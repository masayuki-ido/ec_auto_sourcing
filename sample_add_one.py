"""
1件だけ商品を追加するサンプルスクリプト

確認済みフロー:
  1. ログイン
  2. /item/search へ移動
  3. 検索モード選択（画像URL or キーワード）
  4. 検索実行
  5. 最初の商品の「詳細を見る」をクリック → モーダルが開く
  6. モーダル内で設定:
       - カテゴリ選択
       - 商品コンセプト入力
       - 販売価格確認
       - カラー・サイズ入力
       - 商品画像を「商品画像に追加」で選択
  7. 「この商品をTaobaoからサイトに追加」をクリック

実行方法:
    python sample_add_one.py                    # 画像URL検索（デフォルト）
    python sample_add_one.py --keyword          # キーワード検索
    python sample_add_one.py --dry-run          # 追加ボタンは押さない
    python sample_add_one.py --image-url "URL"  # 画像URLを指定
"""
import argparse, logging, sys
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from config import ADMIN_USER, ADMIN_PASS
LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"

# ─── サンプル値（必要に応じて変更） ────────────────────
SAMPLE_KEYWORD   = "サコッシュ"
SAMPLE_IMAGE_URL = (
    "https://g-search1.alicdn.com/img/bao/uploaded/i4/i1/"
    "1049653664/O1CN01iPes6U1cw9q46zYvI_!!0-item_pic.jpg"
)
SAMPLE_CONCEPT   = "軽量で使いやすい、毎日のお出かけにぴったりのサコッシュ"
SAMPLE_COLOR     = "ブラック, ネイビー, ベージュ"
SAMPLE_SIZE      = "縦15cm × 横25cm × マチ3cm"
# ────────────────────────────────────────────────────────


def step_login(page) -> None:
    """Step 1: ログイン"""
    logger.info("Step 1: ログイン")
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.fill('input[name="email"]', ADMIN_USER)
    page.fill('input[name="password"]', ADMIN_PASS)
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: "login" not in url, timeout=15_000)
    logger.info(f"  ✓ ログイン成功")


def step_search(page, use_image: bool, image_url: str, keyword: str) -> bool:
    """Step 2: 検索"""
    logger.info(f"Step 2: 検索（{'画像URL' if use_image else 'キーワード'}）")
    page.goto(f"{BASE}/item/search", wait_until="networkidle")
    page.wait_for_timeout(1000)

    if use_image:
        page.select_option("select", value="image")
        page.wait_for_timeout(500)
        page.fill('input[placeholder*="URL"]', image_url)
        logger.info(f"  画像URL: {image_url[:60]}...")
        page.click('button:has-text("検索")')
    else:
        page.select_option("select", value="word2")
        page.wait_for_timeout(500)
        page.fill('input[type="text"]', keyword)
        logger.info(f"  キーワード: 「{keyword}」")
        page.click('button:has-text("検索")')

    page.screenshot(path="logs/step2_search_submitted.png")

    try:
        page.wait_for_selector('button:has-text("詳細を見る")', timeout=30_000)
        logger.info("  ✓ 検索結果が表示されました")
        page.screenshot(path="logs/step2_search_result.png", full_page=True)
        return True
    except PWTimeout:
        logger.error("  ✗ 検索結果がタイムアウト。セレクタまたはネットワークを確認してください。")
        page.screenshot(path="logs/step2_search_timeout.png")
        return False


def step_open_modal(page) -> bool:
    """
    Step 3: 画像が3枚以上ある商品の「詳細を見る」をクリックしてモーダルを開く
    画像が足りない商品はスキップして次の商品を試す。
    """
    import re
    logger.info("Step 3: 商品詳細モーダルを開く（画像3枚以上の商品を探す）")

    detail_btns = page.query_selector_all('button:has-text("詳細を見る")')
    if not detail_btns:
        logger.error("  ✗ 「詳細を見る」ボタンが見つかりません")
        return False

    for i, btn in enumerate(detail_btns[:10]):
        try:
            card_text = btn.evaluate("el => el.closest('div')?.parentElement?.innerText || ''")
            logger.info(f"  [{i}] 商品: {card_text[:60].replace(chr(10), ' | ')}")
        except Exception:
            pass

        btn.click()
        logger.info(f"  [{i}] 「詳細を見る」をクリック")

        try:
            page.wait_for_selector('[role="dialog"]', timeout=8_000)
            page.wait_for_timeout(1500)

            # スライド枚数を確認
            modal_text = page.locator('[role="dialog"]').inner_text()
            slide_match = re.search(r'(\d+)/(\d+)', modal_text)
            if slide_match:
                total = int(slide_match.group(2))
                logger.info(f"  [{i}] 画像枚数: {total}")
                if total >= 3:
                    logger.info(f"  ✓ 十分な画像数です（{total}枚）")
                    page.screenshot(path="logs/step3_modal_open.png", full_page=True)
                    return True
                else:
                    logger.info(f"  [{i}] 画像{total}枚は不足（3枚以上必要）→ 次の商品へ")
            else:
                logger.info(f"  [{i}] スライド情報不明 → スキップ")

            # モーダルを閉じて次へ
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

        except Exception as e:
            logger.warning(f"  [{i}] モーダルエラー: {e}")
            page.keyboard.press("Escape")
            page.wait_for_timeout(500)

    logger.error("  ✗ 画像3枚以上の商品が見つかりませんでした")
    return False


def step_fill_modal(page, concept: str, color: str, size: str, dry_run: bool) -> bool:
    """Step 4: モーダル内のフォームを設定"""
    logger.info("Step 4: モーダルのフォームを設定")

    modal = page.locator('[role="dialog"]')

    # ── カテゴリ選択 ──
    try:
        cat_select = modal.locator("select").first
        options = cat_select.locator("option").all()
        opt_texts = [o.inner_text() for o in options if o.get_attribute("value")]
        logger.info(f"  カテゴリ選択肢: {opt_texts}")

        # 空でない最初のオプションを選択
        for opt in options:
            val = opt.get_attribute("value")
            if val:
                cat_select.select_option(value=val)
                logger.info(f"  カテゴリ選択: 「{opt.inner_text()}」")
                break
    except Exception as e:
        logger.warning(f"  カテゴリ選択失敗: {e}")

    # ── 商品コンセプト ──
    try:
        concept_input = modal.locator('input[placeholder="商品のコンセプトを入力"]')
        concept_input.fill(concept)
        logger.info(f"  コンセプト入力: 「{concept}」")
    except Exception as e:
        logger.warning(f"  コンセプト入力失敗: {e}")

    # ── 販売価格（自動計算済みを確認） ──
    try:
        price_inputs = modal.locator('input[type="number"]').all()
        editable_prices = [p for p in price_inputs if not p.evaluate("e => e.readOnly")]
        if editable_prices:
            current = editable_prices[0].input_value()
            logger.info(f"  販売価格（自動）: {current}円")
    except Exception as e:
        logger.warning(f"  価格確認失敗: {e}")

    # ── カラー ──
    try:
        color_input = modal.locator('input[placeholder="カラー情報"]')
        color_input.fill(color)
        logger.info(f"  カラー入力: 「{color}」")
    except Exception as e:
        logger.warning(f"  カラー入力失敗: {e}")

    # ── サイズ ──
    try:
        size_input = modal.locator('input[placeholder="サイズ情報"]')
        size_input.fill(size)
        logger.info(f"  サイズ入力: 「{size}」")
    except Exception as e:
        logger.warning(f"  サイズ入力失敗: {e}")

    # ── 商品画像を「商品画像に追加」で選択（3枚以上） ──
    import re
    try:
        add_img_btns = modal.locator('button:has-text("商品画像に追加")').all()
        logger.info(f"  商品画像ボタン数: {len(add_img_btns)}")
        for i, btn in enumerate(add_img_btns[:8]):  # 最大8枚まで追加
            try:
                btn.click()
                page.wait_for_timeout(400)
                logger.info(f"  商品画像{i+1}枚目を追加")
            except Exception as e:
                logger.debug(f"  画像{i+1}枚目クリック失敗: {e}")

        # 選択枚数を確認
        page.wait_for_timeout(500)
        modal_text = modal.inner_text()
        count_match = re.search(r'(\d+)枚選択中', modal_text)
        if count_match:
            logger.info(f"  ✓ 商品画像 {count_match.group(1)}枚 選択済み")
    except Exception as e:
        logger.warning(f"  商品画像追加失敗: {e}")

    page.screenshot(path="logs/step4_modal_filled.png", full_page=True)
    logger.info("  ✓ フォーム入力完了")

    # ── 追加ボタン ──
    if dry_run:
        logger.info("  [DRY-RUN] 「この商品をTaobaoからサイトに追加」はスキップします")
        return True

    try:
        add_btn = modal.locator('button:has-text("この商品をTaobaoからサイトに追加")')
        add_btn.wait_for(timeout=5_000)
        add_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(500)
        page.screenshot(path="logs/step5_before_add.png", full_page=True)

        logger.info("  「この商品をTaobaoからサイトに追加」をクリック！")
        add_btn.click()
        page.wait_for_timeout(5_000)
        page.screenshot(path="logs/step5_after_add.png", full_page=True)
        logger.info(f"  追加後URL: {page.url}")
        logger.info("  ✓ 商品追加完了！")
        return True

    except Exception as e:
        logger.error(f"  ✗ 追加ボタンクリック失敗: {e}")
        page.screenshot(path="logs/step5_error.png")
        return False


def main():
    parser = argparse.ArgumentParser(description="1件商品追加サンプル")
    parser.add_argument("--image-url", default=SAMPLE_IMAGE_URL)
    parser.add_argument("--keyword",   action="store_true", help="キーワード検索モード")
    parser.add_argument("--dry-run",   action="store_true", help="追加ボタンは押さない")
    parser.add_argument("--concept",   default=SAMPLE_CONCEPT)
    parser.add_argument("--color",     default=SAMPLE_COLOR)
    parser.add_argument("--size",      default=SAMPLE_SIZE)
    args = parser.parse_args()

    logger.info(f"=== sample_add_one.py 開始 | dry_run={args.dry_run} ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            step_login(page)

            ok = step_search(page, not args.keyword, args.image_url, SAMPLE_KEYWORD)
            if not ok:
                return

            ok = step_open_modal(page)
            if not ok:
                return

            ok = step_fill_modal(page, args.concept, args.color, args.size, args.dry_run)

            if ok and not args.dry_run:
                logger.info("\n✓✓✓ 1件の商品追加が完了しました！ ✓✓✓")
            elif ok and args.dry_run:
                logger.info("\n✓ DRY-RUN完了。--dry-run を外すと実際に追加されます。")

            logger.info("\n各ステップのスクリーンショット: logs/step*.png")

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            page.screenshot(path="logs/unexpected_error.png")

        finally:
            logger.info("\nブラウザはそのまま開いています。")
            try:
                input("Enterキーで終了...")
            except (EOFError, KeyboardInterrupt):
                pass
            browser.close()


if __name__ == "__main__":
    main()
