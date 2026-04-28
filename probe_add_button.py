"""
「商品を追加」ボタン押下後の画面遷移を観察する
押下直後から5秒ごとにスクショを取り、ボタン状態・モーダル・トースト等を記録
"""
from __future__ import annotations
import logging, time
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import ADMIN_USER, ADMIN_PASS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOGS = Path("logs/probe_addbtn")
LOGS.mkdir(parents=True, exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"


def dump_state(page, label: str):
    path = LOGS / f"{label}.png"
    page.screenshot(path=str(path), full_page=True)
    # モーダル・ボタン・トーストの状態
    info = {}
    try:
        dlg = page.locator('[role="dialog"]')
        info["dialog_count"] = dlg.count()
        if dlg.count():
            info["dialog_visible"] = dlg.first.is_visible()
    except Exception as e:
        info["dialog_err"] = str(e)
    try:
        add_btn = page.locator('button:has-text("商品を追加")')
        if add_btn.count():
            info["add_btn_count"] = add_btn.count()
            info["add_btn_text"] = add_btn.first.inner_text()[:40]
            info["add_btn_disabled"] = add_btn.first.is_disabled()
    except Exception as e:
        info["add_btn_err"] = str(e)
    # トースト候補
    for sel in ['[role="status"]', '[class*="toast"]', '[class*="Toast"]', '[class*="notification"]']:
        try:
            el = page.locator(sel)
            if el.count():
                info[f"toast[{sel}]"] = el.first.inner_text()[:100]
        except Exception:
            pass
    logger.info(f"[{label}] {info}")


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.fill('input[name="email"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda u: "login" not in u, timeout=15_000)
        logger.info("ログイン完了")

        page.goto(f"{BASE}/item/search", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.select_option("select", value="netsea2")
        page.wait_for_timeout(800)
        page.locator('input[placeholder*="フリーワード"]').fill("サコッシュ")
        page.wait_for_timeout(300)
        page.locator('button:has-text("検索")').click()
        page.locator('text=商品追加に進む').first.wait_for(timeout=30_000)
        logger.info("検索結果表示")

        # 最初のカードをクリック
        page.locator('text=商品追加に進む').first.click()
        page.locator('[role="dialog"][data-state="open"]').wait_for(timeout=10_000)
        page.wait_for_timeout(1500)
        logger.info("モーダル表示")
        dump_state(page, "00_before_click")

        # 「商品を追加」クリック
        modal = page.locator('[role="dialog"][data-state="open"]')
        add_btn = modal.locator('button:has-text("商品を追加")')
        add_btn.click(timeout=10_000)
        click_ts = time.time()
        logger.info("「商品を追加」クリック")

        # 1秒ごとに状態を30秒間記録
        for i in range(1, 31):
            page.wait_for_timeout(1000)
            dump_state(page, f"{i:02d}s_after")
            # 早期終了: モーダル消えた&トーストあり
            try:
                dlg_vis = page.locator('[role="dialog"]').first.is_visible() if page.locator('[role="dialog"]').count() else False
                if not dlg_vis and i > 5:
                    logger.info(f"モーダル消失検出 @ {i}秒")
                    page.wait_for_timeout(2000)
                    dump_state(page, f"{i+2:02d}s_final")
                    break
            except Exception:
                pass

        logger.info(f"総経過: {time.time() - click_ts:.1f}秒")
        browser.close()


if __name__ == "__main__":
    main()
