"""
管理画面での商品検索処理

NOTE: セレクタは管理画面に合わせて調整してください。
"""
import logging
from playwright.sync_api import Page, TimeoutError as PWTimeout
from config import ADMIN_URL

logger = logging.getLogger(__name__)

# ─── 要調整: 検索フォームのセレクタ ────────────────────
# 管理画面内の「商品検索」または「Alibaba商品DB」ページURL（ログイン後の相対パス）
SEARCH_PAGE_PATH = "/products/alibaba-search"   # 例: /products/alibaba-search

SEL_SEARCH_INPUT  = 'input[placeholder*="検索"], input[name="keyword"], input[type="search"]'
SEL_SEARCH_BUTTON = 'button[type="submit"], button:has-text("検索")'
SEL_RESULT_ROW    = 'table tbody tr, .product-item, [class*="product-row"]'
# ─────────────────────────────────────────────────────


def navigate_to_search(page: Page) -> None:
    """検索ページへ遷移する（ログイン済み前提）。"""
    base = ADMIN_URL.rstrip("/").rsplit("/", 1)[0]  # ドメインルートを抽出
    target = base + SEARCH_PAGE_PATH
    logger.info(f"検索ページへ移動: {target}")
    page.goto(target, wait_until="networkidle")


def search_products(page: Page, keyword: str) -> list[dict]:
    """
    指定キーワードで商品を検索し、結果行の情報リストを返す。

    Returns:
        List of dict: [{"element": <locator>, "name": str, "price": int, "id": str}, ...]
    """
    logger.info(f"キーワード「{keyword}」で検索開始")

    try:
        page.wait_for_selector(SEL_SEARCH_INPUT, timeout=10_000)
        page.fill(SEL_SEARCH_INPUT, keyword)
        page.click(SEL_SEARCH_BUTTON)
        page.wait_for_load_state("networkidle")
    except PWTimeout:
        logger.error("検索フォームが見つかりません。SEL_SEARCH_INPUT を確認してください。")
        return []

    # 結果行を収集
    rows = page.query_selector_all(SEL_RESULT_ROW)
    logger.info(f"検索結果: {len(rows)} 件")

    products = []
    for row in rows:
        info = _parse_row(row)
        if info:
            products.append(info)

    return products


def _parse_row(row) -> dict | None:
    """
    結果行から商品情報を抽出する。
    管理画面のHTML構造に合わせて実装を調整してください。
    """
    try:
        # ── 要調整: 各セルのセレクタ ──
        name_el   = row.query_selector('td:nth-child(2), .product-name')
        price_el  = row.query_selector('td:nth-child(3), .product-price')
        id_el     = row.query_selector('td:nth-child(1), [data-id]')
        image_el  = row.query_selector('img')

        name  = name_el.inner_text().strip()  if name_el  else ""
        price_text = price_el.inner_text().strip() if price_el else "0"
        prod_id    = (id_el.get_attribute("data-id") or id_el.inner_text().strip()) if id_el else ""
        image_url  = image_el.get_attribute("src") if image_el else None

        # 価格を数値に変換（「¥1,500」→ 1500）
        price = int("".join(filter(str.isdigit, price_text)) or 0)

        if not name:
            return None

        return {
            "id":        prod_id,
            "name":      name,
            "price":     price,
            "image_url": image_url,
            "element":   row,       # Playwright Locator（後続ステップで使用）
        }
    except Exception as e:
        logger.debug(f"行パース失敗（スキップ）: {e}")
        return None


# ─── 単体テスト ─────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from playwright.sync_api import sync_playwright
    from config import HEADLESS, SEARCH_KEYWORDS
    from steps.login import login

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        try:
            login(page)
            navigate_to_search(page)
            results = search_products(page, SEARCH_KEYWORDS[0])
            for p in results[:5]:
                print(p["id"], p["name"], p["price"])
        except Exception as e:
            print(f"[ERROR] {e}", file=sys.stderr)
        finally:
            browser.close()
