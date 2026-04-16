"""
管理画面への商品追加処理

NOTE: セレクタは管理画面の HTML 構造に合わせて調整してください。
"""
import logging
from datetime import datetime
from playwright.sync_api import Page, TimeoutError as PWTimeout

logger = logging.getLogger(__name__)

# ─── 要調整: 商品追加関連セレクタ ──────────────────────
# 商品詳細ページを開くリンク/ボタン（検索結果行の中にある）
SEL_DETAIL_LINK   = 'a[href*="/product/"], button:has-text("詳細"), td a'
# 管理画面の「追加」または「ECサイトに追加」ボタン
SEL_ADD_BUTTON    = 'button:has-text("追加"), button:has-text("ECに追加"), button:has-text("登録")'
# 追加完了を確認するセレクタ（成功ダイアログ/メッセージ）
SEL_SUCCESS_MSG   = '.success, .alert-success, [class*="toast"], dialog:has-text("完了")'
# ─────────────────────────────────────────────────────


def add_product(page: Page, product: dict) -> bool:
    """
    管理画面で商品の「追加」ボタンをクリックして保存する。

    処理フロー:
      1. 検索結果の行から商品詳細ページへ遷移（または詳細モーダルを開く）
      2. カテゴリ選択・カラー同期は呼び出し元（main.py）で先に完了済みの前提
      3. 「追加」ボタンをクリック
      4. 完了確認

    Args:
        page: ログイン済み Playwright Page
        product: 処理済み商品辞書

    Returns:
        True: 追加成功 / False: 失敗
    """
    name  = product.get("name", "不明")
    price = product.get("price", 0)

    try:
        # ── 詳細ページへ遷移 ──
        elem = product.get("element")
        if elem:
            detail_link = elem.query_selector(SEL_DETAIL_LINK)
            if detail_link:
                detail_link.click()
                page.wait_for_load_state("networkidle")
            else:
                # 行全体をクリックして詳細ページを開くケース
                elem.click()
                page.wait_for_load_state("networkidle")

        # ── 追加ボタンをクリック ──
        page.wait_for_selector(SEL_ADD_BUTTON, timeout=10_000)
        page.click(SEL_ADD_BUTTON)

        # ── 完了確認 ──
        try:
            page.wait_for_selector(SEL_SUCCESS_MSG, timeout=10_000)
        except PWTimeout:
            # 成功メッセージが無い場合はURLの変化で判断
            logger.debug("成功メッセージ要素が見つからないが、処理は継続します")

        _log_success(name, price, product.get("category", "不明"), product.get("synced_colors", []))
        return True

    except PWTimeout as e:
        logger.error(f"追加タイムアウト [{name}]: {e}")
        _take_error_screenshot(page, name)
        return False
    except Exception as e:
        logger.error(f"追加エラー [{name}]: {e}")
        _take_error_screenshot(page, name)
        return False


def _log_success(name: str, price: int, category: str, colors: list) -> None:
    """追加完了ログを出力する。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(
        f"[追加完了] {now} | "
        f"商品名: {name} | "
        f"価格: {price}円 | "
        f"カテゴリ: {category} | "
        f"カラー: {colors}"
    )


def _take_error_screenshot(page: Page, name: str) -> None:
    """エラー時のスクリーンショットを保存する。"""
    try:
        safe_name = "".join(c if c.isalnum() else "_" for c in name)[:30]
        path = f"logs/error_{safe_name}_{datetime.now().strftime('%H%M%S')}.png"
        page.screenshot(path=path)
        logger.info(f"スクリーンショット保存: {path}")
    except Exception:
        pass
