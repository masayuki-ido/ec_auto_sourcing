"""
カラー整合性チェック:
  管理画面が自動検出したカラーリストと画像から抽出した主要色を照合して補正する

NOTE: 管理画面のカラーリスト取得・更新のセレクタは実際のHTMLに合わせて調整してください。
"""
import logging
from playwright.sync_api import Page

from utils.color_detect import get_color_names_from_image

logger = logging.getLogger(__name__)

# ─── 要調整: カラー関連セレクタ ────────────────────────
# 管理画面が自動検出したカラーのチェックボックス/タグ一覧
SEL_COLOR_LIST     = '.color-list .color-item, [class*="color-tag"], input[name*="color"]'
# カラー名が入っているテキスト要素（チェックボックスのラベルなど）
SEL_COLOR_LABEL    = 'label, span, .color-name'
# カラー削除ボタン（チェックボックスのチェックを外す or 削除ボタン）
SEL_COLOR_DELETE   = 'input[type="checkbox"]'
# カラー追加ボタン/フォーム
SEL_COLOR_ADD_BTN  = 'button:has-text("色を追加"), .add-color-btn'
SEL_COLOR_ADD_INPUT = 'input[placeholder*="カラー"], input[name*="new_color"]'
# ─────────────────────────────────────────────────────


def sync_colors(page: Page, product: dict) -> dict:
    """
    管理画面のカラーリストを画像の実際の色に合わせて補正する。

    処理:
      1. 管理画面から現在のカラーリストを取得
      2. 画像から主要色を抽出してカラー名に変換
      3. 管理画面にあるが画像にない色 → チェックを外す / 削除
      4. 画像にあるが管理画面にない色 → 追加

    Args:
        page: ログイン済みの Playwright Page（商品詳細/編集ページが開いている状態）
        product: 商品辞書（image_bytes キーが必要）

    Returns:
        product に "synced_colors" キーを追加して返す
    """
    image_bytes = product.get("image_bytes")
    if not image_bytes:
        logger.warning(f"image_bytes が未設定: {product['name']}")
        return product

    # ── 1. 画像から色を抽出
    image_colors = get_color_names_from_image(image_bytes)
    logger.info(f"画像から検出したカラー: {image_colors}")

    # ── 2. 管理画面の現在カラーリストを取得
    admin_colors = _get_admin_colors(page)
    logger.info(f"管理画面のカラーリスト: {admin_colors}")

    # ── 3. 管理画面にあるが画像にない色 → 削除
    to_remove = [c for c in admin_colors if c not in image_colors]
    for color_name in to_remove:
        _remove_color(page, color_name)
        logger.info(f"カラー削除: {color_name}")

    # ── 4. 画像にあるが管理画面にない色 → 追加
    to_add = [c for c in image_colors if c not in admin_colors]
    for color_name in to_add:
        _add_color(page, color_name)
        logger.info(f"カラー追加: {color_name}")

    product["synced_colors"] = image_colors
    return product


def _get_admin_colors(page: Page) -> list[str]:
    """管理画面から現在設定されているカラー名リストを取得する。"""
    colors = []
    try:
        items = page.query_selector_all(SEL_COLOR_LIST)
        for item in items:
            label = item.query_selector(SEL_COLOR_LABEL)
            name = (label or item).inner_text().strip()
            if name:
                colors.append(name)
    except Exception as e:
        logger.warning(f"カラーリスト取得失敗: {e}")
    return colors


def _remove_color(page: Page, color_name: str) -> None:
    """管理画面からカラーを削除（チェックを外す）する。"""
    try:
        # チェックボックスのケース
        items = page.query_selector_all(SEL_COLOR_LIST)
        for item in items:
            label = item.query_selector(SEL_COLOR_LABEL)
            text = (label or item).inner_text().strip()
            if text == color_name:
                cb = item.query_selector(SEL_COLOR_DELETE)
                if cb:
                    if cb.is_checked():
                        cb.click()
                else:
                    # 削除ボタンがある場合
                    del_btn = item.query_selector('button[class*="delete"], button[class*="remove"]')
                    if del_btn:
                        del_btn.click()
                break
    except Exception as e:
        logger.warning(f"カラー削除失敗 [{color_name}]: {e}")


def _add_color(page: Page, color_name: str) -> None:
    """管理画面にカラーを追加する。"""
    try:
        add_btn = page.query_selector(SEL_COLOR_ADD_BTN)
        if add_btn:
            add_btn.click()
            page.wait_for_timeout(300)
        add_input = page.query_selector(SEL_COLOR_ADD_INPUT)
        if add_input:
            add_input.fill(color_name)
            page.keyboard.press("Enter")
        else:
            logger.warning(f"カラー追加フォームが見つかりません: {color_name}")
    except Exception as e:
        logger.warning(f"カラー追加失敗 [{color_name}]: {e}")
