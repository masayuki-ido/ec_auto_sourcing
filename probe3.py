"""
商品検索ページ・商品詳細ページの構造調査
"""
import logging, json
from pathlib import Path
from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config import ADMIN_USER, ADMIN_PASS
LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"


def login(page):
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1500)
    page.fill('input[name="email"]', ADMIN_USER)
    page.fill('input[name="password"]', ADMIN_PASS)
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: "login" not in url, timeout=15_000)
    logger.info(f"ログイン成功: {page.url}")


def probe_page(page, url: str, label: str):
    """ページのスクショ・HTML・要素情報を保存"""
    page.goto(url, wait_until="networkidle")
    page.wait_for_timeout(1500)
    page.screenshot(path=f"logs/p3_{label}.png", full_page=True)
    (LOGS / f"p3_{label}.html").write_text(page.content(), encoding="utf-8")

    # inputs / buttons / selects を収集
    elements = {"inputs": [], "buttons": [], "selects": [], "tables": []}

    for el in page.query_selector_all("input, textarea"):
        elements["inputs"].append({
            "tag":         el.evaluate("e => e.tagName"),
            "type":        el.get_attribute("type") or "text",
            "name":        el.get_attribute("name"),
            "id":          el.get_attribute("id"),
            "placeholder": el.get_attribute("placeholder"),
            "class":       (el.get_attribute("class") or "")[:60],
        })

    for el in page.query_selector_all("button"):
        text = el.inner_text().strip()[:60]
        elements["buttons"].append({
            "text":  text,
            "type":  el.get_attribute("type"),
            "class": (el.get_attribute("class") or "")[:60],
            "id":    el.get_attribute("id"),
        })

    for el in page.query_selector_all("select"):
        options = [o.inner_text().strip() for o in el.query_selector_all("option")]
        elements["selects"].append({
            "name":    el.get_attribute("name"),
            "id":      el.get_attribute("id"),
            "options": options,
        })

    # テーブル構造
    for i, tbl in enumerate(page.query_selector_all("table")):
        headers = [th.inner_text().strip() for th in tbl.query_selector_all("thead th, thead td")]
        first_row = [td.inner_text().strip()[:30] for td in tbl.query_selector_all("tbody tr:first-child td")]
        elements["tables"].append({"index": i, "headers": headers, "first_row": first_row})

    logger.info(f"[{label}] inputs:{len(elements['inputs'])} buttons:{len(elements['buttons'])} selects:{len(elements['selects'])} tables:{len(elements['tables'])}")
    logger.info(f"  buttons: {[b['text'] for b in elements['buttons'] if b['text']]}")

    (LOGS / f"p3_{label}_elements.json").write_text(
        json.dumps(elements, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return elements


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        login(page)

        # ── 1. 商品検索ページ ──
        logger.info("\n=== 商品検索ページ /item/search ===")
        probe_page(page, f"{BASE}/item/search", "search")

        # ── 2. 検索を実行してみる ──
        logger.info("\n=== 検索「サコッシュ」実行 ===")
        page.goto(f"{BASE}/item/search", wait_until="networkidle")
        page.wait_for_timeout(1000)

        # 検索inputを探す
        search_inputs = page.query_selector_all("input")
        for inp in search_inputs:
            ph = inp.get_attribute("placeholder") or ""
            nm = inp.get_attribute("name") or ""
            logger.info(f"  input: name={nm!r} placeholder={ph!r}")

        # 検索フォームに入力
        filled = False
        for sel in ['input[name="keyword"]', 'input[placeholder*="検索"]',
                    'input[placeholder*="search"]', 'input[type="search"]', 'input[type="text"]']:
            el = page.query_selector(sel)
            if el:
                el.fill("サコッシュ")
                logger.info(f"  入力成功: {sel}")
                filled = True
                break

        if not filled:
            logger.warning("  検索inputが見つかりませんでした")

        # 検索ボタン or Enterキー
        for btn_sel in ['button[type="submit"]', 'button:has-text("検索")', 'button:has-text("Search")']:
            btn = page.query_selector(btn_sel)
            if btn:
                btn.click()
                logger.info(f"  ボタンクリック: {btn_sel}")
                break
        else:
            page.keyboard.press("Enter")
            logger.info("  Enterキーで検索")

        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path="logs/p3_search_result.png", full_page=True)
        (LOGS / "p3_search_result.html").write_text(page.content(), encoding="utf-8")
        logger.info(f"  検索後URL: {page.url}")

        # 結果行を数える
        for sel in ["table tbody tr", ".item-row", "[class*='product-']", "li[class*='item']"]:
            rows = page.query_selector_all(sel)
            if rows:
                logger.info(f"  結果行 ({sel}): {len(rows)}件")
                # 最初の行のテキスト
                logger.info(f"  最初の行: {rows[0].inner_text()[:100].replace(chr(10), ' ')}")
                break

        # ── 3. 既存商品の詳細ページ（/item/31）──
        logger.info("\n=== 既存商品詳細 /item/31 ===")
        probe_page(page, f"{BASE}/item/31", "item_detail")

        logger.info("\n=== 完了 ===")
        logger.info("logs/p3_*.png を確認してください")
        try:
            input("Enterキーで終了...")
        except (EOFError, KeyboardInterrupt):
            pass
        browser.close()


if __name__ == "__main__":
    main()
