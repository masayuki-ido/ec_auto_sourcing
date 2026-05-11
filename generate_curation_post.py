"""
おすすめサコッシュN選 投稿候補を自動生成。

実行例:
    python generate_curation_post.py --theme 本革
    python generate_curation_post.py --theme 帆布 --count 5 --dry-run
    python generate_curation_post.py --theme コスパ --count 5

next_post.json を上書きし、Issue起票は generate_daily.yml の手動実行で行う想定
(現在の運用: candidate JSON は手動投稿用なので Issue は scripts/build_issue_body.py で同様に作れる)。
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

from anthropic import Anthropic
from dotenv import load_dotenv

from utils.curation_image import make_curation_cover, make_product_slide
from utils.cover_image import _download, _get_session
from rembg import remove
from generate_next_post import (
    load_csv,
    load_posted_items,
    collect_images,
    score,
    MIN_IMAGES_REQUIRED,
    CATEGORY_LABEL,
    CURATED_HASHTAG_POOL,
    MODEL,
    NEXT_POST_PATH,
    append_caption_history,
)

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
CURATION_DIR_BASE = ROOT / "data" / "instagram" / "curation"
GITHUB_RAW_BASE = os.getenv(
    "GITHUB_RAW_BASE",
    "https://raw.githubusercontent.com/masayuki-ido/ec_auto_sourcing/main",
)


def _to_int(v) -> int:
    try:
        return int(str(v or "").replace(",", ""))
    except (ValueError, TypeError):
        return 999999


THEME_DEFS: dict[str, dict] = {
    "本革": {
        "label": "本革サコッシュ",
        "audience": "コスパで選ばない大人の",
        "filter": lambda r: r.get("category_id", "").split(",")[0] == "4",
    },
    "帆布": {
        "label": "帆布サコッシュ",
        "audience": "ナチュラル派が選ぶ",
        "filter": lambda r: r.get("category_id", "").split(",")[0] == "2",
    },
    "ナイロン": {
        "label": "ナイロンサコッシュ",
        "audience": "アクティブ派の必需品",
        "filter": lambda r: r.get("category_id", "").split(",")[0] in ("3", "6"),
    },
    "コスパ": {
        "label": "5,000円以下サコッシュ",
        "audience": "プチプラ派の本気",
        "filter": lambda r: _to_int(r.get("price")) <= 5000,
    },
    "コンパクト": {
        "label": "コンパクトサコッシュ",
        "audience": "身軽派のための",
        # サイズが小さい目安: size_description にW20以下が含まれる か display順の上位
        "filter": lambda r: True,  # 全件OK、score で人気順
    },
}


CURATION_PROMPT = """あなたはサコッシュ・ショルダーバッグ専門ECショップのInstagram運用担当です。
これから「{theme_label} {n}選」のカルーセル投稿(Instagram)を作ります。

選定した{n}商品の情報をお渡しします。以下を生成してください:
1. 各商品の「推したい理由」3点(各28文字以内、絵文字なし、商品データに書かれた事実に基づく)
2. 全体キャプション本文(投稿全体を紹介する文、4〜7行、テンプレ感を避ける、自然な日本語)
3. ハッシュタグ4個(プールから、ジャンルを散らして、サコッシュ系は1個まで)

## 商品リスト
{products_json}

## ハッシュタグキュレーションプール
{hashtag_pool}

## 厳守事項
- 推し理由は商品データに書かれた事実のみ(description, size_description, color, material)
- 「軽さ」「コンパクト」などの形容も、データに数値や記述がない場合は使わない
- キャプション末尾には @sacoche_sacolla への誘導を1回入れる
- ハッシュタグはキャプションには含めない(別フィールド)
- 出力JSONのみ。マークダウン・前置き禁止

出力JSONフォーマット:
{{
  "items": [
    {{"item_id": "<元のitem_id>", "reasons": ["...", "...", "..."]}},
    ...
  ],
  "caption": "<全体キャプション>",
  "hashtags": ["#xxx", "#yyy", "#zzz", "#www"]
}}
"""


def pick_product_only_image(image_urls: list[str], max_check: int = 5) -> str:
    """商品単体写真(モデル着用カットでないもの)を優先して選ぶ。
    rembgで前景抽出後、alpha bbox の縦横比 × 前景占有率 のスコアで判定。
    バッグ単体は横長(ratio低)で背景が大きい(occupancy低)→ スコア低
    人物は縦長(ratio高)で画面を多く占める(occupancy高)→ スコア高"""
    import numpy as np
    if not image_urls:
        return ""
    best_url = image_urls[0]
    best_score = float("inf")
    session = _get_session()
    for url in image_urls[:max_check]:
        try:
            src = _download(url)
            no_bg = remove(src, session=session)
            bbox = no_bg.getbbox()
            if not bbox:
                continue
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w <= 0 or h <= 0:
                continue
            ratio = h / w
            alpha = np.array(no_bg.split()[-1])
            occupancy = (alpha > 30).sum() / max(alpha.size, 1)
            score = ratio * (1 + occupancy * 1.5)
            if score < best_score:
                best_score = score
                best_url = url
        except Exception:
            continue
    return best_url


def shorten_product_name(name: str) -> str:
    """5選スライド表示用に冗長な接頭辞を除去。"""
    s = (name or "").strip()
    for prefix in ("サコッシュ ", "サコッシュ・", "サコッシュ/"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    return s


def filter_candidates(rows, posted_ids, theme_filter, color_filter=None):
    cands = [
        r for r in rows
        if r["item_id"] not in posted_ids
        and r.get("hide") == "false"
        and len(collect_images(r)) >= MIN_IMAGES_REQUIRED
        and theme_filter(r)
    ]
    if color_filter:
        cands = [r for r in cands if color_filter in (r.get("color") or "")]
    return cands


def generate_content(theme_label: str, products: list[dict]) -> dict:
    client = Anthropic()
    products_for_prompt = []
    for p in products:
        cat_id = (p.get("category_id") or "").split(",")[0]
        products_for_prompt.append({
            "item_id": p["item_id"],
            "name": p["name"],
            "price": p["price"],
            "color": (p.get("color") or "").replace(",", "・"),
            "category": CATEGORY_LABEL.get(cat_id, "バッグ"),
            "description": (p.get("description") or "")[:300],
            "size_description": (p.get("size_description") or "記載なし")[:200],
            "additional": (p.get("additional_description") or "")[:300],
        })
    pool_str = "\n".join(
        f"  ・{cat}: {' '.join(tags)}" for cat, tags in CURATED_HASHTAG_POOL.items()
    )
    user_msg = CURATION_PROMPT.format(
        theme_label=theme_label,
        n=len(products),
        products_json=json.dumps(products_for_prompt, ensure_ascii=False, indent=2),
        hashtag_pool=pool_str,
    )
    res = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        messages=[{"role": "user", "content": user_msg}],
    )
    raw = res.content[0].text.strip()
    if raw.startswith("```"):
        parts = raw.split("```")
        raw = parts[1] if len(parts) > 1 else raw
        raw = raw.lstrip("json").strip()
    return json.loads(raw)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", required=True, choices=list(THEME_DEFS.keys()))
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-record", action="store_true", help="caption_history.json に記録しない")
    parser.add_argument("--color", help="色フィルタ")
    args = parser.parse_args()

    theme = THEME_DEFS[args.theme]
    rows = load_csv()
    posted = load_posted_items()
    logger.info(f"CSV: {len(rows)}件 / 投稿済み: {len(posted)}件")

    candidates = filter_candidates(rows, posted, theme["filter"], args.color)
    logger.info(f"テーマ「{args.theme}」候補: {len(candidates)}件")
    if len(candidates) < args.count:
        logger.error(f"候補が不足: {len(candidates)} < {args.count}")
        sys.exit(2)

    candidates.sort(key=score, reverse=True)
    selected = candidates[: args.count]
    logger.info(f"選定: {[(p['item_id'], p['name'][:20]) for p in selected]}")

    content = generate_content(theme["label"], selected)

    # 画像生成
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    run_dir = CURATION_DIR_BASE / args.theme / run_id
    run_dir.mkdir(parents=True, exist_ok=True)
    image_urls: list[str] = []

    # 表紙 (プレビュー画像は selected の先頭3件から、商品単体写真を選ぶ)
    preview_images: list[str] = []
    for p in selected[:3]:
        imgs = collect_images(p, max_n=10)
        if imgs:
            preview_images.append(pick_product_only_image(imgs))
    cover_path = run_dir / "01_cover.jpg"
    make_curation_cover(
        theme_title=theme["label"],
        theme_subtitle=f"{args.count}選",
        audience_label=theme["audience"],
        preview_images=preview_images,
        out_path=cover_path,
    )
    cover_url = f"{GITHUB_RAW_BASE}/data/instagram/curation/{args.theme}/{run_id}/01_cover.jpg"
    image_urls.append(cover_url)
    logger.info(f"表紙生成: {cover_path}")

    # 各商品スライド
    items_by_id: dict[str, dict] = {x["item_id"]: x for x in content.get("items", [])}
    for idx, product in enumerate(selected, start=2):
        reasons = items_by_id.get(product["item_id"], {}).get("reasons", [])
        if len(reasons) < 3:
            # フォールバック: 商品データから抽出
            color = (product.get("color") or "").replace(",", "・") or "—"
            reasons = (reasons + [
                f"カラー展開: {color}",
                f"カテゴリ: {CATEGORY_LABEL.get((product.get('category_id') or '').split(',')[0], 'バッグ')}",
                f"価格: ¥{int(product['price']):,}",
            ])[:3]

        prod_images = collect_images(product, max_n=10)
        prod_url = pick_product_only_image(prod_images) if prod_images else ""
        slide_path = run_dir / f"{idx:02d}_item_{product['item_id']}.jpg"
        price_text = f"¥{int(product['price']):,}"
        make_product_slide(
            product_image_url=prod_url,
            product_name=shorten_product_name(product["name"]),
            price_text=price_text,
            reasons=reasons,
            theme_label=f"{theme['label']} {args.count}選",
            slide_no=idx,
            total_slides=args.count + 1,
            out_path=slide_path,
            item_id=product["item_id"],
        )
        slide_url = (
            f"{GITHUB_RAW_BASE}/data/instagram/curation/{args.theme}/"
            f"{run_id}/{idx:02d}_item_{product['item_id']}.jpg"
        )
        image_urls.append(slide_url)
        logger.info(f"スライド {idx}: {product['item_id']} → {slide_path.name}")

    # キャプション + ハッシュタグ整形
    caption_body = (content.get("caption") or "").strip()
    base_tag = "#サコッシュ"
    gen_tags = [t for t in content.get("hashtags", []) if t and t != base_tag]
    all_tags = ([base_tag] + gen_tags)[:5]
    caption = f"{caption_body}\n\n{' '.join(all_tags)}"

    post = {
        "item_id": f"curation_{args.theme}_{run_id}",
        "caption": caption,
        "media_type": "carousel",
        "image_urls": image_urls,
        "image_url": "",
    }
    logger.info(f"画像枚数: {len(image_urls)} / カルーセル")
    logger.info(f"\n----- caption -----\n{caption}\n-------------------")

    if args.dry_run:
        logger.info("--dry-run: next_post.json への書き込みスキップ")
        return

    NEXT_POST_PATH.parent.mkdir(parents=True, exist_ok=True)
    NEXT_POST_PATH.write_text(
        json.dumps(post, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"書き込み完了: {NEXT_POST_PATH}")

    if not args.no_record:
        append_caption_history(post["item_id"], caption)
        logger.info("caption_history.json に追加")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"失敗: {e}", exc_info=True)
        sys.exit(1)
