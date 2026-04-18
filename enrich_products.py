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
import argparse, logging, re, sys, time
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

from config import ADMIN_USER, ADMIN_PASS
from add_five import login, is_usable_image, get_slide_img_urls

LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"
ENRICHMENT_URL = f"{BASE}/item/enrichment?sortBy=session&sortOrder=desc"


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
    モーダル内のカルーセル画像から適切な画像を2~4枚選択する。
    画像フィルタリング（中国語テキスト除外・空白除外）を適用。
    Returns: 選択した画像数
    """
    # サムネイル画像を取得
    thumbnails = modal.locator("img").all()
    logger.info(f"  モーダル内画像数: {len(thumbnails)}")

    # 既に選択されている画像数を確認
    selected_count = len(modal.locator('button:has-text("↑"), button:has-text("↓")').all()) // 2
    if selected_count == 0:
        # 削除ボタンの数で判断
        delete_btns = modal.locator('[class*="trash"], button:has-text("削除")').all()
        selected_count = len(delete_btns)

    logger.info(f"  既に選択済み画像数: {selected_count}")

    # カルーセルのサムネイル（右側のサムネイル列）をクリックして画像を選択
    # まず、選択可能なサムネイルを探す
    right_thumbnails = modal.locator('img[class*="cursor"], img[class*="thumbnail"], img[class*="thumb"]').all()
    if not right_thumbnails:
        # フォールバック: モーダル右側の小さな画像
        right_thumbnails = modal.locator('img').all()

    img_urls = []
    for thumb in right_thumbnails:
        src = thumb.get_attribute("src") or ""
        if src and src.startswith("http"):
            img_urls.append(src)

    # フィルタリングして適切な画像を選択
    usable_indices = []
    for idx, url in enumerate(img_urls):
        if len(usable_indices) >= 4:
            break
        if is_usable_image(url):
            usable_indices.append(idx)
            logger.info(f"    [{idx}] OK: {url[-50:]}")
        else:
            logger.info(f"    [{idx}] NG: {url[-50:]}")

    if not usable_indices:
        logger.warning("  フィルタ通過画像なし → 最初の3枚を使用")
        usable_indices = list(range(min(3, len(right_thumbnails))))

    # 必要な枚数（2~4枚）を選択
    target_count = max(2, min(4, len(usable_indices)))
    selected = usable_indices[:target_count]

    for idx in selected:
        try:
            right_thumbnails[idx].click()
            page.wait_for_timeout(500)
        except Exception as e:
            logger.warning(f"    画像クリック失敗 [{idx}]: {e}")

    logger.info(f"  画像選択完了: {len(selected)}枚")
    return len(selected)


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
        gen_btn = page.locator('button:has-text("リッチ化文章を生成する")')
        gen_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        gen_btn.click()
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

    # ページ最下部の「更新」ボタンをクリック
    try:
        update_btn = page.locator('button:has-text("更新")')
        update_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        update_btn.click()
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
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)

            # 未対応商品リストを取得
            items = get_unenriched_items(page)

            if not items:
                logger.info("リッチ化未対応の商品はありません")
                return

            # 上から順に処理
            for item in items[:args.count]:
                try:
                    success = enrich_single_product(page, item, dry_run=args.dry_run)
                    if success:
                        enriched_count += 1
                        logger.info(f"✓✓✓ {enriched_count}/{args.count}件 リッチ化完了")
                    else:
                        logger.warning(f"  商品 {item['id']} のリッチ化に失敗")
                except Exception as e:
                    logger.error(f"  商品 {item['id']} 処理中にエラー: {e}")
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass

                if enriched_count >= args.count:
                    break

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            page.screenshot(path="logs/enrich_unexpected_error.png")

        finally:
            logger.info(f"\n{'='*50}")
            logger.info(f"完了: {enriched_count}/{args.count}件 リッチ化しました")
            logger.info(f"{'='*50}")
            logger.info("\nブラウザはそのまま開いています。")
            try:
                input("Enterキーで終了...")
            except (EOFError, KeyboardInterrupt):
                pass
            browser.close()


if __name__ == "__main__":
    main()
