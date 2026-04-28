"""ログイン後ダッシュボードのナビリンク一覧をダンプする"""
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


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(ADMIN_URL, wait_until="networkidle")
        page.fill('input[name="email"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_load_state("networkidle", timeout=20_000)
        page.wait_for_timeout(3000)

        logger.info(f"ログイン後URL: {page.url}")
        page.screenshot(path=str(LOGS / "nav_dashboard.png"), full_page=True)
        (LOGS / "nav_dashboard.html").write_text(page.content(), encoding="utf-8")

        # 全リンクをダンプ
        links = []
        for a in page.query_selector_all("a"):
            text = (a.inner_text() or "").strip()[:60]
            href = a.get_attribute("href") or ""
            if text or href:
                links.append({"text": text, "href": href})

        (LOGS / "nav_links.json").write_text(
            json.dumps(links, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"リンク数: {len(links)}")
        for l in links:
            if l["text"]:
                print(f"  [{l['text']}] -> {l['href']}")

        browser.close()


if __name__ == "__main__":
    main()
