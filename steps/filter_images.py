"""
画像フィルタリング: 中国語テキスト検出・サイズチェック
"""
from __future__ import annotations
import logging
import requests
from config import MIN_IMAGE_SHORT_SIDE
from utils.ocr import has_chinese_text, check_image_size

logger = logging.getLogger(__name__)

DOWNLOAD_TIMEOUT = 10  # 秒


def filter_by_image(products: list[dict]) -> list[dict]:
    """
    各商品の画像をダウンロードし、以下の条件で除外する:
      - 中国語テキストが含まれる
      - 短辺が MIN_IMAGE_SHORT_SIDE px 未満

    Args:
        products: filter_products.py 通過済み商品リスト

    Returns:
        画像フィルタ通過済み商品リスト（image_bytes キーを追加）
    """
    passed = []
    for p in products:
        url = p.get("image_url")
        if not url:
            logger.debug(f"スキップ（URL無し）: {p['name']}")
            continue

        image_bytes = _download(url)
        if image_bytes is None:
            logger.warning(f"画像ダウンロード失敗（スキップ）: {p['name']} [{url}]")
            continue

        # サイズチェック
        if not check_image_size(image_bytes, MIN_IMAGE_SHORT_SIDE):
            logger.info(f"除外（サイズ不足）: {p['name']}")
            continue

        # 中国語テキストチェック
        if has_chinese_text(image_bytes):
            logger.info(f"除外（中国語テキスト検出）: {p['name']}")
            continue

        p["image_bytes"] = image_bytes
        passed.append(p)

    logger.info(f"画像フィルタ: {len(products)} 件 → {len(passed)} 件通過")
    return passed


def _download(url: str) -> bytes | None:
    """画像URLからバイト列を取得する。失敗時は None を返す。"""
    try:
        resp = requests.get(url, timeout=DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        return resp.content
    except requests.RequestException as e:
        logger.debug(f"ダウンロード失敗 [{url}]: {e}")
        return None


# ─── 単体テスト ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    # ローカル画像ファイルでテストする場合
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            data = f.read()
        print("中国語検出:", has_chinese_text(data))
        print("サイズOK:", check_image_size(data, MIN_IMAGE_SHORT_SIDE))
    else:
        print("使い方: python -m steps.filter_images <画像ファイルパス>")
