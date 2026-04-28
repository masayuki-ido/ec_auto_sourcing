"""検索ページ /item/search の構造をダンプ"""
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
        page.wait_for_timeout(3000)
        page.screenshot(path=str(LOGS / "search_before.png"), full_page=True)

        # input/button/select列挙
        dump = {"inputs": [], "buttons": [], "selects": [], "textareas": []}
        for el in page.query_selector_all("input"):
            dump["inputs"].append({
                "type": el.get_attribute("type"),
                "name": el.get_attribute("name"),
                "id": el.get_attribute("id"),
                "placeholder": el.get_attribute("placeholder"),
                "class": (el.get_attribute("class") or "")[:80],
            })
        for el in page.query_selector_all("button"):
            dump["buttons"].append({
                "text": (el.inner_text() or "").strip()[:40],
                "type": el.get_attribute("type"),
                "class": (el.get_attribute("class") or "")[:80],
            })
        for el in page.query_selector_all("select"):
            dump["selects"].append({
                "name": el.get_attribute("name"),
                "id": el.get_attribute("id"),
            })
        for el in page.query_selector_all("textarea"):
            dump["textareas"].append({
                "name": el.get_attribute("name"),
                "placeholder": el.get_attribute("placeholder"),
            })

        (LOGS / "search_structure.json").write_text(
            json.dumps(dump, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(json.dumps(dump, ensure_ascii=False, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
