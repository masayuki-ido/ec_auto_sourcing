"""
Instagram 投稿候補を自動生成して data/instagram/next_post.json に書き込む。

- 商品CSV(管理画面エクスポート)から人気・トレンド優先で1件選定
- 商品画像をカルーセル化(images1〜images5)
- Claude Sonnet でキャプション本文 + 個別ハッシュタグを生成
- BASE_HASHTAGS と結合(重複除去)して書き出し
- 投稿済み item_id を data/instagram/posted_items.json に記録(重複回避)

使い方:
    python generate_next_post.py
    python generate_next_post.py --dry-run
    python generate_next_post.py --item-id 123        # 特定商品で生成
    python generate_next_post.py --no-record          # 投稿済み記録に追加しない
    ITEM_CSV=/path/to.csv python generate_next_post.py
"""
from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import logging
import os
import random
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from utils.cover_image import make_cover

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DEFAULT_CSV = Path.home() / "Downloads" / "item_sacoche-sacolla.csv"
CSV_PATH = Path(os.getenv("ITEM_CSV", str(DEFAULT_CSV)))
NEXT_POST_PATH = ROOT / "data" / "instagram" / "next_post.json"
POSTED_ITEMS_PATH = ROOT / "data" / "instagram" / "posted_items.json"
COVERS_DIR = ROOT / "data" / "instagram" / "covers"
PREVIEW_DIR = ROOT / "logs" / "instagram_preview"

# 表紙画像をホスティングする raw.githubusercontent.com のベースURL
GITHUB_RAW_BASE = os.getenv(
    "GITHUB_RAW_BASE",
    "https://raw.githubusercontent.com/masayuki-ido/ec_auto_sourcing/main",
)

MODEL = "claude-sonnet-4-6"
MAX_CAROUSEL_IMAGES = 5
MIN_IMAGES_REQUIRED = 3

# 必ず全投稿に付与するベースハッシュタグ(順序維持で先頭側に並ぶ)
BASE_HASHTAGS = [
    "#サコッシュ",
    "#サコッシュコーデ",
    "#サコッシュバッグ",
    "#サコッシュショルダー",
]

# Claude が商品ごとに「ここから優先して選ぶ」キュレーションプール。
# 日本のファッション/バッグ系Instagramでよく使われるタグを手選定したもの。
# (※リアルタイムの投稿数取得ではなく、運用知見ベース。インサイト蓄積後に随時更新)
CURATED_HASHTAG_POOL = {
    "汎用コーデ系(大ボリューム)": [
        "#お出かけコーデ", "#今日のコーデ", "#毎日コーデ", "#コーデ記録",
        "#大人コーデ", "#大人カジュアル", "#大人女子コーデ", "#きれいめコーデ",
        "#シンプルコーデ", "#カジュアルコーデ", "#休日コーデ", "#通勤コーデ",
        "#プチプラコーデ", "#プチプラファッション", "#ママコーデ",
    ],
    "バッグ系(中ボリューム・関連性高)": [
        "#ショルダーバッグ", "#バッグコーデ", "#バッグ通販", "#バッグ好き",
        "#バッグ好きな人と繋がりたい", "#新作バッグ", "#お気に入りバッグ",
        "#お出かけバッグ", "#斜め掛けバッグ", "#斜めがけバッグ",
        "#ミニバッグ", "#コンパクトバッグ", "#軽量バッグ",
    ],
    "素材別": [
        "#レザーバッグ", "#本革バッグ", "#本革好き",
        "#ナイロンバッグ", "#帆布バッグ", "#キャンバスバッグ", "#PUレザー",
    ],
    "スタイル/世界観": [
        "#ミニマリストコーデ", "#ミニマリスト", "#ミニマルファッション",
        "#韓国コーデ", "#韓国ファッション", "#ナチュラルコーデ",
        "#ユニセックスファッション",
    ],
    "用途/シーン": [
        "#プレゼント", "#ギフト", "#誕生日プレゼント",
        "#旅行コーデ", "#旅行バッグ", "#マザーズバッグ", "#通勤バッグ", "#手ぶら派",
    ],
    "英語タグ(海外リーチ用、2〜3個まで)": [
        "#sacoche", "#bagstagram", "#minimalbag", "#leatherbag",
        "#dailyoutfit", "#japanesefashion",
    ],
}

CATEGORY_LABEL = {
    "1": "合皮レザー",
    "2": "キャンバス・帆布",
    "3": "ナイロン",
    "4": "本革",
    "5": "コットン",
    "6": "防水・撥水",
    "7": "クリア・PVC",
    "8": "メッシュ",
}

CAPTION_SYSTEM = """あなたはサコッシュ・ショルダーバッグ専門ECショップのInstagram運用担当です。
新着・人気商品を紹介する投稿のキャプションを作成してください。

トーン: 親しみやすく上品。装飾的すぎない。読者の生活シーンが想像できる文章。

本文の構成 (JSON の "body" に入れる):
1. フック (1行) — 商品の魅力を凝縮した一行コピー。絵文字は0〜2個まで
2. 空行
3. ベネフィット (3行) — 特徴ではなく「ユーザーの生活でどう嬉しいか」を3行で
4. 空行
5. スペックブロック — 以下の形式で商品情報を箇条書き
   ──────────
   📐 サイズ: <寸法を読みやすく整形。例「W22 × H14.5 × D3cm / ストラップ140cm」>
   🎨 カラー: <カンマ区切りを「・」で区切り直す>
   🧵 素材: <商品説明から素材名を抽出。原文表記そのまま>
   💴 価格: ¥<価格を3桁カンマ区切り>
   ──────────
6. 空行
7. CTA (1行) — 「プロフィールリンクから」「他カラーもチェック」など軽い誘導

厳守事項:
- 素材名・色名・カテゴリ名は商品情報の表記を1文字も変えずに使うこと(「ナイロン」を「ナイロム」など絶対NG)
- サイズは商品情報に記載された数値のみ使う。書いてない数値を捏造しない
- サイズが「記載なし」の場合は「📐 サイズ: お問い合わせください」と書く
- カラーが1色しかない商品で「全N色」と書かない
- 商品説明に書かれていない機能・素材・特徴を勝手に追加しない

出力は JSON 1個のみ。マークダウンや前置き禁止。"""

CAPTION_USER_TEMPLATE = """以下の商品からキャプションを作成してください。

商品名: {name}
価格: {price}円
カラー展開: {color}
カテゴリ: {category}
商品説明:
{description}

サイズ情報(原文):
{size_description}

追加説明(機能・素材詳細):
{additional}

出力JSONフォーマット:
{{
  "body": "<本文。改行は \\n。フック/空行/ベネフィット3行/空行/スペックブロック/空行/CTA の構成>",
  "hashtags": ["#xxx", "#yyy", ...],
  "cover_top": "<表紙画像の上部に入る短い煽り(8〜14文字目安)。例: 大切な人へのプレゼントに / 通勤がもっと身軽に / 週末コーデの相棒に >",
  "cover_bottom": "<表紙画像の下部に入る大字。改行 \\n で2行構成 (例: 本革\\nサコッシュ / 帆布\\nショルダー)。素材+カテゴリの組み合わせを基本とする>"
}}

hashtagsの選び方(重要):
- **以下のキュレーションプールから優先して選ぶこと**(運用で当たり傾向のあるタグ群)
  {curated_pool}
- 上記プールから商品に合うものを **12〜13個** 選ぶ
- それに加えて、商品名・素材・カラー固有の **個別タグを2〜3個** 自由に作って良い
- 合計 15個 にする
- 英語タグは2〜3個まで
- 以下のベースタグは出力に含めないでください(後段で自動付与): {base_tags}

cover_top / cover_bottom の制約:
- cover_top は ＼／ で囲まれて表示されるので、それ自体には ＼／ を含めない
- cover_bottom は 1行 4〜6文字 × 2行を目安に。長すぎると画像からはみ出す
- どちらも商品情報に裏付けのある内容のみ。素材・カテゴリは原文表記そのまま
"""


def load_csv() -> list[dict]:
    if not CSV_PATH.exists():
        raise FileNotFoundError(
            f"商品CSVが見つかりません: {CSV_PATH}\n"
            f"  add_netsea.py 実行時に管理画面からダウンロードされる想定です。\n"
            f"  ITEM_CSV 環境変数で別パス指定可。"
        )
    with CSV_PATH.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_posted_items() -> set[str]:
    if not POSTED_ITEMS_PATH.exists():
        return set()
    return set(json.loads(POSTED_ITEMS_PATH.read_text(encoding="utf-8")))


def save_posted_items(item_ids: set[str]) -> None:
    POSTED_ITEMS_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTED_ITEMS_PATH.write_text(
        json.dumps(sorted(item_ids, key=lambda x: int(x)), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def collect_images(row: dict, max_n: int = MAX_CAROUSEL_IMAGES) -> list[str]:
    urls: list[str] = []
    for i in range(1, 11):
        url = (row.get(f"images{i}") or "").strip()
        if url.startswith("http"):
            urls.append(url)
        if len(urls) >= max_n:
            break
    return urls


def score(row: dict) -> float:
    """is_popular=true を最優先、次に display(小さいほど高優先)"""
    s = 0.0
    if row.get("is_popular") == "true":
        s += 100.0
    try:
        display = int(row.get("display", "9999"))
    except ValueError:
        display = 9999
    s += 1000.0 / max(display, 1)
    return s


def pick_product(rows: list[dict], posted: set[str], item_id: str | None) -> dict:
    if item_id:
        for r in rows:
            if r["item_id"] == str(item_id):
                return r
        raise ValueError(f"item_id={item_id} がCSVに見つかりません")

    candidates = [
        r for r in rows
        if r["item_id"] not in posted
        and r.get("hide") == "false"
        and len(collect_images(r)) >= MIN_IMAGES_REQUIRED
    ]
    if not candidates:
        raise RuntimeError("投稿候補がありません(全件投稿済み or 画像不足)")

    candidates.sort(key=score, reverse=True)
    top = candidates[: min(10, len(candidates))]
    return random.choice(top)


def generate_caption(product: dict) -> dict:
    """Claude で本文・ハッシュタグ・表紙テキストを生成"""
    client = Anthropic()
    cat_id = (product.get("category_id") or "").split(",")[0]
    cat_label = CATEGORY_LABEL.get(cat_id, "バッグ")
    pool_str = "\n".join(
        f"  ・{cat}: {' '.join(tags)}" for cat, tags in CURATED_HASHTAG_POOL.items()
    )
    user_msg = CAPTION_USER_TEMPLATE.format(
        name=product["name"],
        price=product["price"],
        color=(product.get("color") or "").replace(",", "・") or "—",
        category=cat_label,
        description=(product.get("description") or "")[:600],
        size_description=(product.get("size_description") or "記載なし")[:500],
        additional=(product.get("additional_description") or "")[:800],
        base_tags=", ".join(BASE_HASHTAGS),
        curated_pool=pool_str,
    )

    res = client.messages.create(
        model=MODEL,
        max_tokens=1500,
        system=CAPTION_SYSTEM,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = res.content[0].text.strip()

    # ```json ... ``` で包まれている場合に備えてストリップ
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        raw = raw.lstrip("json").strip()

    return json.loads(raw)


def merge_hashtags(generated: list[str]) -> list[str]:
    """BASE_HASHTAGS を先頭に、生成タグを後ろに。重複除去。"""
    seen: set[str] = set()
    merged: list[str] = []
    for tag in BASE_HASHTAGS + generated:
        t = tag.strip()
        if not t:
            continue
        if not t.startswith("#"):
            t = "#" + t
        if t not in seen:
            seen.add(t)
            merged.append(t)
    return merged


def build_post(product: dict, skip_cover: bool = False) -> dict:
    product_images = collect_images(product)
    gen = generate_caption(product)
    body = gen["body"].strip()
    tags = merge_hashtags(gen.get("hashtags", []))
    caption = f"{body}\n\n{' '.join(tags)}"

    cover_local: Path | None = None
    cover_url: str = ""
    if not skip_cover and product_images:
        try:
            cover_local = make_cover(
                image_url=product_images[0],
                top_text=gen.get("cover_top", "今日のおすすめ"),
                bottom_text=gen.get("cover_bottom", product["name"][:8]),
                out_path=COVERS_DIR / f"{product['item_id']}.jpg",
            )
            cover_url = f"{GITHUB_RAW_BASE}/data/instagram/covers/{product['item_id']}.jpg"
            logger.info(f"表紙生成: {cover_local}")
        except Exception as e:
            logger.warning(f"表紙生成失敗 (続行): {e}")

    # 表紙 + 商品画像 でカルーセル構成
    images = ([cover_url] if cover_url else []) + product_images
    images = images[:10]  # Instagramカルーセル上限

    base = {
        "item_id": product["item_id"],
        "caption": caption,
        "cover_top": gen.get("cover_top", ""),
        "cover_bottom": gen.get("cover_bottom", ""),
    }
    if len(images) >= 2:
        base.update({
            "media_type": "carousel",
            "image_urls": images,
            "image_url": "",
        })
    else:
        base.update({
            "media_type": "single",
            "image_url": images[0] if images else "",
            "image_urls": [],
        })
    # プレビューでローカル画像も表示できるようにメタとして保持
    if cover_local:
        base["_cover_local"] = str(cover_local)
    return base


def render_preview_html(post: dict, product: dict) -> Path:
    """next_post.json の内容をInstagram風に表示するHTMLを生成"""
    images = list(post.get("image_urls") or ([post["image_url"]] if post.get("image_url") else []))
    # 表紙はGitHubにpush前なので、ローカルJPGを base64 dataURL に埋め込んで表示
    cover_local = post.get("_cover_local")
    if cover_local and images and Path(cover_local).exists():
        b64 = base64.b64encode(Path(cover_local).read_bytes()).decode("ascii")
        images[0] = f"data:image/jpeg;base64,{b64}"
    caption_html = html.escape(post.get("caption", "")).replace("\n", "<br>")
    images_html = "\n".join(
        f'<div class="slide"><span class="num">{i+1}/{len(images)}</span>'
        f'<img src="{html.escape(url)}" loading="lazy"></div>'
        for i, url in enumerate(images)
    )
    page = f"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8">
<title>IG Preview - item {product['item_id']}</title>
<style>
  body {{ font-family: -apple-system, sans-serif; background:#fafafa; margin:0; padding:24px; }}
  .post {{ max-width: 540px; margin: 0 auto; background:#fff; border:1px solid #dbdbdb; border-radius:8px; overflow:hidden; }}
  .header {{ padding: 12px 16px; border-bottom:1px solid #efefef; display:flex; align-items:center; gap:10px; }}
  .avatar {{ width:32px; height:32px; border-radius:50%; background:linear-gradient(135deg,#f58529,#dd2a7b,#8134af); }}
  .username {{ font-weight:600; font-size:14px; }}
  .carousel {{ display:flex; overflow-x:auto; scroll-snap-type: x mandatory; aspect-ratio: 1/1; background:#000; }}
  .slide {{ flex: 0 0 100%; scroll-snap-align: start; position:relative; display:flex; align-items:center; justify-content:center; }}
  .slide img {{ max-width:100%; max-height:100%; object-fit:contain; }}
  .num {{ position:absolute; top:8px; right:12px; background:rgba(0,0,0,.6); color:#fff; padding:2px 10px; border-radius:12px; font-size:12px; }}
  .caption {{ padding:14px 16px; font-size:14px; line-height:1.55; color:#262626; white-space:normal; }}
  .meta {{ padding:8px 16px 14px; font-size:12px; color:#8e8e8e; border-top:1px solid #efefef; }}
  .meta b {{ color:#262626; }}
</style></head><body>
<div class="post">
  <div class="header"><div class="avatar"></div><div class="username">sacoche_sacolla</div></div>
  <div class="carousel">{images_html}</div>
  <div class="caption">{caption_html}</div>
  <div class="meta">
    <b>item_id:</b> {product['item_id']} &nbsp;
    <b>name:</b> {html.escape(product.get('name',''))} &nbsp;
    <b>¥{html.escape(product.get('price',''))}</b> &nbsp;
    <b>popular:</b> {product.get('is_popular','')} &nbsp;
    <b>display:</b> {product.get('display','')}
  </div>
</div>
</body></html>"""
    PREVIEW_DIR.mkdir(parents=True, exist_ok=True)
    out = PREVIEW_DIR / f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_item{product['item_id']}.html"
    out.write_text(page, encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="next_post.json を書き換えない")
    parser.add_argument("--item-id", help="特定商品IDで生成")
    parser.add_argument("--no-record", action="store_true", help="posted_items.json に追加しない")
    parser.add_argument("--preview", action="store_true", help="生成内容をブラウザで開く")
    parser.add_argument("--no-open", action="store_true", help="--preview 時にブラウザを開かない (HTMLだけ書き出し)")
    args = parser.parse_args()

    rows = load_csv()
    posted = load_posted_items()
    logger.info(f"CSV: {len(rows)}件 / 投稿済み: {len(posted)}件")

    product = pick_product(rows, posted, args.item_id)
    logger.info(
        f"選定: [{product['item_id']}] {product['name']} ¥{product['price']} "
        f"(popular={product.get('is_popular')}, display={product.get('display')})"
    )

    post = build_post(product)
    n_images = len(post.get("image_urls") or []) or (1 if post.get("image_url") else 0)
    logger.info(f"画像枚数: {n_images} / media_type={post['media_type']}")
    logger.info(f"\n----- caption -----\n{post['caption']}\n-------------------")

    if args.preview:
        preview_path = render_preview_html(post, product)
        logger.info(f"プレビュー: {preview_path}")
        if not args.no_open:
            subprocess.run(["open", str(preview_path)], check=False)

    if args.dry_run:
        logger.info("--dry-run: 書き込みスキップ")
        return

    NEXT_POST_PATH.parent.mkdir(parents=True, exist_ok=True)
    public_post = {k: v for k, v in post.items() if not k.startswith("_")}
    NEXT_POST_PATH.write_text(
        json.dumps(public_post, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    logger.info(f"書き込み完了: {NEXT_POST_PATH}")

    if not args.no_record:
        posted.add(product["item_id"])
        save_posted_items(posted)
        logger.info(f"posted_items.json 更新 ({len(posted)}件)")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
