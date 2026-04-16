"""
ログイン動作の詳細調査スクリプト（Next.js対応版）
"""
import logging, json, time
from pathlib import Path
from playwright.sync_api import sync_playwright, Request, Response

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config import ADMIN_URL, ADMIN_USER, ADMIN_PASS
LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)

LOGIN_URL = ADMIN_URL  # https://sacoche-sacolla.flumo-admin-server.com/login


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # ── ネットワークログを記録 ──
        network_log = []
        def on_response(resp: Response):
            if "login" in resp.url or "auth" in resp.url or "session" in resp.url:
                network_log.append({"url": resp.url, "status": resp.status, "method": resp.request.method})
        page.on("response", on_response)

        logger.info(f"ページへアクセス: {LOGIN_URL}")
        page.goto(LOGIN_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        page.screenshot(path="logs/p2_01_before_login.png")

        logger.info("フォームに入力...")
        page.fill('input[name="email"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.screenshot(path="logs/p2_02_filled.png")

        logger.info("ログインボタンをクリック...")
        page.click('button[type="submit"]')

        # URLが変わるまで最大15秒待つ
        try:
            page.wait_for_url(
                lambda url: "login" not in url,
                timeout=15_000
            )
            logger.info(f"✓ ログイン成功！ URL: {page.url}")
        except Exception:
            # URLが変わらなかった場合 → エラーメッセージを探す
            page.wait_for_timeout(3000)
            logger.warning(f"URL変化なし。現在のURL: {page.url}")

            # エラーメッセージを探す
            for sel in ['.error', '[class*="error"]', '[class*="alert"]', 'p[class*="red"]',
                        '[role="alert"]', '.text-red-500', '.text-destructive']:
                el = page.query_selector(sel)
                if el:
                    logger.error(f"エラーメッセージ検出 ({sel}): {el.inner_text().strip()}")

        page.screenshot(path="logs/p2_03_after_submit.png", full_page=True)
        logger.info(f"現在のURL: {page.url}")

        # ── ネットワークログ出力 ──
        logger.info(f"ネットワークログ:\n{json.dumps(network_log, ensure_ascii=False, indent=2)}")
        (LOGS / "p2_network.json").write_text(json.dumps(network_log, ensure_ascii=False, indent=2))

        # ── ログイン成功していれば画面構造を調査 ──
        if "login" not in page.url:
            logger.info("=== ログイン後の画面を調査 ===")
            page.screenshot(path="logs/p2_04_dashboard.png", full_page=True)
            (LOGS / "p2_dashboard.html").write_text(page.content(), encoding="utf-8")

            # ナビリンクを全取得
            links = []
            for a in page.query_selector_all("a[href]"):
                href = a.get_attribute("href") or ""
                text = a.inner_text().strip()[:50]
                if text and href:
                    links.append({"text": text, "href": href})

            logger.info(f"リンク一覧 ({len(links)}件):\n{json.dumps(links, ensure_ascii=False, indent=2)}")
            (LOGS / "p2_links.json").write_text(json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8")

        logger.info("\nスクリーンショット: logs/p2_*.png")
        try:
            input("Enterキーで終了...")
        except (EOFError, KeyboardInterrupt):
            pass
        browser.close()

if __name__ == "__main__":
    main()
