"""
価格・画像有無による商品フィルタリング
"""
import logging
from config import MAX_PRICE_JPY

logger = logging.getLogger(__name__)


def filter_products(products: list[dict]) -> list[dict]:
    """
    価格上限・画像有無でフィルタリングして通過した商品リストを返す。

    Args:
        products: search.py が返す商品辞書のリスト

    Returns:
        条件を満たす商品辞書のリスト
    """
    passed = []
    for p in products:
        reasons = _check(p)
        if reasons:
            logger.debug(f"除外 [{p['name']}]: {', '.join(reasons)}")
        else:
            passed.append(p)

    logger.info(f"価格・画像フィルタ: {len(products)} 件 → {len(passed)} 件通過")
    return passed


def _check(product: dict) -> list[str]:
    """除外理由のリストを返す。空なら通過。"""
    reasons = []

    # 価格チェック
    if product["price"] > MAX_PRICE_JPY:
        reasons.append(f"価格 {product['price']}円 > 上限 {MAX_PRICE_JPY}円")

    # 画像チェック
    if not product.get("image_url"):
        reasons.append("商品画像なし")

    return reasons


# ─── 単体テスト ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    sample = [
        {"id": "1", "name": "テスト商品A", "price": 12000, "image_url": "http://example.com/a.jpg"},
        {"id": "2", "name": "テスト商品B", "price": 20000, "image_url": "http://example.com/b.jpg"},
        {"id": "3", "name": "テスト商品C", "price":  8000, "image_url": None},
        {"id": "4", "name": "テスト商品D", "price":  5000, "image_url": "http://example.com/d.jpg"},
    ]
    result = filter_products(sample)
    print("通過:", [p["name"] for p in result])
