"""
Instagram トークン動作確認スクリプト

使い方:
    python check_instagram.py            # トークンが有効か確認
    python check_instagram.py --refresh  # 長期トークンをリフレッシュ（60日延長）
"""
import argparse
import logging
import os
import sys

from dotenv import load_dotenv

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
load_dotenv()

from utils.instagram import refresh_long_lived_token, whoami


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="長期トークンを60日延長する")
    args = parser.parse_args()

    if args.refresh:
        print("長期トークンをリフレッシュ中...")
        result = refresh_long_lived_token()
        new_token = result.get("access_token")
        expires_in = result.get("expires_in")
        days = expires_in // 86400 if expires_in else "?"
        print(f"\n✅ リフレッシュ成功！有効期限: 約{days}日")
        print(f"\n新しいトークン:\n{new_token}")
        print("\n→ .env の IG_ACCESS_TOKEN を上記の値に更新してください")
        return

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
