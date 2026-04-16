"""
日次スケジュール実行スクリプト

実行方法:
    python scheduler.py          # .env の SCHEDULE_TIME に従って毎日実行
    python scheduler.py --now    # 今すぐ1回実行してから待機
"""
import argparse
import logging
import sys
import time
from datetime import datetime

import schedule

from config import SCHEDULE_TIME
from main   import run, setup_logging

setup_logging()
logger = logging.getLogger(__name__)


def job() -> None:
    """スケジュール実行のジョブ関数。"""
    logger.info(f"スケジュール実行開始: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    try:
        added = run()
        logger.info(f"スケジュール実行完了: {added} 件追加")
    except Exception as e:
        logger.critical(f"スケジュール実行中に未処理エラー: {e}", exc_info=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="EC商品自動追加 スケジューラ")
    parser.add_argument("--now", action="store_true", help="起動直後に1回即時実行する")
    args = parser.parse_args()

    logger.info(f"スケジューラ起動 | 実行時刻: 毎日 {SCHEDULE_TIME}")

    # 毎日指定時刻に実行
    schedule.every().day.at(SCHEDULE_TIME).do(job)

    if args.now:
        logger.info("--now オプション: 今すぐ1回実行します")
        job()

    logger.info("待機中... (停止: Ctrl+C)")
    try:
        while True:
            schedule.run_pending()
            time.sleep(30)  # 30秒ごとにスケジュールチェック
    except KeyboardInterrupt:
        logger.info("スケジューラを停止しました")
        sys.exit(0)


if __name__ == "__main__":
    main()
