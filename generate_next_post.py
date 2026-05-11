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
# 優先順: 環境変数 > リポジトリ内のpublic CSV > ローカルDownloads
_PUBLIC_CSV = ROOT / "data" / "items_public.csv"
_LOCAL_CSV = Path.home() / "Downloads" / "item_sacoche-sacolla.csv"
if os.getenv("ITEM_CSV"):
    CSV_PATH = Path(os.getenv("ITEM_CSV"))
elif _PUBLIC_CSV.exists():
    CSV_PATH = _PUBLIC_CSV
else:
    CSV_PATH = _LOCAL_CSV
NEXT_POST_PATH = ROOT / "data" / "instagram" / "next_post.json"
POSTED_ITEMS_PATH = ROOT / "data" / "instagram" / "posted_items.json"
COVERS_DIR = ROOT / "data" / "instagram" / "covers"
PREVIEW_DIR = ROOT / "logs" / "instagram_preview"
# 過去キャプション履歴(同パターン・同フック繰り返しを避けるためClaudeへの参考として渡す)
CAPTION_HISTORY_PATH = ROOT / "data" / "instagram" / "caption_history.json"
MAX_HISTORY_RECORDS = 20         # ファイルに残す件数
HISTORY_SAMPLES_FOR_PROMPT = 5   # プロンプトに渡す直近件数

# 表紙画像をホスティングする raw.githubusercontent.com のベースURL
GITHUB_RAW_BASE = os.getenv(
    "GITHUB_RAW_BASE",
    "https://raw.githubusercontent.com/masayuki-ido/ec_auto_sourcing/main",
)

MODEL = "claude-sonnet-4-6"
MAX_CAROUSEL_IMAGES = 5
MIN_IMAGES_REQUIRED = 3
# ハッシュタグは5個までに制限(同系統タグ偏重・スパム検知回避)
MAX_HASHTAGS = 5

# 必ず全投稿に付与するベースハッシュタグ(ブランド認知のための1個のみ)
BASE_HASHTAGS = [
    "#サコッシュ",
]

# Claude が商品ごとに「ここから優先して選ぶ」キュレーションプール。
# サコッシュ系に偏らないよう、素材・シーン・ライフスタイル・コーデ系を横断的に用意。
CURATED_HASHTAG_POOL = {
    "形状/用途": [
        "#ショルダーバッグ", "#斜めがけバッグ", "#クロスボディバッグ",
        "#ミニショルダー", "#コンパクトバッグ",
    ],
    "素材": [
        "#帆布バッグ", "#キャンバスバッグ", "#ナイロンバッグ",
        "#レザーバッグ", "#本革バッグ", "#撥水バッグ", "#メッシュバッグ",
    ],
    "シーン": [
        "#お出かけコーデ", "#休日コーデ", "#散歩コーデ", "#旅行コーデ",
        "#通勤コーデ", "#フェスコーデ", "#ライブコーデ",
    ],
    "コーデ/スタイル": [
        "#カジュアルコーデ", "#大人カジュアル", "#シンプルコーデ",
        "#ナチュラルコーデ", "#プチプラコーデ", "#きれいめカジュアル",
    ],
    "ライフスタイル": [
        "#暮らしを楽しむ", "#シンプルライフ", "#一人時間",
        "#身軽に暮らす", "#今日の相棒",
    ],
    "サコッシュ系(使う場合は1個まで)": [
        "#サコッシュコーデ", "#サコッシュバッグ", "#サコッシュショルダー",
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
**構成・トーン・絵文字の使い方を毎回変える**。テンプレ感は最大の敵で、Instagram側のスパム検知にも影響する。

## 切り口を毎回変える(直近投稿のサンプルを参照して、同じ切り口を連続させない)
切り口の例:
- 質問投げかけ:「最近、バッグの中身、増えてませんか?」
- 場面描写:「コンビニまでの5分。手が空いてる安心感。」
- ユーザーの心の声:「軽さって、こんなに大事だったんだ。」
- 数値・サイズ訴求:「160g。卵3個分の重さで、丸一日。」
- 比較訴求:「普通のバッグより一回り小さい、でも入る。」
- コンセプト訴求:「持つほどに肩になじむ一枚。」
- 季節・天気訴求:「梅雨入り前に、撥水を一つ。」

## 本文の構成ルール
- **長さ: 4〜8行(短め推奨)**。長文は読まれない。
- 構成は毎回変える。「フック → ベネフィット3行 → スペック → CTA」のような固定型は禁止。
- スペック情報(サイズ・色・素材・価格)は **入れる/入れない/部分的に入れる** を毎回変える。
- スペックを入れる場合、フォーマットも毎回変える(本文中に自然に組み込む / 1行にまとめる / 箇条書き / カンマ区切り 等)。
- **絶対に使わない**: `──────────` のような枠線、固定の絵文字テンプレ(📐🎨🧵💴を毎回4セット並べる等)。
- 直近投稿サンプルが渡される場合、それらと **冒頭1行・全体構成・絵文字の数と種類が必ず違う** ようにする。

## 厳守事項(変えてはいけないこと)
- 素材名・色名・カテゴリ名は商品情報の表記を1文字も変えずに使う(「ナイロン」を「ナイロム」など絶対NG)
- サイズは商品情報に記載された数値のみ使う。書いてない数値を捏造しない
- サイズが「記載なし」の場合は本文中に書かない、または「サイズ詳細はプロフィールリンクから」のような誘導
- カラーが1色しかない商品で「全N色」と書かない
- 商品説明に書かれていない機能・素材・特徴を勝手に追加しない(機能訴求は商品データに基づく事実のみ)
- CTAには必ず @sacoche_sacolla を1回入れる(タップ可能な誘導リンク)

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

{recent_history}

出力JSONフォーマット:
{{
  "body": "<本文。改行は \\n。4〜8行で簡潔に。構成は毎回変える(固定テンプレ禁止)>",
  "hashtags": ["#xxx", "#yyy", ...],
  "cover_top": "<表紙上部の【】内に入る訴求文(8〜15文字目安)。商品の最大の強みを言い切る。例: コンパクトなのに収納抜群 / 通勤バッグの新定番 / 軽さは正義 / 旅にも普段にも / プチプラで大人見え>",
  "cover_left": "<表紙左側の縦書き(4〜7文字)。商品の特徴・形容を表す短文。例: 軽いコンパクト / 上質レザー / 撥水ナイロン / シンプル美人>",
  "cover_right": "<表紙右側の縦書き(4〜6文字)。商品カテゴリ系で固定気味。例: サコッシュ / ショルダー / クロスバッグ>"
}}

hashtagsの選び方(重要):
- **以下のキュレーションプールから幅広く、ジャンルを散らして** 選ぶ
  {curated_pool}
- 個数: **3〜4個**(ベースタグ {base_tags} と合算して5個以内になるよう調整)
- 同じカテゴリ(例: 形状/用途)から複数選ばない。素材・シーン・コーデ・ライフスタイルから散らす
- サコッシュ系タグは使うとしても1個まで(検索流入は #サコッシュ 単体に任せる)
- 自作タグは追加しない(プールにあるタグのみ使用)
- ベースタグ {base_tags} は出力に含めない(後段で自動付与)

cover_* の制約:
- cover_top は 【】で囲まれて表示されるので、それ自体には 【】 を含めない。**毎回違う訴求**にする
- cover_left / cover_right はそれぞれ縦書きで表示される。文字数厳守(長いと画像からはみ出す)
- cover_left = 商品の「特徴・形容」(例: 軽いコンパクト、上質レザー、撥水ナイロン)、cover_right = 商品の「カテゴリ」(例: サコッシュ、ショルダー)
- 全て商品情報に裏付けのある内容のみ。素材・カテゴリは原文表記そのまま
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


def load_caption_history() -> list[dict]:
    """直近のキャプション履歴を取得。
    初回(ファイル無し)は data/instagram/posted/*.json から自動シードする。"""
    if CAPTION_HISTORY_PATH.exists():
        return json.loads(CAPTION_HISTORY_PATH.read_text(encoding="utf-8"))
    history: list[dict] = []
    posted_dir = ROOT / "data" / "instagram" / "posted"
    if posted_dir.exists():
        for f in sorted(posted_dir.glob("*.json")):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                history.append({
                    "saved_at": d.get("posted_at", ""),
                    "item_id": str(d.get("item_id", "")),
                    "caption": d.get("caption", ""),
                })
            except Exception:
                pass
    return history


def append_caption_history(item_id: str, caption: str) -> None:
    """新しいキャプションを履歴に追加し、最新 MAX_HISTORY_RECORDS 件を保持。"""
    history = load_caption_history()
    history.append({
        "saved_at": datetime.now().isoformat(),
        "item_id": str(item_id),
        "caption": caption,
    })
    history = history[-MAX_HISTORY_RECORDS:]
    CAPTION_HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    CAPTION_HISTORY_PATH.write_text(
        json.dumps(history, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_recent_history_section() -> str:
    """プロンプトに差し込む「直近投稿サンプル」セクションを構築。"""
    history = load_caption_history()
    if not history:
        return ""
    samples = history[-HISTORY_SAMPLES_FOR_PROMPT:]
    blocks = []
    for h in samples:
        cap = (h.get("caption") or "").strip()
        if not cap:
            continue
        # ハッシュタグ行は冗長なので分離して本文だけ提示
        body_only = cap.split("\n\n#")[0].strip()
        blocks.append(f"--- 過去投稿 (item {h.get('item_id', '?')}) ---\n{body_only}")
    if not blocks:
        return ""
    joined = "\n\n".join(blocks)
    return (
        "## 直近投稿サンプル(これらと冒頭1行・全体構成・絵文字の使い方が必ず違うようにする)\n"
        f"{joined}\n"
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


# Instagram カルーセル投稿のアスペクト比制約 (公式: 0.8〜1.91)
IG_ASPECT_MIN = 0.8
IG_ASPECT_MAX = 1.91


def _is_ig_compatible(image_url: str) -> bool:
    """画像URLをHEAD的にダウンロードしてアスペクト比をチェック"""
    try:
        from io import BytesIO
        from PIL import Image
        import requests as _req
        res = _req.get(image_url, timeout=15)
        if not res.ok:
            return False
        img = Image.open(BytesIO(res.content))
        w, h = img.size
        if h == 0:
            return False
        ratio = w / h
        return IG_ASPECT_MIN <= ratio <= IG_ASPECT_MAX
    except Exception as e:
        logger.warning(f"アスペクト比チェック失敗 {image_url}: {e}")
        return False


def filter_ig_compatible(urls: list[str]) -> list[str]:
    """カルーセル投稿規格に合う画像URLだけ残す"""
    kept = []
    for u in urls:
        if _is_ig_compatible(u):
            kept.append(u)
        else:
            logger.warning(f"アスペクト比NGで除外: {u}")
    return kept


def has_real_size(row: dict) -> bool:
    sd = (row.get("size_description") or "").strip()
    return bool(sd) and sd != "記載なし"


def score(row: dict) -> float:
    """is_popular > サイズ記載あり > display(小さいほど高優先)"""
    s = 0.0
    if row.get("is_popular") == "true":
        s += 100.0
    if has_real_size(row):
        s += 50.0  # サイズが入ってる商品を優遇
    try:
        display = int(row.get("display", "9999"))
    except ValueError:
        display = 9999
    s += 1000.0 / max(display, 1)
    return s


def pick_product(
    rows: list[dict],
    posted: set[str],
    item_id: str | None,
    color_filter: str | None = None,
) -> dict:
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
    if color_filter:
        candidates = [r for r in candidates if color_filter in (r.get("color") or "")]
    if not candidates:
        raise RuntimeError(
            "投稿候補がありません"
            f"{' (color=' + color_filter + ')' if color_filter else ''}"
        )

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
        recent_history=build_recent_history_section(),
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
    """BASE_HASHTAGS を先頭に、生成タグを後ろに。重複除去 + MAX_HASHTAGS で打ち切り。"""
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
    if len(merged) > MAX_HASHTAGS:
        logger.info(f"ハッシュタグ {len(merged)}個 → {MAX_HASHTAGS}個に切り詰め")
        merged = merged[:MAX_HASHTAGS]
    return merged


def _fix_material_in_body(body: str, expected_material: str) -> str:
    """🧵 素材: 行に書かれた素材が expected と異なれば修正。基本ガード"""
    import re as _re
    if not expected_material or expected_material == "バッグ":
        return body
    pattern = r"(🧵\s*素材[::]\s*)([^\n]+)"
    m = _re.search(pattern, body)
    if not m:
        return body
    written = m.group(2).strip()
    if expected_material not in written:
        logger.warning(f"素材表記の不一致を修正: 「{written}」→「{expected_material}」")
        body = _re.sub(pattern, lambda mm: f"{mm.group(1)}{expected_material}", body, count=1)
    return body


def build_post(
    product: dict,
    skip_cover: bool = False,
    cover_image_override: str | None = None,
    cover_top_override: str | None = None,
    cover_left_override: str | None = None,
    cover_right_override: str | None = None,
    bg_index: int | None = None,
) -> dict:
    product_images = collect_images(product)
    # Instagram規格外(アスペクト比0.8〜1.91外)を除外
    product_images = filter_ig_compatible(product_images)
    gen = generate_caption(product)
    body = gen["body"].strip()
    # 素材表記のセーフティネット(Claudeが誤った場合に category 由来の正値で上書き)
    cat_id = (product.get("category_id") or "").split(",")[0]
    expected_material = CATEGORY_LABEL.get(cat_id, "バッグ")
    body = _fix_material_in_body(body, expected_material)
    tags = merge_hashtags(gen.get("hashtags", []))
    caption = f"{body}\n\n{' '.join(tags)}"

    cover_local: Path | None = None
    cover_url: str = ""
    if not skip_cover and (product_images or cover_image_override):
        try:
            if cover_image_override:
                cover_src_url = cover_image_override
            elif len(product_images) >= 4:
                cover_src_url = product_images[3]
            else:
                cover_src_url = product_images[-1]
            cover_local = make_cover(
                image_url=cover_src_url,
                top_text=cover_top_override or gen.get("cover_top", "今日のおすすめ"),
                bottom_text=gen.get("cover_bottom", ""),
                out_path=COVERS_DIR / f"{product['item_id']}.jpg",
                item_id=product["item_id"],
                price="",
                cover_left=cover_left_override or gen.get("cover_left", "サコッシュ"),
                cover_right=cover_right_override or gen.get("cover_right", "サコッシュ"),
                bg_index=bg_index,
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
        "cover_left": gen.get("cover_left", ""),
        "cover_right": gen.get("cover_right", ""),
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
    parser.add_argument("--color", help="指定色を含む商品に絞る (例: --color ブラック)")
    parser.add_argument("--cover-image", help="表紙ソース画像を上書き (URLまたはローカルパス)")
    parser.add_argument("--cover-left", help="表紙の左縦書きを上書き")
    parser.add_argument("--cover-right", help="表紙の右縦書きを上書き")
    parser.add_argument("--cover-top", help="表紙の【】タイトルを上書き")
    parser.add_argument("--bg-index", type=int, help="表紙背景色をパレット番号で指定 (0=mint, 1=pink, 2=mustard, 3=gray, 4=beige, 5=sage, 6=lavender, 7=peach)")
    args = parser.parse_args()

    rows = load_csv()
    posted = load_posted_items()
    logger.info(f"CSV: {len(rows)}件 / 投稿済み: {len(posted)}件")

    product = pick_product(rows, posted, args.item_id, color_filter=args.color)
    logger.info(
        f"選定: [{product['item_id']}] {product['name']} ¥{product['price']} "
        f"(popular={product.get('is_popular')}, display={product.get('display')})"
    )

    post = build_post(
        product,
        cover_image_override=args.cover_image,
        cover_top_override=args.cover_top,
        cover_left_override=args.cover_left,
        cover_right_override=args.cover_right,
        bg_index=args.bg_index,
    )
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
        append_caption_history(product["item_id"], post["caption"])
        logger.info("caption_history.json に追加")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
