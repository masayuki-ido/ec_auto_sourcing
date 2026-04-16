"""
検索モードの切り替え・商品カード構造・追加ボタンの詳細調査
"""
import logging, json, re
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
    logger.info("ログイン成功")


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        login(page)

        # ── 検索ページへ ──
        page.goto(f"{BASE}/item/search", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # ── 1. 検索モードのSELECTを確認 ──
        logger.info("=== 検索モードSELECT ===")
        sel_el = page.query_selector("select")
        if sel_el:
            options = sel_el.query_selector_all("option")
            for opt in options:
                logger.info(f"  value={opt.get_attribute('value')!r}  text={opt.inner_text()!r}")

        # ── 2. 「画像で検索」モードに切り替え ──
        logger.info("\n=== 画像検索モードに切り替え ===")
        page.select_option("select", value="image")
        page.wait_for_timeout(1000)
        page.screenshot(path="logs/p5_image_mode.png")

        # 画像URLを入力するフィールドを探す
        for inp in page.query_selector_all("input, textarea"):
            ph = inp.get_attribute("placeholder") or ""
            nm = inp.get_attribute("name") or ""
            logger.info(f"  input: name={nm!r} placeholder={ph!r}")

        # ── 3. サンプル画像URLで検索 ──
        # GoogleでサコッシュTOP画像のURLを使用
        sample_image_url = "https://g-search1.alicdn.com/img/bao/uploaded/i4/i1/1049653664/O1CN01iPes6U1cw9q46zYvI_!!0-item_pic.jpg"
        logger.info(f"\n=== 画像URL検索: {sample_image_url[:60]}... ===")

        # 画像URL入力欄を探して入力
        filled = False
        for sel in ['input[placeholder*="URL"]', 'input[placeholder*="url"]',
                    'input[placeholder*="画像"]', 'input[placeholder*="http"]',
                    'textarea[placeholder*="URL"]', 'input[type="url"]',
                    'input[type="text"]']:
            el = page.query_selector(sel)
            if el and el.is_visible():
                el.fill(sample_image_url)
                logger.info(f"  入力成功: {sel}")
                filled = True
                break

        if filled:
            # 検索ボタンをクリック
            for btn_sel in ['button:has-text("検索")', 'button[type="submit"]',
                            'button:has-text("Search")']:
                btn = page.query_selector(btn_sel)
                if btn and btn.is_visible():
                    btn.click()
                    logger.info(f"  検索ボタンクリック: {btn_sel}")
                    break

            page.wait_for_timeout(5000)  # 画像検索は時間がかかる
            page.screenshot(path="logs/p5_image_search_result.png", full_page=True)

        # ── 4. キーワード検索で商品カード構造を調べる ──
        logger.info("\n=== キーワード検索で商品カード構造を調査 ===")
        page.goto(f"{BASE}/item/search", wait_until="networkidle")
        page.wait_for_timeout(1000)
        page.select_option("select", value="word2")
        page.wait_for_timeout(500)
        page.fill('input[type="text"]', "サコッシュ")
        page.click('button:has-text("検索")')

        # 結果が出るまで待つ
        try:
            page.wait_for_selector('div[class*="grid"] > div img', timeout=20_000)
        except:
            pass
        page.wait_for_timeout(3000)
        page.screenshot(path="logs/p5_keyword_result.png", full_page=True)
        (LOGS / "p5_keyword_result.html").write_text(page.content(), encoding="utf-8")

        # 商品カードを調査
        cards = page.query_selector_all('div[class*="grid"] > div')
        logger.info(f"商品カード数: {len(cards)}")

        product_cards = []
        for i, card in enumerate(cards[:5]):
            # カード内のボタン・リンク・テキストを調査
            buttons = card.query_selector_all("button")
            links   = card.query_selector_all("a[href]")
            imgs    = card.query_selector_all("img")
            price_els = card.query_selector_all('[class*="price"], [class*="Price"]')

            card_info = {
                "index": i,
                "text":     card.inner_text()[:200].replace("\n", " | "),
                "buttons":  [b.inner_text().strip()[:30] for b in buttons],
                "links":    [(a.get_attribute("href"), a.inner_text()[:30]) for a in links],
                "img_srcs": [img.get_attribute("src")[:80] for img in imgs if img.get_attribute("src")],
                "prices":   [p.inner_text().strip() for p in price_els],
            }
            product_cards.append(card_info)
            logger.info(f"\nカード[{i}]:\n  text: {card_info['text'][:100]}\n  buttons: {card_info['buttons']}\n  links: {card_info['links'][:2]}")

        (LOGS / "p5_product_cards.json").write_text(
            json.dumps(product_cards, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ── 5. 最初の商品カードの「追加」ボタンを探す ──
        logger.info("\n=== 追加ボタンを探す ===")
        add_btns = page.query_selector_all('button:has-text("追加"), button:has-text("インポート"), button:has-text("登録"), button:has-text("取り込")')
        logger.info(f"「追加」系ボタン: {len(add_btns)}個")
        for btn in add_btns[:5]:
            logger.info(f"  {btn.inner_text()!r} class={btn.get_attribute('class')!r}")

        logger.info("\n=== 完了 ===")
        try:
            input("Enterキーで終了...")
        except (EOFError, KeyboardInterrupt):
            pass
        browser.close()


if __name__ == "__main__":
    main()
