"""
商品情報リッチ化スクリプト

リッチ化未対応の商品を自動でリッチ化する:
  1. リッチ化一覧から未対応商品を取得
  2. 各商品の詳細ページで「商品をリッチ化する」をクリック
  3. モーダルで適切な画像を選択
  4. 「リッチ化文章を生成する」で文章生成
  5. 「この文章を登録する」で登録
  6. 「更新」ボタンで保存

実行方法:
    python enrich_products.py
    python enrich_products.py --dry-run
    python enrich_products.py --count 3
"""
from __future__ import annotations
import argparse, json, logging, os, re, sys, time
from pathlib import Path
from io import BytesIO

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
import requests
from PIL import Image
import numpy as np

from config import ADMIN_USER, ADMIN_PASS, HEADLESS
from add_five import login, is_usable_image, get_slide_img_urls

LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"
ENRICHMENT_URL = f"{BASE}/item/enrichment?sortBy=session&sortOrder=desc"
SKIP_FILE = Path("enrich_skip.json")
_AUTO = os.getenv("AUTO", "0") == "1"


def load_skip_ids() -> set[str]:
    """スキップ対象の商品IDを読み込む"""
    if not SKIP_FILE.exists():
        return set()
    try:
        data = json.loads(SKIP_FILE.read_text(encoding="utf-8"))
        return set(str(x) for x in data.get("ids", []))
    except Exception as e:
        logger.warning(f"スキップリスト読み込み失敗: {e}")
        return set()


def add_skip_id(item_id: str, reason: str) -> None:
    """商品IDをスキップリストに追加"""
    item_id = str(item_id)
    data = {"ids": [], "reasons": {}}
    if SKIP_FILE.exists():
        try:
            data = json.loads(SKIP_FILE.read_text(encoding="utf-8"))
            data.setdefault("ids", [])
            data.setdefault("reasons", {})
        except Exception:
            pass
    if item_id not in data["ids"]:
        data["ids"].append(item_id)
    data["reasons"][item_id] = reason
    SKIP_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info(f"  → スキップリストに追加: ID {item_id} ({reason})")


def get_unenriched_items(page) -> list[dict]:
    """リッチ化一覧から未対応商品のIDとリンクを取得"""
    logger.info("リッチ化一覧ページにアクセス中...")
    page.goto(ENRICHMENT_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)

    items = []
    while True:
        rows = page.query_selector_all("tr")
        for row in rows:
            cells = row.query_selector_all("td")
            if len(cells) < 6:
                continue
            status_text = cells[5].inner_text().strip()
            if status_text == "未対応":
                item_id = cells[0].inner_text().strip()
                name = cells[2].inner_text().strip()
                link = cells[0].query_selector("a")
                href = link.get_attribute("href") if link else f"/item/{item_id}"
                items.append({
                    "id": item_id,
                    "name": name,
                    "url": f"{BASE}{href}" if href.startswith("/") else href
                })

        # 次ページがあればクリック
        try:
            next_btn = page.locator('button:has-text("Next")')
            if next_btn.is_visible() and next_btn.is_enabled():
                next_btn.click()
                page.wait_for_timeout(2000)
            else:
                break
        except Exception:
            break

    logger.info(f"未対応商品: {len(items)}件")
    return items


def select_enrichment_images(page, modal) -> int:
    """
    モーダル内のカルーセル画像から3~4枚を「説明画像に追加」ボタンで選択する。
    フロー: サムネイルクリック→メイン画像切替→「説明画像に追加」クリック を繰り返す。
    画像フィルタリング（中国語テキスト除外・空白除外）を適用。
    Returns: 追加した画像数
    """
    target_min, target_max = 3, 4

    # モーダル内の全imgからサムネイル候補を抽出（http始まりかつユニーク）
    all_imgs = modal.locator("img").all()
    seen_src = set()
    candidates = []  # [(locator, src), ...]
    for img in all_imgs:
        try:
            src = img.get_attribute("src") or ""
        except Exception:
            continue
        if not src.startswith("http"):
            continue
        if src in seen_src:
            continue
        seen_src.add(src)
        candidates.append((img, src))

    logger.info(f"  ユニーク画像候補: {len(candidates)}枚")

    selected_count = 0
    for idx, (thumb, src) in enumerate(candidates):
        if selected_count >= target_max:
            break

        if not is_usable_image(src):
            logger.info(f"    [{idx}] NG: {src[-50:]}")
            continue
        logger.info(f"    [{idx}] OK: {src[-50:]}")

        # サムネイルをクリックしてメイン画像を切り替え
        try:
            thumb.scroll_into_view_if_needed(timeout=3000)
            thumb.click(timeout=5000)
            page.wait_for_timeout(400)
        except Exception as e:
            logger.warning(f"    [{idx}] サムネイルクリック失敗: {e}")
            continue

        # 「説明画像に追加」ボタンをクリック
        try:
            add_btn = modal.get_by_text("説明画像に追加").first
            add_btn.scroll_into_view_if_needed(timeout=3000)
            try:
                add_btn.click(timeout=5000)
            except Exception:
                add_btn.click(force=True, timeout=5000)
            page.wait_for_timeout(500)
            selected_count += 1
            logger.info(f"    [{idx}] ✓ 追加 ({selected_count}枚目)")
        except Exception as e:
            logger.warning(f"    [{idx}] 「説明画像に追加」クリック失敗: {e}")
            continue

    if selected_count < target_min:
        logger.warning(f"  選択数不足: {selected_count}枚 (目標 {target_min}枚以上)")

    logger.info(f"  画像選択完了: {selected_count}枚")
    return selected_count


def enrich_single_product(page, item: dict, dry_run: bool) -> bool:
    """1つの商品をリッチ化する"""
    logger.info(f"\n--- 商品ID {item['id']}: {item['name']} ---")

    page.goto(item["url"], wait_until="networkidle")
    page.wait_for_timeout(2000)

    # ページ下部の「商品をリッチ化する」ボタンを探す
    try:
        enrich_btn = page.locator('button:has-text("商品をリッチ化する")').first
        enrich_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
    except Exception as e:
        logger.warning(f"  「商品をリッチ化する」ボタンが見つかりません: {e}")
        return False

    if dry_run:
        logger.info(f"  [DRY-RUN] リッチ化スキップ: {item['name']}")
        return True

    # ボタンをクリック
    try:
        enrich_btn.click()
        logger.info("  「商品をリッチ化する」をクリック")
    except Exception as e:
        logger.warning(f"  ボタンクリック失敗: {e}")
        return False

    # モーダルが表示されるのを待つ（「情報を取得中です」→ 画像カルーセル）
    logger.info("  情報取得中... (最大60秒)")
    try:
        # 「情報を取得中です」が消えるまで待つ
        page.wait_for_timeout(3000)

        # モーダルが表示され、カルーセルが読み込まれるまで待つ
        page.locator('text=説明生成用画像').wait_for(timeout=60_000)
        logger.info("  モーダル読み込み完了")
        page.wait_for_timeout(1000)
    except PWTimeout:
        logger.warning("  モーダル表示タイムアウト（60秒）")
        page.screenshot(path=f"logs/enrich_timeout_{item['id']}.png")
        add_skip_id(item["id"], "modal_timeout")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    # モーダルを取得
    modal = page.locator('[role="dialog"]').first
    if not modal.is_visible():
        # ダイアログがない場合はモーダル的な要素を探す
        modal = page.locator('text=説明生成用画像').locator("..").locator("..").locator("..")

    # 画像を選択
    try:
        select_enrichment_images(page, modal)
    except Exception as e:
        logger.warning(f"  画像選択エラー: {e}")
        # 画像選択に失敗しても続行（デフォルトの画像が選択されている場合がある）

    # 「リッチ化文章を生成する」をクリック
    try:
        gen_btn = page.locator('button:has-text("リッチ化文章を生成する")').first
        gen_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        # ボタンがenabledになるまで最大60秒待機
        try:
            page.wait_for_function(
                """() => {
                    const btns = Array.from(document.querySelectorAll('button'));
                    const b = btns.find(x => x.textContent && x.textContent.includes('リッチ化文章を生成する'));
                    return b && !b.disabled;
                }""",
                timeout=60_000,
            )
        except PWTimeout:
            logger.info("  生成ボタンenabled待機タイムアウト → force=Trueで試行")
        try:
            gen_btn.click(timeout=10_000)
        except Exception as click_err:
            logger.info(f"  通常click失敗、force=Trueで再試行: {click_err}")
            gen_btn.click(force=True, timeout=10_000)
        logger.info("  「リッチ化文章を生成する」をクリック")
    except Exception as e:
        logger.warning(f"  文章生成ボタンクリック失敗: {e}")
        return False

    # 文章生成完了を待つ（最大90秒）
    logger.info("  文章生成中... (最大90秒)")
    try:
        # 「この文章を登録する」ボタンが表示されるまで待つ
        page.locator('button:has-text("この文章を登録する")').wait_for(timeout=90_000)
        logger.info("  文章生成完了")
        page.wait_for_timeout(1000)
    except PWTimeout:
        logger.warning("  文章生成タイムアウト（90秒）")
        page.screenshot(path=f"logs/enrich_gen_timeout_{item['id']}.png")
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        return False

    # 「この文章を登録する」をクリック
    try:
        register_btn = page.locator('button:has-text("この文章を登録する")')
        register_btn.click()
        logger.info("  「この文章を登録する」をクリック")
        page.wait_for_timeout(2000)
    except Exception as e:
        logger.warning(f"  文章登録ボタンクリック失敗: {e}")
        return False

    # モーダルを閉じる（×ボタンまたはEscape）
    try:
        close_btn = page.locator('button:has-text("×"), [class*="close"]').first
        if close_btn.is_visible():
            close_btn.click()
        else:
            page.keyboard.press("Escape")
        page.wait_for_timeout(1000)
    except Exception:
        page.keyboard.press("Escape")
        page.wait_for_timeout(1000)

    # モーダルが完全に消えるまで待機（最大10秒）
    try:
        page.locator('[role="dialog"]').first.wait_for(state="hidden", timeout=10_000)
    except Exception:
        pass

    # ページ最下部の「更新」ボタンをクリック（form内のsubmitボタン）
    try:
        update_btn = page.locator('form button[type="submit"]:has-text("更新")').first
        update_btn.scroll_into_view_if_needed(timeout=60_000)
        page.wait_for_timeout(500)
        try:
            update_btn.click(timeout=10_000)
        except Exception as click_err:
            logger.info(f"  通常click失敗、force=Trueで再試行: {click_err}")
            update_btn.click(force=True, timeout=10_000)
        logger.info("  「更新」をクリック")
        page.wait_for_timeout(3000)
    except Exception as e:
        logger.warning(f"  更新ボタンクリック失敗: {e}")
        return False

    logger.info(f"  ✓ リッチ化完了: {item['name']}")
    try:
        page.screenshot(path=f"logs/enriched_{item['id']}.png")
    except Exception:
        pass

    return True


def main():
    parser = argparse.ArgumentParser(description="商品リッチ化自動スクリプト")
    parser.add_argument("--dry-run", action="store_true", help="実際には更新しない確認モード")
    parser.add_argument("--count", type=int, default=5, help="処理する商品数")
    parser.add_argument("--no-filter", action="store_true", help="画像フィルタリングを無効化")
    args = parser.parse_args()

    logger.info(f"=== enrich_products.py 開始 | dry_run={args.dry_run} | 目標={args.count}件 ===")

    enriched_count = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)

            # 未対応商品リストを取得
            items = get_unenriched_items(page)

            if not items:
                logger.info("リッチ化未対応の商品はありません")
                return

            # スキップリストを除外
            skip_ids = load_skip_ids()
            if skip_ids:
                before = len(items)
                items = [it for it in items if str(it["id"]) not in skip_ids]
                logger.info(f"スキップリスト適用: {before} → {len(items)}件 (除外 {before - len(items)}件)")

            # 上から順に処理（成功カウントが目標に達するまで継続）
            consecutive_errors = 0
            for item in items:
                if enriched_count >= args.count:
                    break
                # ページが閉じられていたら中断
                if page.is_closed():
                    logger.error("ページが閉じられました。処理を中断します")
                    break
                try:
                    success = enrich_single_product(page, item, dry_run=args.dry_run)
                    if success:
                        enriched_count += 1
                        consecutive_errors = 0
                        logger.info(f"✓✓✓ {enriched_count}/{args.count}件 リッチ化完了")
                    else:
                        logger.warning(f"  商品 {item['id']} のリッチ化に失敗")
                        consecutive_errors += 1
                except Exception as e:
                    logger.error(f"  商品 {item['id']} 処理中にエラー: {e}")
                    consecutive_errors += 1
                    try:
                        if not page.is_closed():
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(1000)
                    except Exception:
                        pass

                if consecutive_errors >= 5:
                    logger.error(f"連続エラー {consecutive_errors}件、処理を中断します")
                    break

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            page.screenshot(path="logs/enrich_unexpected_error.png")

        finally:
            logger.info(f"\n{'='*50}")
            logger.info(f"完了: {enriched_count}/{args.count}件 リッチ化しました")
            logger.info(f"{'='*50}")
            if _AUTO:
                logger.info("\nAUTOモード: ブラウザを閉じます。")
            else:
                logger.info("\nブラウザはそのまま開いています。")
                try:
                    input("Enterキーで終了...")
                except (EOFError, KeyboardInterrupt):
                    pass
            browser.close()


if __name__ == "__main__":
    main()
