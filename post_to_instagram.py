"""
Instagram 自動投稿スクリプト

data/instagram/next_post.json の内容を Instagram に投稿します。
GitHub Actions から日次で呼び出される想定。

使い方:
    python post_to_instagram.py                    # next_post.json を投稿
    python post_to_instagram.py --dry-run          # 投稿せず内容だけ表示

投稿後:
    - data/instagram/posted/YYYY-MM-DD.json に投稿履歴を保存
    - data/instagram/next_post.json はそのまま残る（次の投稿用に上書き想定）
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)

ROOT = Path(__file__).parent
NEXT_POST_PATH = ROOT / "data" / "instagram" / "next_post.json"
POSTED_DIR = ROOT / "data" / "instagram" / "posted"

from utils.instagram import publish_carousel, publish_image, whoami


def load_next_post() -> dict:
    if not NEXT_POST_PATH.exists():
        raise FileNotFoundError(f"投稿データが見つかりません: {NEXT_POST_PATH}")
    return json.loads(NEXT_POST_PATH.read_text(encoding="utf-8"))


def save_posted(post: dict, media_id: str) -> Path:
    POSTED_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    record = {
        "posted_at": datetime.now().isoformat(),
        "media_id": media_id,
        **post,
    }
    out = POSTED_DIR / f"{today}.json"
    out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="投稿せず内容を表示")
    args = parser.parse_args()

    post = load_next_post()
    media_type = post.get("media_type", "single")
    caption = post.get("caption", "").strip()

    logger.info(f"投稿タイプ: {media_type}")
    logger.info(f"キャプション:\n{caption}")

    if media_type == "single":
        image_url = post.get("image_url")
        if not image_url:
            raise ValueError("image_url が空です")
        logger.info(f"画像URL: {image_url}")
    elif media_type == "carousel":
        image_urls = post.get("image_urls", [])
        if not 2 <= len(image_urls) <= 10:
            raise ValueError("カルーセルは2〜10枚の画像URLが必要です")
        logger.info(f"画像枚数: {len(image_urls)}")
    else:
        raise ValueError(f"未対応の media_type: {media_type}")

    if args.dry_run:
        logger.info("--dry-run モード: 投稿せず終了")
        return

    info = whoami()
    logger.info(f"投稿先アカウント: @{info.get('username')} ({info.get('account_type')})")

    if media_type == "single":
        media_id = publish_image(post["image_url"], caption)
    else:
        media_id = publish_carousel(post["image_urls"], caption)

    saved = save_posted(post, media_id)
    logger.info(f"投稿完了 | media_id={media_id} | 履歴: {saved}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        logger.error(f"投稿失敗: {e}", exc_info=True)
        sys.exit(1)
