"""検索結果カードのクローズアップ＋詳細ページ遷移を試す"""
from __future__ import annotations
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
        page = browser.new_page(viewport={"width": 1400, "height": 900})
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

        # 結果ビューポートだけ撮る
        page.screenshot(path=str(LOGS / "results_viewport.png"), full_page=False)

        # 最初のカードをクリックして何が起きるか見る
        cards = page.query_selector_all("[class*='grid'] > div")
        logger.info(f"grid候補数: {len(cards)}")

        # 商品画像があるカードを絞り込む
        product_cards = []
        for c in cards:
            img = c.query_selector("img")
            if img:
                src = img.get_attribute("src") or ""
                if "alicdn" in src or "taobao" in src or "1688" in src or "jpg" in src.lower() or "png" in src.lower():
                    product_cards.append(c)
        logger.info(f"商品っぽいカード: {len(product_cards)}")

        if product_cards:
            c = product_cards[0]
            # カード内のボタン・リンク列挙
            print("\n=== カード内要素 ===")
            print("HTML snippet:")
            html = c.inner_html()[:800]
            print(html)
            print("\nボタン:")
            for b in c.query_selector_all("button"):
                print(f"  [{(b.inner_text() or '').strip()[:40]}]")
            print("\nリンク:")
            for a in c.query_selector_all("a"):
                print(f"  text=[{(a.inner_text() or '').strip()[:40]}] href={a.get_attribute('href')}")

            # クリックしてみる
            logger.info("カードをクリック")
            c.click()
            page.wait_for_timeout(5000)
            logger.info(f"遷移後URL: {page.url}")
            page.screenshot(path=str(LOGS / "card_clicked.png"), full_page=True)

            # 遷移先のボタン列挙
            print("\n=== 遷移先のボタン ===")
            for b in page.query_selector_all("button"):
                t = (b.inner_text() or "").strip()[:40]
                if t:
                    print(f"  [{t}]")

        browser.close()


if __name__ == "__main__":
    main()
