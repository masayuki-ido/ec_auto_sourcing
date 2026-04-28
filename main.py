"""
ECサイト商品自動追加 メインスクリプト

実行方法:
    python main.py                  # 全キーワードで実行
    python main.py --keyword サコッシュ   # キーワード指定
    python main.py --dry-run        # 実際には追加せず確認のみ
"""
from __future__ import annotations
import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright

import config
from steps.login          import login
from steps.search         import navigate_to_search, search_products
from steps.filter_products import filter_products
from steps.filter_images  import filter_by_image
from steps.color_check    import sync_colors
from steps.category_select import select_category
from steps.add_product    import add_product

# ─── スクショ保存ヘルパ ────────────────────────────────
SHOT_DIR = config.LOGS_DIR / f"run_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
_shot_counter = {"n": 0}

def snap(page, label: str) -> None:
    _shot_counter["n"] += 1
    path = SHOT_DIR / f"{_shot_counter['n']:03d}_{label}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        logging.getLogger(__name__).info(f"[SHOT] {path}")
    except Exception as e:
        logging.getLogger(__name__).warning(f"スクショ失敗 {label}: {e}")

# ─── ログ設定 ────────────────────────────────────────────
def setup_logging() -> None:
    today = datetime.now().strftime("%Y-%m-%d")
    log_path = config.LOGS_DIR / f"{today}.log"

    fmt = "%(asctime)s [%(levelname)s] %(name)s - %(message)s"
    handlers = [
        logging.FileHandler(log_path, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(level=logging.INFO, format=fmt, handlers=handlers)


# ─── 追加済みID管理 ─────────────────────────────────────
def load_added_ids() -> set[str]:
    if config.ADDED_PRODUCTS_FILE.exists():
        with open(config.ADDED_PRODUCTS_FILE, encoding="utf-8") as f:
            return set(json.load(f))
    return set()


def save_added_ids(ids: set[str]) -> None:
    with open(config.ADDED_PRODUCTS_FILE, "w", encoding="utf-8") as f:
        json.dump(sorted(ids), f, ensure_ascii=False, indent=2)


# ─── メイン処理 ─────────────────────────────────────────
def run(keywords: list[str] | None = None, dry_run: bool = False) -> int:
    """
    商品自動追加を実行する。

    Args:
        keywords: 検索キーワードリスト（None の場合は config.SEARCH_KEYWORDS を使用）
        dry_run:  True の場合は管理画面への追加をスキップして確認のみ

    Returns:
        追加に成功した件数
    """
    setup_logging()
    logger = logging.getLogger(__name__)

    keywords  = keywords or config.SEARCH_KEYWORDS
    added_ids = load_added_ids()

    total_added      = 0
    consecutive_fail = 0
    FAIL_ALERT_COUNT = 3

    logger.info(f"=== 実行開始 | キーワード: {keywords} | 上限: {config.ADD_LIMIT}件 | dry_run={dry_run} ===")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=config.HEADLESS)
        page    = browser.new_page()

        try:
            # ── ログイン ──
            login(page)
            snap(page, "after_login")

            for keyword in keywords:
                if total_added >= config.ADD_LIMIT:
                    break

                # ── 検索 ──
                navigate_to_search(page)
                snap(page, f"search_page_{keyword}")
                products = search_products(page, keyword)
                snap(page, f"search_results_{keyword}")
                if not products:
                    logger.warning(f"「{keyword}」の検索結果が 0 件でした")
                    continue

                # ── 価格・画像フィルタ ──
                products = filter_products(products)

                # ── 画像OCR・サイズフィルタ ──
                products = filter_by_image(products)

                for product in products:
                    if total_added >= config.ADD_LIMIT:
                        break

                    prod_id = product.get("id", "")

                    # ── 重複チェック ──
                    if prod_id and prod_id in added_ids:
                        logger.debug(f"スキップ（追加済み）: {product['name']}")
                        continue

                    try:
                        # ── カテゴリ選択 ──
                        product = select_category(page, product)
                        snap(page, f"category_{total_added+1}")

                        # ── カラー整合性チェック ──
                        product = sync_colors(page, product)
                        snap(page, f"color_{total_added+1}")

                        # ── 商品追加 ──
                        if dry_run:
                            logger.info(f"[DRY-RUN] 追加予定: {product['name']} ({product['price']}円)")
                            success = True
                        else:
                            success = add_product(page, product)
                            snap(page, f"added_{total_added+1}")

                        if success:
                            total_added += 1
                            consecutive_fail = 0
                            if prod_id:
                                added_ids.add(prod_id)
                            save_added_ids(added_ids)
                        else:
                            consecutive_fail += 1
                            _check_consecutive_failures(consecutive_fail, FAIL_ALERT_COUNT)

                    except Exception as e:
                        logger.error(f"商品処理中にエラー（スキップ）: {product.get('name')} | {e}")
                        consecutive_fail += 1
                        _check_consecutive_failures(consecutive_fail, FAIL_ALERT_COUNT)

        except RuntimeError as e:
            logger.critical(f"致命的エラーにより終了: {e}")
            try:
                snap(page, "fatal_error")
            except Exception:
                pass
        finally:
            browser.close()

    logger.info(f"=== 実行完了 | 追加件数: {total_added} 件 ===")
    return total_added


def _check_consecutive_failures(count: int, threshold: int) -> None:
    """連続失敗が閾値を超えたら目立つアラートを出力する。"""
    if count >= threshold:
        msg = (
            "\n" + "!" * 60 + "\n"
            f"  警告: 追加失敗が {count} 件連続しています。\n"
            "  管理画面の状態・セレクタ・ネットワークを確認してください。\n"
            + "!" * 60
        )
        logging.getLogger(__name__).warning(msg)
        print(msg, file=sys.stderr)


# ─── CLI エントリポイント ────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="EC商品自動追加ツール")
    parser.add_argument("--keyword", nargs="+", help="検索キーワード（複数指定可）")
    parser.add_argument("--dry-run", action="store_true", help="実際には追加しない確認モード")

    # 個別ステップのテスト用
    parser.add_argument("--step", choices=["login", "search", "filter", "image", "color", "category"],
                        help="指定したステップのみ単体実行")

    args = parser.parse_args()

    if args.step:
        _run_single_step(args.step, args.keyword)
    else:
        run(keywords=args.keyword, dry_run=args.dry_run)


def _run_single_step(step: str, keywords: list[str] | None) -> None:
    """個別ステップの単体テスト実行。"""
    setup_logging()
    kw = (keywords or config.SEARCH_KEYWORDS)[0]

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=config.HEADLESS)
        page    = browser.new_page()
        try:
            login(page)
            if step == "login":
                print("[OK] ログイン成功")
                return
            navigate_to_search(page)
            products = search_products(page, kw)
            if step == "search":
                print(f"[OK] 検索結果 {len(products)} 件")
                for p in products[:5]: print(" ", p["name"], p["price"])
                return
            products = filter_products(products)
            if step == "filter":
                print(f"[OK] 価格フィルタ後 {len(products)} 件")
                return
            products = filter_by_image(products)
            if step == "image":
                print(f"[OK] 画像フィルタ後 {len(products)} 件")
                return
            if products:
                p = products[0]
                if step == "color":
                    p = sync_colors(page, p)
                    print(f"[OK] カラー同期: {p.get('synced_colors')}")
                elif step == "category":
                    p = select_category(page, p)
                    print(f"[OK] カテゴリ: {p.get('category')}")
        finally:
            browser.close()
