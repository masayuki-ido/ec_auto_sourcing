"""
EC運営全自動スケジューラ

全タスクを日次で自動実行:
  1. 商品追加 (add_five.py)
  2. 商品リッチ化 (enrich_products.py)
  3. 記事リトライ (article_retry.py)

実行方法:
    python scheduler.py                    # .env の時刻に従って毎日実行
    python scheduler.py --now              # 今すぐ全タスクを1回実行
    python scheduler.py --task enrich      # 特定タスクのみ実行
    python scheduler.py --task article     # 特定タスクのみ実行
"""
import argparse
import logging
import os
import sys
import time
from datetime import datetime

import schedule

from config import SCHEDULE_TIME
from main   import run, setup_logging

setup_logging()
logger = logging.getLogger(__name__)

# .env からスケジュール時刻を取得（デフォルト値あり）
ENRICH_TIME  = os.getenv("ENRICH_SCHEDULE_TIME", "10:00")
ARTICLE_TIME = os.getenv("ARTICLE_SCHEDULE_TIME", "11:00")


def add_products_job() -> None:
    """商品追加ジョブ"""
    logger.info(f"[商品追加] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        added = run()
        logger.info(f"[商品追加] 完了: {added} 件追加")
    except Exception as e:
        logger.critical(f"[商品追加] エラー: {e}", exc_info=True)


def enrich_job() -> None:
    """商品リッチ化ジョブ"""
    logger.info(f"[リッチ化] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        from enrich_products import main as enrich_main
        # sys.argv を一時的に書き換えてデフォルト引数で実行
        original_argv = sys.argv
        sys.argv = ["enrich_products.py", "--count", "5"]
        try:
            enrich_main()
        finally:
            sys.argv = original_argv
        logger.info("[リッチ化] 完了")
    except Exception as e:
        logger.critical(f"[リッチ化] エラー: {e}", exc_info=True)


def article_retry_job() -> None:
    """記事リトライジョブ"""
    logger.info(f"[記事リトライ] 開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        from article_retry import main as article_main
        original_argv = sys.argv
        sys.argv = ["article_retry.py", "--count", "5"]
        try:
            article_main()
        finally:
            sys.argv = original_argv
        logger.info("[記事リトライ] 完了")
    except Exception as e:
        logger.critical(f"[記事リトライ] エラー: {e}", exc_info=True)


def run_all_jobs() -> None:
    """全タスクを順番に実行"""
    logger.info("=== 全タスク実行開始 ===")
    add_products_job()
    enrich_job()
    article_retry_job()
    logger.info("=== 全タスク実行完了 ===")


TASK_MAP = {
    "add": add_products_job,
    "enrich": enrich_job,
    "article": article_retry_job,
    "all": run_all_jobs,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="EC運営全自動スケジューラ")
    parser.add_argument("--now", action="store_true", help="起動直後に1回即時実行する")
    parser.add_argument("--task", choices=["add", "enrich", "article", "all"],
                        default="all", help="実行するタスク（デフォルト: all）")
    args = parser.parse_args()

    logger.info(f"スケジューラ起動 | 商品追加: {SCHEDULE_TIME} | リッチ化: {ENRICH_TIME} | 記事リトライ: {ARTICLE_TIME}")

    # 毎日指定時刻にそれぞれのジョブを実行
    schedule.every().day.at(SCHEDULE_TIME).do(add_products_job)
    schedule.every().day.at(ENRICH_TIME).do(enrich_job)
    schedule.every().day.at(ARTICLE_TIME).do(article_retry_job)

    if args.now:
        logger.info(f"--now オプション: 「{args.task}」を今すぐ実行します")
        TASK_MAP[args.task]()

    logger.info("待機中... (停止: Ctrl+C)")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)
    except KeyboardInterrupt:
        logger.info("スケジューラを停止しました")
        sys.exit(0)


if __name__ == "__main__":
    main()
