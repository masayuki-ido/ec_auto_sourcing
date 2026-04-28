"""
商品一覧のCSVエクスポート挙動を観察する
クリック後のモーダル変化・ネットワーク応答・ダウンロード発生を記録
"""
from __future__ import annotations
import logging, time
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import ADMIN_USER, ADMIN_PASS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOGS = Path("logs/probe_csv")
LOGS.mkdir(parents=True, exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False, downloads_path=str(LOGS / "dl"))
        ctx = browser.new_context(accept_downloads=True)
        page = ctx.new_page()

        # ダウンロード検知
        downloads = []
        page.on("download", lambda d: (
            downloads.append(d),
            logger.info(f"[DOWNLOAD] suggested={d.suggested_filename}")
        ))
        # レスポンス検知（CSVぽいもの）
        page.on("response", lambda r: (
            logger.info(f"[RESP {r.status}] {r.url[-120:]}")
            if ("csv" in r.url.lower() or "export" in r.url.lower() or "download" in r.url.lower())
            else None
        ))

        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.fill('input[name="email"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda u: "login" not in u, timeout=15_000)
        logger.info("ログイン完了")

        page.goto(f"{BASE}/item", wait_until="networkidle")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(LOGS / "01_item_page.png"), full_page=True)

        # 「CSVエクスポート」ボタン
        csv_btn = page.locator('button:has-text("CSVエクスポート")').first
        csv_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        csv_btn.click()
        logger.info("CSVエクスポートボタンクリック")
        page.wait_for_timeout(2000)
        page.screenshot(path=str(LOGS / "02_after_btn1.png"), full_page=True)

        # モーダル内の要素を全列挙
        modal_info = page.evaluate("""
            () => {
                const dlg = document.querySelector('[role="dialog"][data-state="open"]');
                if (!dlg) return {error: 'no dialog'};
                const btns = [...dlg.querySelectorAll('button')].map(b => ({
                    text: b.innerText.trim().slice(0, 80),
                    disabled: b.disabled,
                }));
                const texts = [...dlg.querySelectorAll('h1,h2,h3,h4,p,span,div,label')]
                    .map(e => e.innerText.trim())
                    .filter(t => t && t.length < 100);
                return {btns, texts: [...new Set(texts)].slice(0, 30)};
            }
        """)
        logger.info(f"モーダル内容: {modal_info}")

        # 「商品データを全てCSVにエクスポート」の横のCSVエクスポートをクリック
        btns = page.locator('[role="dialog"][data-state="open"] button:has-text("CSVエクスポート")').all()
        logger.info(f"モーダル内ボタン数: {len(btns)}")
        if len(btns) >= 2:
            # download イベント待機付きでクリック
            try:
                with page.expect_download(timeout=30_000) as dl_info:
                    btns[1].click()
                    logger.info("モーダル内CSVエクスポートクリック（ダウンロード待機）")
                download = dl_info.value
                save_path = LOGS / download.suggested_filename
                download.save_as(str(save_path))
                logger.info(f"[DOWNLOADED] {save_path} ({save_path.stat().st_size} bytes)")
            except Exception as e:
                logger.warning(f"ダウンロード待機失敗: {e}")
                page.screenshot(path=str(LOGS / "03_download_fail.png"), full_page=True)
                # モーダルの状態を確認
                page.wait_for_timeout(3000)
                modal_after = page.evaluate("""
                    () => {
                        const dlg = document.querySelector('[role="dialog"]');
                        if (!dlg) return 'no dialog';
                        return dlg.innerText.slice(0, 500);
                    }
                """)
                logger.info(f"クリック後のモーダル: {modal_after}")
        elif len(btns) == 1:
            btns[0].click()
            logger.info("モーダル内ボタン1つをクリック")
            page.wait_for_timeout(5000)
            page.screenshot(path=str(LOGS / "03_after_single_btn.png"), full_page=True)
        else:
            logger.warning("モーダル内にCSVエクスポートボタンが見つからない")

        logger.info(f"ダウンロードイベント発火数: {len(downloads)}")
        page.wait_for_timeout(3000)
        browser.close()


if __name__ == "__main__":
    main()
