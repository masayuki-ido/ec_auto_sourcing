"""
検索結果の動的読み込みを待ってから構造を調査
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


def main():
    api_calls = []

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # APIコールを全て記録
        def on_request(req):
            if req.resource_type in ("xhr", "fetch"):
                api_calls.append({"method": req.method, "url": req.url})
        def on_response(resp):
            if resp.request.resource_type in ("xhr", "fetch") and resp.status < 400:
                for call in api_calls:
                    if call["url"] == resp.url and "response" not in call:
                        try:
                            body = resp.text()[:500]
                            call["response_preview"] = body
                        except:
                            pass
        page.on("request", on_request)
        page.on("response", on_response)

        login(page)

        # ── 検索ページへ ──
        page.goto(f"{BASE}/item/search", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # 検索実行
        page.fill('input[type="text"]', "サコッシュ")
        page.wait_for_timeout(500)
        page.click('button:has-text("検索")')

        # 結果が出るまで最大10秒待つ
        logger.info("検索結果を待機中...")
        result_appeared = False
        for sel in [
            "table tbody tr",
            "[class*='item-card']",
            "[class*='product-card']",
            "[class*='search-result']",
            "div[class*='grid'] > div",
            "ul > li",
            # Next.js のレンダリング待ち
        ]:
            try:
                page.wait_for_selector(sel, timeout=8_000)
                rows = page.query_selector_all(sel)
                if len(rows) > 1:
                    logger.info(f"結果検出 ({sel}): {len(rows)}件")
                    result_appeared = True
                    # 最初の3件の内容を表示
                    for i, row in enumerate(rows[:3]):
                        text = row.inner_text()[:100].replace("\n", " | ")
                        logger.info(f"  [{i}] {text}")
                    break
            except:
                continue

        page.wait_for_timeout(3000)
        page.screenshot(path="logs/p4_search_result.png", full_page=True)
        (LOGS / "p4_search_result.html").write_text(page.content(), encoding="utf-8")

        if not result_appeared:
            logger.warning("標準セレクタでは結果が見つかりませんでした。HTMLを調査します")
            # body内のdiv構造を調べる
            body_text = page.inner_text("body")
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            logger.info(f"ページテキスト（最初の50行）:\n" + "\n".join(lines[:50]))

        # APIコールのログ
        logger.info(f"\n=== APIコール ({len(api_calls)}件) ===")
        for call in api_calls:
            logger.info(f"  {call['method']} {call['url']}")
            if "response_preview" in call:
                logger.info(f"    → {call['response_preview'][:200]}")

        (LOGS / "p4_api_calls.json").write_text(
            json.dumps(api_calls, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ── 商品詳細の inputs を詳しく ──
        logger.info("\n=== 商品詳細ページ /item/31 のフォーム ===")
        page.goto(f"{BASE}/item/31", wait_until="networkidle")
        page.wait_for_timeout(2000)

        # 全inputの情報
        for inp in page.query_selector_all("input, textarea, select"):
            tag  = inp.evaluate("e => e.tagName")
            name = inp.get_attribute("name") or ""
            id_  = inp.get_attribute("id") or ""
            val  = inp.evaluate("e => e.value") or ""
            ph   = inp.get_attribute("placeholder") or ""
            if name or id_:
                logger.info(f"  {tag}: name={name!r} id={id_!r} value={val[:40]!r} placeholder={ph!r}")

        logger.info("\n完了")
        try:
            input("Enterキーで終了...")
        except (EOFError, KeyboardInterrupt):
            pass
        browser.close()


if __name__ == "__main__":
    main()
