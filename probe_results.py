"""検索実行→検索結果ページの構造ダンプ"""
from __future__ import annotations
import json
import logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import ADMIN_URL, ADMIN_USER, ADMIN_PASS, HEADLESS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOGS = Path("logs")
LOGS.mkdir(exist_ok=True)
base = ADMIN_URL.rstrip("/").rsplit("/", 1)[0]


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(ADMIN_URL, wait_until="networkidle")
        page.fill('input[name="email"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=20_000)
        page.wait_for_timeout(2000)

        page.goto(base + "/item/search", wait_until="networkidle")
        page.wait_for_timeout(2000)

        page.fill('input[placeholder*="パーカー"]', "サコッシュ")
        page.click('button:has-text("検索開始")')
        page.wait_for_timeout(8000)
        page.wait_for_load_state("networkidle", timeout=30_000)
        page.wait_for_timeout(3000)

        page.screenshot(path=str(LOGS / "search_results_dump.png"), full_page=True)
        (LOGS / "search_results_dump.html").write_text(page.content(), encoding="utf-8")
        logger.info(f"現在URL: {page.url}")

        # 商品カードらしき要素を探す
        candidates = [
            ("table tr", page.query_selector_all("table tr")),
            ("[class*='grid'] > div", page.query_selector_all("[class*='grid'] > div")),
            ("[class*='card']", page.query_selector_all("[class*='card']")),
            ("[class*='product']", page.query_selector_all("[class*='product']")),
            ("[class*='item']", page.query_selector_all("[class*='item']")),
            ("li", page.query_selector_all("li")),
        ]
        for name, els in candidates:
            print(f"  {name}: {len(els)} 件")

        # 「追加」ボタンを全列挙
        print("\n=== 追加ボタン候補 ===")
        for btn in page.query_selector_all("button"):
            text = (btn.inner_text() or "").strip()[:30]
            if "追加" in text or "登録" in text or "+" in text:
                print(f"  [{text}] class={(btn.get_attribute('class') or '')[:60]}")

        browser.close()


if __name__ == "__main__":
    main()
