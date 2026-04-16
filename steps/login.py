"""
管理画面へのログイン処理

NOTE: 実際のセレクタは管理画面の HTML を確認して書き換えてください。
      ブラウザで右クリック→「検証」→該当要素をコピー。
"""
import logging
from playwright.sync_api import Page, TimeoutError as PWTimeout
from config import ADMIN_URL, ADMIN_USER, ADMIN_PASS

logger = logging.getLogger(__name__)

# ─── 要調整: 管理画面のセレクタ ────────────────────────
SEL_USERNAME = 'input[name="email"]'        # ログインIDフィールド
SEL_PASSWORD = 'input[name="password"]'     # パスワードフィールド
SEL_SUBMIT   = 'button[type="submit"]'      # ログインボタン
# ログイン成功を判断する要素（ダッシュボードに固有の要素）
SEL_AFTER_LOGIN = 'nav, .dashboard, .sidebar, [class*="admin"]'
# ─────────────────────────────────────────────────────


def login(page: Page) -> None:
    """
    管理画面にログインする。
    失敗時は RuntimeError を送出。

    Args:
        page: Playwright の Page オブジェクト（呼び出し元で生成済みのもの）
    """
    if not ADMIN_USER or not ADMIN_PASS:
        raise RuntimeError(".env に ADMIN_USER / ADMIN_PASS が設定されていません。")

    logger.info(f"管理画面へアクセス: {ADMIN_URL}")
    page.goto(ADMIN_URL, wait_until="networkidle")

    try:
        page.fill(SEL_USERNAME, ADMIN_USER)
        page.fill(SEL_PASSWORD, ADMIN_PASS)
        page.click(SEL_SUBMIT)

        # ─── ログイン後の画面遷移を待つ ─────────────
        page.wait_for_selector(SEL_AFTER_LOGIN, timeout=15_000)
        logger.info("ログイン成功")

    except PWTimeout:
        page.screenshot(path="logs/login_failed.png")
        raise RuntimeError(
            "ログインに失敗しました（タイムアウト）。"
            "セレクタまたはURL・認証情報を確認してください。"
            "スクリーンショット: logs/login_failed.png"
        )
    except Exception as e:
        page.screenshot(path="logs/login_error.png")
        raise RuntimeError(f"ログイン中に予期しないエラー: {e}")


# ─── 単体テスト ─────────────────────────────────────────
if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
    from playwright.sync_api import sync_playwright
    from config import HEADLESS

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        page = browser.new_page()
        try:
            login(page)
            print("ログイン成功！現在のURL:", page.url)
        except RuntimeError as e:
            print(f"[ERROR] {e}", file=sys.stderr)
        finally:
            browser.close()
