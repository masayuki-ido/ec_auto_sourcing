"""管理画面からエクスポートした CSV を repo に同期する。

仕様:
  - 供給元URL (supplier_url) など機密性のある列は削除
  - 投稿生成に必要な列だけを残す
  - 出力: data/items_public.csv (リポジトリにコミット可能な公開版)

使い方:
  python scripts/sync_items_csv.py
  ITEM_CSV=/path/to/source.csv python scripts/sync_items_csv.py
"""
from __future__ import annotations

import csv
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SRC = Path.home() / "Downloads" / "item_sacoche-sacolla.csv"
SRC = Path(os.getenv("ITEM_CSV", str(DEFAULT_SRC)))
DST = ROOT / "data" / "items_public.csv"

# 投稿生成に必要 + 公開しても問題ない列のみ残す
KEEP_COLUMNS = [
    "item_id",
    "name",
    "description",
    "size_description",
    "additional_description",
    "price",
    "discounted_price",
    "stock",
    "category_id",
    "subcategory_id",
    "display",
    "hide",
    "is_popular",
    "color",
    "size",
    *(f"images{i}" for i in range(1, 11)),
]


def main() -> None:
    if not SRC.exists():
        print(f"[ERR] 元CSVが見つかりません: {SRC}", file=sys.stderr)
        sys.exit(1)

    with SRC.open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    print(f"入力: {len(rows)}行 ({SRC})")

    DST.parent.mkdir(parents=True, exist_ok=True)
    with DST.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=KEEP_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    print(f"出力: {len(rows)}行 → {DST}")
    print("  (supplier_url, 日付などは除外済み)")
    print("commit/push: git add data/items_public.csv && git commit -m 'chore: items CSV update' && git push")


if __name__ == "__main__":
    main()
