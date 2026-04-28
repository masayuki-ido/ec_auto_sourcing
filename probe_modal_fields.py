"""
Netsea商品追加モーダルの全フィールド(select/input/textarea)をダンプ
カテゴリ・配送情報など何を選択すべきか把握する
"""
from __future__ import annotations
import json, logging
from pathlib import Path
from playwright.sync_api import sync_playwright
from config import ADMIN_USER, ADMIN_PASS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

LOGS = Path("logs/probe_modal_fields")
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
        page.wait_for_timeout(2000)

        page.screenshot(path=str(LOGS / "modal_full.png"), full_page=True)

        # JSで全要素の詳細をダンプ
        info = page.evaluate("""
            () => {
                const dlg = document.querySelector('[role="dialog"][data-state="open"]');
                if (!dlg) return {error: 'no dialog'};
                const result = {selects: [], inputs: [], textareas: [], labels: [], radios: [], checkboxes: []};

                // selects（カテゴリ・配送方法など）
                dlg.querySelectorAll('select').forEach(s => {
                    const options = [...s.options].map(o => ({value: o.value, text: o.innerText.trim(), selected: o.selected}));
                    // 直前のラベル候補
                    let label = '';
                    let el = s;
                    for (let i = 0; i < 5 && el.previousElementSibling; i++) {
                        el = el.previousElementSibling;
                        if (el.innerText && el.innerText.trim().length < 30) {
                            label = el.innerText.trim();
                            break;
                        }
                    }
                    // 親の前のラベルも探す
                    if (!label && s.parentElement) {
                        const pPrev = s.parentElement.previousElementSibling;
                        if (pPrev && pPrev.innerText) label = pPrev.innerText.trim().slice(0, 40);
                    }
                    result.selects.push({name: s.name, id: s.id, label, options});
                });

                // inputs（全部）
                dlg.querySelectorAll('input').forEach(i => {
                    let label = '';
                    let el = i;
                    for (let k = 0; k < 3 && el.previousElementSibling; k++) {
                        el = el.previousElementSibling;
                        if (el.innerText && el.innerText.trim().length < 30) {
                            label = el.innerText.trim(); break;
                        }
                    }
                    result.inputs.push({
                        type: i.type, name: i.name, placeholder: i.placeholder,
                        value: (i.value || '').slice(0, 60), label,
                        checked: i.checked,
                    });
                });

                // textareas
                dlg.querySelectorAll('textarea').forEach(t => {
                    result.textareas.push({name: t.name, placeholder: t.placeholder, value: (t.value || '').slice(0, 100)});
                });

                // ラベル/セクションテキスト（配送関連キーワード検索用）
                [...dlg.querySelectorAll('label, h1, h2, h3, h4, p, span, div')].forEach(el => {
                    const t = (el.innerText || '').trim();
                    if (t && t.length < 50 && /配送|送料|カテゴリ|カラー|サイズ|発送|納期|在庫/.test(t)) {
                        result.labels.push(t);
                    }
                });
                result.labels = [...new Set(result.labels)].slice(0, 30);

                return result;
            }
        """)
        (LOGS / "modal_fields.json").write_text(json.dumps(info, ensure_ascii=False, indent=2), encoding="utf-8")

        print(json.dumps(info, ensure_ascii=False, indent=2))

        browser.close()


if __name__ == "__main__":
    main()
