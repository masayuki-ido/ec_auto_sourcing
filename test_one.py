"""
1件だけ商品を追加するサンプル実行スクリプト
probe.py でセレクタを確認してから、このファイルのSEL_*を書き換えて実行してください

実行方法:
    python test_one.py
    python test_one.py --dry-run    # 追加ボタンは押さずに途中まで確認
"""
import argparse
import logging
import sys
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from config import ADMIN_URL, ADMIN_USER, ADMIN_PASS

# ================================================================
# ここを probe.py の結果を見て書き換えてください
# ================================================================

# ログインフォーム
SEL_LOGIN_USER   = 'input[name="email"]'
SEL_LOGIN_PASS   = 'input[name="password"]'
SEL_LOGIN_BTN    = 'button[type="submit"]'
SEL_AFTER_LOGIN  = 'nav, .sidebar, [class*="dashboard"]'   # ログイン後に現れる要素

# 商品検索ページへのパス（ログイン後のURLルート）
SEARCH_PAGE_PATH = "/products/alibaba-search"    # ← 要確認・変更

# 検索フォーム
SEL_SEARCH_INPUT = 'input[placeholder*="検索"], input[name="keyword"]'
SEL_SEARCH_BTN   = 'button[type="submit"]'

# 検索結果の1行目
SEL_FIRST_ROW    = 'table tbody tr:first-child, .product-item:first-child'

# 詳細ページへのリンク（行内）
SEL_DETAIL_LINK  = 'a, button:has-text("詳細")'

# カテゴリプルダウン
SEL_CATEGORY     = 'select[name="category"], #category'

# 追加ボタン
SEL_ADD_BTN      = 'button:has-text("追加"), button:has-text("登録"), button:has-text("ECに追加")'

# ================================================================

SEARCH_KEYWORD = "サコッシュ"


def main(dry_run: bool = False):
    logger.info(f"=== test_one.py 開始 | keyword={SEARCH_KEYWORD} | dry_run={dry_run} ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)   # 画面を見ながら確認
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            # ── Step 1: ログイン ──────────────────────────────
            logger.info("Step 1: ログイン")
            page.goto(ADMIN_URL, wait_until="domcontentloaded")
            page.wait_for_timeout(1500)

            page.fill(SEL_LOGIN_USER, ADMIN_USER)
            page.fill(SEL_LOGIN_PASS, ADMIN_PASS)
            page.click(SEL_LOGIN_BTN)

            try:
                page.wait_for_selector(SEL_AFTER_LOGIN, timeout=15_000)
                logger.info(f"  ✓ ログイン成功 | URL: {page.url}")
            except PWTimeout:
                page.screenshot(path="logs/test_one_login_fail.png")
                logger.error("  ✗ ログイン失敗。SEL_LOGIN_* を確認してください。")
                logger.error("    スクリーンショット: logs/test_one_login_fail.png")
                return

            # ── Step 2: 検索ページへ移動 ─────────────────────
            logger.info("Step 2: 検索ページへ移動")
            base = ADMIN_URL.rstrip("/").rsplit("/login", 1)[0]
            target = base + SEARCH_PAGE_PATH
            page.goto(target, wait_until="networkidle")
            logger.info(f"  URL: {page.url}")
            page.screenshot(path="logs/test_one_search_page.png")

            # ── Step 3: キーワード検索 ───────────────────────
            logger.info(f"Step 3: 「{SEARCH_KEYWORD}」で検索")
            try:
                page.wait_for_selector(SEL_SEARCH_INPUT, timeout=8_000)
                page.fill(SEL_SEARCH_INPUT, SEARCH_KEYWORD)
                page.click(SEL_SEARCH_BTN)
                page.wait_for_load_state("networkidle")
                logger.info(f"  ✓ 検索完了 | URL: {page.url}")
                page.screenshot(path="logs/test_one_search_result.png")
            except PWTimeout:
                logger.error("  ✗ 検索フォームが見つかりません。SEL_SEARCH_INPUT を確認してください。")
                page.screenshot(path="logs/test_one_search_fail.png")
                return

            # ── Step 4: 最初の商品を選択 ─────────────────────
            logger.info("Step 4: 最初の商品を選択")
            try:
                first_row = page.wait_for_selector(SEL_FIRST_ROW, timeout=8_000)
                name_text = first_row.inner_text()[:60].replace("\n", " ")
                logger.info(f"  対象商品: {name_text}")
                page.screenshot(path="logs/test_one_before_click.png")

                # 詳細リンクをクリック
                detail = first_row.query_selector(SEL_DETAIL_LINK)
                if detail:
                    detail.click()
                else:
                    first_row.click()
                page.wait_for_load_state("networkidle")
                logger.info(f"  ✓ 商品詳細へ遷移 | URL: {page.url}")
                page.screenshot(path="logs/test_one_product_detail.png")

            except PWTimeout:
                logger.error("  ✗ 検索結果が見つかりません。SEL_FIRST_ROW を確認してください。")
                page.screenshot(path="logs/test_one_no_result.png")
                return

            # ── Step 5: カテゴリ選択 ─────────────────────────
            logger.info("Step 5: カテゴリ選択")
            try:
                cat_el = page.query_selector(SEL_CATEGORY)
                if cat_el:
                    page.select_option(SEL_CATEGORY, label="ショルダーバッグ")
                    logger.info("  ✓ カテゴリ「ショルダーバッグ」を選択")
                else:
                    logger.warning("  カテゴリプルダウンが見つかりません（スキップ）")
            except Exception as e:
                logger.warning(f"  カテゴリ選択失敗（スキップ）: {e}")

            # ── Step 6: 追加ボタン ───────────────────────────
            if dry_run:
                logger.info("Step 6: [DRY-RUN] 追加ボタンは押しません")
                page.screenshot(path="logs/test_one_dryrun_final.png")
                logger.info("  ✓ ここまで正常に進みました！")
                logger.info("  追加ボタンの場所を確認してから --dry-run なしで再実行してください。")
            else:
                logger.info("Step 6: 追加ボタンをクリック")
                try:
                    add_btn = page.wait_for_selector(SEL_ADD_BTN, timeout=8_000)
                    page.screenshot(path="logs/test_one_before_add.png")
                    add_btn.click()
                    page.wait_for_load_state("networkidle")
                    logger.info(f"  ✓ 追加完了 | URL: {page.url}")
                    page.screenshot(path="logs/test_one_after_add.png")
                except PWTimeout:
                    logger.error("  ✗ 追加ボタンが見つかりません。SEL_ADD_BTN を確認してください。")
                    page.screenshot(path="logs/test_one_no_add_btn.png")
                    return

            logger.info("\n=== 完了 ===")
            logger.info("ブラウザはそのまま開いています。画面を確認してください。")
            try:
                input("Enterキーで終了...")
            except (EOFError, KeyboardInterrupt):
                pass

        except KeyboardInterrupt:
            logger.info("中断されました")
        finally:
            browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="追加ボタンは押さない")
    args = parser.parse_args()
    main(dry_run=args.dry_run)
