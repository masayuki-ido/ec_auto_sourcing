"""
管理画面の構造を調べる診断スクリプト
実行するとスクリーンショットとHTML断片をlogsに保存します

実行方法:
    python probe.py
"""
import json
import logging
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

# ログ設定
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

from config import ADMIN_URL, ADMIN_USER, ADMIN_PASS, HEADLESS
LOGS = Path("logs")
LOGS.mkdir(exist_ok=True)


def save_screenshot(page, name: str):
    path = LOGS / f"probe_{name}.png"
    page.screenshot(path=str(path), full_page=True)
    logger.info(f"スクリーンショット保存: {path}")


def save_html(page, name: str):
    path = LOGS / f"probe_{name}.html"
    path.write_text(page.content(), encoding="utf-8")
    logger.info(f"HTML保存: {path}")


def probe_inputs(page) -> dict:
    """ページ上のinput/select/buttonを列挙する。"""
    result = {"inputs": [], "buttons": [], "selects": [], "links": []}

    for el in page.query_selector_all("input"):
        result["inputs"].append({
            "type":        el.get_attribute("type") or "text",
            "name":        el.get_attribute("name"),
            "id":          el.get_attribute("id"),
            "placeholder": el.get_attribute("placeholder"),
            "class":       el.get_attribute("class"),
        })

    for el in page.query_selector_all("button, input[type='submit']"):
        result["buttons"].append({
            "text":  el.inner_text().strip()[:50],
            "type":  el.get_attribute("type"),
            "class": el.get_attribute("class"),
            "id":    el.get_attribute("id"),
        })

    for el in page.query_selector_all("select"):
        options = [o.inner_text().strip() for o in el.query_selector_all("option")]
        result["selects"].append({
            "name":    el.get_attribute("name"),
            "id":      el.get_attribute("id"),
            "options": options[:10],  # 最大10件
        })

    for el in page.query_selector_all("nav a, header a, .sidebar a, .menu a"):
        href = el.get_attribute("href")
        text = el.inner_text().strip()[:40]
        if text:
            result["links"].append({"text": text, "href": href})

    return result


def main():
    logger.info("=== 管理画面 構造調査 開始 ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)  # 画面を表示して確認
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        # ── Step 1: ログインページ ──
        logger.info(f"ログインページへアクセス: {ADMIN_URL}")
        page.goto(ADMIN_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2000)

        save_screenshot(page, "01_login_page")
        save_html(page, "01_login_page")

        info = probe_inputs(page)
        logger.info(f"ログインページのinput一覧:\n{json.dumps(info, ensure_ascii=False, indent=2)}")
        (LOGS / "probe_01_elements.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        # ── Step 2: ログイン試行 ──
        logger.info("ログイン試行...")
        if not ADMIN_USER:
            logger.error(".envにADMIN_USERが設定されていません")
            browser.close()
            return

        # よくあるセレクタを順に試す
        login_selectors = [
            ('input[name="email"]',    'input[name="password"]'),
            ('input[name="username"]', 'input[name="password"]'),
            ('input[type="email"]',    'input[type="password"]'),
            ('input[name="login"]',    'input[name="pass"]'),
            ('#email',                 '#password'),
            ('#username',              '#password'),
        ]

        logged_in = False
        for user_sel, pass_sel in login_selectors:
            try:
                if page.query_selector(user_sel) and page.query_selector(pass_sel):
                    logger.info(f"セレクタ発見: {user_sel} / {pass_sel}")
                    page.fill(user_sel, ADMIN_USER)
                    page.fill(pass_sel, ADMIN_PASS)

                    # submitボタンを探す
                    for btn_sel in ['button[type="submit"]', 'input[type="submit"]',
                                    'button:has-text("ログイン")', 'button:has-text("Login")',
                                    'button:has-text("サインイン")', 'button:has-text("Sign in")']:
                        if page.query_selector(btn_sel):
                            page.click(btn_sel)
                            break
                    else:
                        page.keyboard.press("Enter")

                    page.wait_for_load_state("networkidle", timeout=15_000)
                    logged_in = True
                    break
            except Exception as e:
                logger.debug(f"セレクタ {user_sel} 失敗: {e}")

        if not logged_in:
            logger.error("ログイン失敗: セレクタが見つかりませんでした")
            save_screenshot(page, "02_login_failed")
            save_html(page, "02_login_failed")
            browser.close()
            return

        logger.info(f"ログイン後URL: {page.url}")
        save_screenshot(page, "02_after_login")
        save_html(page, "02_after_login")

        info2 = probe_inputs(page)
        (LOGS / "probe_02_elements.json").write_text(
            json.dumps(info2, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info(f"ログイン後ページのナビリンク:\n{json.dumps(info2['links'][:20], ensure_ascii=False, indent=2)}")

        # ── Step 3: 商品関連ページを探す ──
        product_keywords = ["product", "商品", "alibaba", "item", "catalog", "catalogue"]
        found_product_page = False

        for link_info in info2["links"]:
            href = link_info.get("href", "") or ""
            text = link_info.get("text", "") or ""
            if any(kw in href.lower() or kw in text.lower() for kw in product_keywords):
                logger.info(f"商品関連リンク発見: {text} → {href}")
                try:
                    page.click(f'a[href="{href}"]')
                    page.wait_for_load_state("networkidle", timeout=10_000)
                    save_screenshot(page, f"03_product_page")
                    save_html(page, f"03_product_page")
                    info3 = probe_inputs(page)
                    (LOGS / "probe_03_elements.json").write_text(
                        json.dumps(info3, ensure_ascii=False, indent=2), encoding="utf-8"
                    )
                    logger.info(f"商品ページURL: {page.url}")
                    found_product_page = True
                    break
                except Exception as e:
                    logger.warning(f"商品ページ遷移失敗: {e}")

        if not found_product_page:
            logger.warning("商品関連ページへの自動遷移に失敗しました。手動でページを確認してください。")
            # 5秒待ってもう一度スクリーンショット
            page.wait_for_timeout(5000)
            save_screenshot(page, "03_manual_check")

        logger.info(
            "\n=== 調査完了 ===\n"
            f"スクリーンショット・HTMLは logs/ フォルダに保存されました。\n"
            f"logs/probe_01_elements.json ... ログインページの要素\n"
            f"logs/probe_02_elements.json ... ログイン後の要素・ナビリンク\n"
            f"ブラウザはそのまま開いています。手動で画面を確認してください。\n"
            "終了するには Ctrl+C を押してください。"
        )

        # ブラウザを開いたまま待機（手動確認用）
        try:
            input("Enterキーで終了...")
        except (KeyboardInterrupt, EOFError):
            pass

        browser.close()
    logger.info("=== 終了 ===")


if __name__ == "__main__":
    main()
