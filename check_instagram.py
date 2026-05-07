"""
Instagram トークン動作確認スクリプト

使い方:
    python check_instagram.py            # トークンが有効か確認

トークンは graph.instagram.com 系の長期ユーザートークン(60日)を使用。
自動refresh機能は廃止し、Meta Business Suite 経由での手動ローテーション運用に統一した
（データセンターIPからの自動化アクティビティ違反リスク回避のため）。
"""
import argparse
import logging
import os
import sys

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv()

from utils.instagram import whoami


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.parse_args()

    print("トークン検証中...")
    info = whoami()
    print(f"\n✅ 接続成功！")
    print(f"  Username    : {info.get('username')}")
    print(f"  User ID     : {info.get('id')}")
    print(f"  Account Type: {info.get('account_type')}")

    expected_id = os.getenv("IG_USER_ID")
    if expected_id and info.get("id") != expected_id:
        print(f"\n⚠️ .env の IG_USER_ID ({expected_id}) と取得結果 ({info.get('id')}) が異なります")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ エラー: {e}", file=sys.stderr)
        sys.exit(1)
