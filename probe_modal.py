"""
モーダルのスクショを実サイズで取る + ボタン周辺の状態をJSで取得
"""
from __future__ import annotations
import json, logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import ADMIN_USER, ADMIN_PASS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOGS = Path("logs/probe_modal")
LOGS.mkdir(parents=True, exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"


def main():
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1400, "height": 1000})
        page.goto(f"{BASE}/login", wait_until="domcontentloaded")
        page.fill('input[name="email"]', ADMIN_USER)
        page.fill('input[name="password"]', ADMIN_PASS)
        page.click('button[type="submit"]')
        page.wait_for_url(lambda u: "login" not in u, timeout=15_000)

        page.goto(f"{BASE}/item/search", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.select_option("select", value="netsea2")
        page.wait_for_timeout(800)
        page.locator('input[placeholder*="フリーワード"]').fill("サコッシュ")
        page.locator('button:has-text("検索")').click()
        page.locator('text=商品追加に進む').first.wait_for(timeout=30_000)

        page.locator('text=商品追加に進む').first.click()
        page.locator('[role="dialog"][data-state="open"]').wait_for(timeout=10_000)
        page.wait_for_timeout(1500)

        # モーダル部分だけのスクショ（viewport）
        page.screenshot(path=str(LOGS / "modal_before.png"), full_page=False)

        # JSで商品を追加ボタンの周辺情報を取得
        info = page.evaluate("""
            () => {
                const btns = [...document.querySelectorAll('[role="dialog"] button')];
                return btns.map(b => ({
                    text: b.innerText.trim().slice(0, 60),
                    disabled: b.disabled,
                    type: b.type,
                    class: (b.className || '').slice(0, 80),
                    rect: (() => { const r = b.getBoundingClientRect(); return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height), visible: r.width > 0 && r.height > 0}; })(),
                }));
            }
        """)
        (LOGS / "buttons.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("=== モーダル内ボタン一覧 ===")
        for b in info:
            logger.info(f"  text=[{b['text']}] disabled={b['disabled']} type={b['type']} rect={b['rect']}")

        # ボタンを探してクリック（3通りの方法を試す）
        add_loc = page.locator('[role="dialog"][data-state="open"] button:has-text("商品を追加")')
        n = add_loc.count()
        logger.info(f"商品を追加ボタン数: {n}")

        if n > 0:
            btn = add_loc.first
            # (1) 通常click
            logger.info("(1) 通常clickを試行")
            btn.click(timeout=5_000)
            page.wait_for_timeout(3000)
            page.screenshot(path=str(LOGS / "after_click1.png"), full_page=False)

            # 状態チェック
            try:
                dlg_vis = page.locator('[role="dialog"]').first.is_visible()
            except Exception:
                dlg_vis = False
            logger.info(f"  dialog_visible: {dlg_vis}")

            if dlg_vis:
                # (2) JSのclick()をevaluate
                logger.info("(2) JS .click() を試行")
                page.evaluate("""
                    () => {
                        const btns = [...document.querySelectorAll('[role="dialog"] button')];
                        const add = btns.find(b => b.innerText.trim().includes('商品を追加'));
                        if (add) {
                            add.scrollIntoView({block:'center'});
                            add.click();
                            return 'clicked';
                        }
                        return 'not found';
                    }
                """)
                page.wait_for_timeout(3000)
                page.screenshot(path=str(LOGS / "after_click2.png"), full_page=False)
                try:
                    dlg_vis = page.locator('[role="dialog"]').first.is_visible()
                except Exception:
                    dlg_vis = False
                logger.info(f"  dialog_visible: {dlg_vis}")

            if dlg_vis:
                # (3) dispatchEvent
                logger.info("(3) dispatchEvent を試行")
                page.evaluate("""
                    () => {
                        const btns = [...document.querySelectorAll('[role="dialog"] button')];
                        const add = btns.find(b => b.innerText.trim().includes('商品を追加'));
                        if (add) {
                            ['pointerdown','mousedown','pointerup','mouseup','click'].forEach(t => {
                                add.dispatchEvent(new MouseEvent(t, {bubbles:true, cancelable:true}));
                            });
                        }
                    }
                """)
                page.wait_for_timeout(5000)
                page.screenshot(path=str(LOGS / "after_click3.png"), full_page=False)

            # 成否最終確認
            page.wait_for_timeout(5000)
            try:
                final_dlg_vis = page.locator('[role="dialog"]').first.is_visible()
            except Exception:
                final_dlg_vis = False
            logger.info(f"最終状態 dialog_visible: {final_dlg_vis}")

        browser.close()


if __name__ == "__main__":
    main()
