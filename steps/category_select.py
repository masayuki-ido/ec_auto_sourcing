"""
商品名・キーワードからカテゴリを自動判定し、管理画面のプルダウンで選択する

NOTE: プルダウンのセレクタは管理画面に合わせて調整してください。
"""
import logging
from playwright.sync_api import Page

from config import CATEGORY_MAP, DEFAULT_CATEGORY

logger = logging.getLogger(__name__)

# ─── 要調整: カテゴリプルダウンのセレクタ ──────────────
SEL_CATEGORY_SELECT = 'select[name="category"], select[name*="category"], #category'
# ─────────────────────────────────────────────────────


def resolve_category(product_name: str) -> str:
    """
    商品名から CATEGORY_MAP を使ってカテゴリ名を決定する。

    Args:
        product_name: 商品名文字列

    Returns:
        カテゴリ名（マッチしなければ DEFAULT_CATEGORY）
    """
    for keyword, category in CATEGORY_MAP.items():
        if keyword in product_name:
            logger.debug(f"カテゴリ判定: 「{keyword}」→「{category}」")
            return category
    logger.debug(f"カテゴリ未マッチ: 「{product_name}」→ デフォルト「{DEFAULT_CATEGORY}」")
    return DEFAULT_CATEGORY


def select_category(page: Page, product: dict) -> dict:
    """
    管理画面の商品編集画面でカテゴリプルダウンを選択する。

    Args:
        page: ログイン済み Playwright Page（商品編集ページが開いている状態）
        product: 商品辞書

    Returns:
        product に "category" キーを追加して返す
    """
    category = resolve_category(product["name"])
    product["category"] = category

    try:
        page.wait_for_selector(SEL_CATEGORY_SELECT, timeout=5_000)
        page.select_option(SEL_CATEGORY_SELECT, label=category)
        logger.info(f"カテゴリ選択: 「{category}」（商品: {product['name']}）")
    except Exception as e:
        logger.warning(f"カテゴリ選択失敗 [{category}]: {e}")

    return product


# ─── 単体テスト ─────────────────────────────────────────
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    tests = [
        "レディース サコッシュ ショルダー",
        "ミニポーチ コインケース付き",
        "本革 長財布 メンズ",
        "デイリートートバッグ",
        "特殊アイテム",
    ]
    for name in tests:
        print(f"{name!r} → {resolve_category(name)!r}")
