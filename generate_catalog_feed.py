"""
Meta Commerce Manager 用の商品カタログCSVを生成する。

入力: 管理画面エクスポートの item_sacoche-sacolla.csv
出力: data/instagram/catalog_feed.csv (Meta必須スキーマ準拠)

使い方:
    python generate_catalog_feed.py
    python generate_catalog_feed.py --out path/to/feed.csv
    ITEM_CSV=/path/to.csv python generate_catalog_feed.py

Meta Commerce Manager アップロード手順:
  1. https://business.facebook.com/commerce/ で Catalog を開く
  2. Catalog → Items → Add Items → Upload File
  3. 出力された catalog_feed.csv をアップロード
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import re
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
DEFAULT_CSV = Path.home() / "Downloads" / "item_sacoche-sacolla.csv"
SOURCE_CSV = Path(os.getenv("ITEM_CSV", str(DEFAULT_CSV)))
DEFAULT_OUT = ROOT / "data" / "instagram" / "catalog_feed.csv"

STORE_BASE = "https://www.sacoche-sacolla.jp/item"
BRAND = "sacoche sacolla"
CURRENCY = "JPY"
CONDITION = "new"

# Meta Catalog 必須/推奨カラム
META_COLUMNS = [
    "id",
    "title",
    "description",
    "availability",
    "condition",
    "price",
    "link",
    "image_link",
    "brand",
    "additional_image_link",
    "color",
    "google_product_category",
]

# 全カテゴリ「Apparel & Accessories > Handbags, Wallets & Cases > Handbags」
GOOGLE_CATEGORY = "169"


def collect_images(row: dict) -> list[str]:
    urls = []
    for i in range(1, 11):
        url = (row.get(f"images{i}") or "").strip()
        if url.startswith("http"):
            urls.append(url)
    return urls


def clean_text(s: str, max_len: int) -> str:
    """改行・連続空白を整理し、max_lenでカット"""
    if not s:
        return ""
    s = re.sub(r"\s+", " ", s).strip()
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def to_availability(row: dict) -> str:
    """hide=true なら discontinued、stock=true なら in stock、それ以外 out of stock"""
    if (row.get("hide") or "").lower() == "true":
        return "discontinued"
    return "in stock" if (row.get("stock") or "").lower() == "true" else "out of stock"


def transform(row: dict) -> dict | None:
    images = collect_images(row)
    if not images:
        logger.warning(f"  [{row['item_id']}] 画像なし: スキップ")
        return None

    try:
        price_int = int(row.get("price") or "0")
    except ValueError:
        price_int = 0
    if price_int <= 0:
        logger.warning(f"  [{row['item_id']}] 価格不正: スキップ")
        return None

    name = clean_text(row.get("name") or "", 150)
    desc = clean_text(row.get("description") or "", 4900)
    if not desc:
        desc = name

    color = (row.get("color") or "").replace(",", " / ").strip()

    return {
        "id": row["item_id"],
        "title": name,
        "description": desc,
        "availability": to_availability(row),
        "condition": CONDITION,
        "price": f"{price_int} {CURRENCY}",
        "link": f"{STORE_BASE}/{row['item_id']}",
        "image_link": images[0],
        "brand": BRAND,
        "additional_image_link": ",".join(images[1:10]),
        "color": color,
        "google_product_category": GOOGLE_CATEGORY,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT, help="出力CSVパス")
    parser.add_argument("--limit", type=int, help="件数制限 (デバッグ用)")
    args = parser.parse_args()

    if not SOURCE_CSV.exists():
        logger.error(f"商品CSVが見つかりません: {SOURCE_CSV}")
        sys.exit(1)

    with SOURCE_CSV.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    logger.info(f"入力: {len(rows)}件 ({SOURCE_CSV})")

    if args.limit:
        rows = rows[: args.limit]

    out_rows = []
    for row in rows:
        item = transform(row)
        if item:
            out_rows.append(item)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=META_COLUMNS, quoting=csv.QUOTE_ALL)
        writer.writeheader()
        writer.writerows(out_rows)

    logger.info(f"出力: {len(out_rows)}件 → {args.out}")
    logger.info("Meta Commerce Manager にアップロードしてください:")
    logger.info("  https://business.facebook.com/commerce/")


if __name__ == "__main__":
    main()
