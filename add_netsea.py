"""
Netseaキーワード検索で商品を追加するスクリプト

管理画面の「商品をNetseaから検索(推奨)」を使い、
キーワード検索で見つかった商品を追加する。

実行方法:
    python add_netsea.py
    python add_netsea.py --dry-run
    python add_netsea.py --count 3
    python add_netsea.py --keyword レザーサコッシュ
"""
import argparse, logging, re, sys, csv, time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import ADMIN_USER, ADMIN_PASS, HEADLESS
import os
from datetime import datetime

LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"
SEARCH_URL = f"{BASE}/item/search"
ITEM_LIST_URL = f"{BASE}/item"
CSV_DIR = Path("data"); CSV_DIR.mkdir(exist_ok=True)

SHOT_DIR = LOGS / f"netsea_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
SHOT_DIR.mkdir(parents=True, exist_ok=True)
_shot_counter = {"n": 0}
_AUTO = os.getenv("AUTO", "0") == "1"

def snap(page, label: str) -> None:
    _shot_counter["n"] += 1
    path = SHOT_DIR / f"{_shot_counter['n']:03d}_{label}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
        logger.info(f"[SHOT] {path}")
    except Exception as e:
        logger.warning(f"スクショ失敗 {label}: {e}")

# カテゴリ自動判定マッピング（商品名・説明のキーワード → カテゴリvalue）
CATEGORY_KEYWORDS = {
    "レザー": "4",     # レザーサコッシュ
    "革":     "4",
    "本革":   "4",
    "合皮":   "1",     # レザー
    "PUレザー": "1",
    "メッシュ": "8",
    "帆布":   "2",     # キャンバス（帆布）
    "キャンバス": "2",
    "コットン": "5",
    "綿":     "5",
    "防水":   "6",
    "撥水":   "6",
    "ナイロン": "3",
    "クリア": "7",
    "透明":   "7",
    "PVC":    "7",
}
DEFAULT_CATEGORY = "3"  # ナイロン（デフォルト）


def login(page) -> None:
    """管理画面にログイン"""
    logger.info("ログイン中...")
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.fill('input[name="email"]', ADMIN_USER)
    page.fill('input[name="password"]', ADMIN_PASS)
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: "login" not in url, timeout=15_000)
    logger.info("ログイン成功")


def download_and_load_csv(page) -> set:
    """
    管理画面から最新CSVをダウンロードして、supplier_urlを読み込む。
    手順: 商品一覧 → CSVエクスポート → モーダル内「商品データを全てCSVにエクスポート」
         横のボタン（1番目）をクリック → Playwrightのdownloadイベントで受信
    """
    logger.info("最新CSVをダウンロード中...")
    page.goto(ITEM_LIST_URL, wait_until="networkidle")
    page.wait_for_timeout(3000)

    # 1. 「CSVエクスポート」ボタンをクリック → モーダル表示
    try:
        csv_btn = page.locator('button:has-text("CSVエクスポート")').first
        csv_btn.wait_for(state="visible", timeout=15_000)
        csv_btn.click(timeout=10_000)
        logger.info("  CSVエクスポートボタンをクリック")
        page.wait_for_timeout(1500)
    except Exception as e:
        logger.warning(f"  CSVエクスポートボタンクリック失敗: {e}")
        return set()

    # 2. モーダル内の「商品データを全てCSVにエクスポート」横のボタン（1番目）をクリック
    #    2番目は「商品購入オプションデータ」で別物なので使わない。
    try:
        page.locator('text=商品データを全てCSVにエクスポート').wait_for(timeout=5_000)
        modal_btns = page.locator(
            '[role="dialog"][data-state="open"] button:has-text("CSVエクスポート")'
        ).all()
        if not modal_btns:
            logger.warning("  モーダル内にCSVエクスポートボタンなし")
            page.keyboard.press("Escape")
            return set()

        # 1番目の「CSVエクスポート」 = 商品データ本体
        target_btn = modal_btns[0]
        download_path = Path.home() / "Downloads" / "item_sacoche-sacolla.csv"
        try:
            with page.expect_download(timeout=60_000) as dl_info:
                target_btn.click()
                logger.info("  モーダル内「商品データ」CSVエクスポートをクリック")
            download = dl_info.value
            download.save_as(str(download_path))
            logger.info(f"  CSVダウンロード完了: {download_path} ({download_path.stat().st_size} bytes)")
        except Exception as e:
            logger.warning(f"  ダウンロード失敗: {e}")
            page.keyboard.press("Escape")
            return set()
    except Exception as e:
        logger.warning(f"  モーダル操作失敗: {e}")
        page.keyboard.press("Escape")
        return set()

    # モーダルを閉じる
    try:
        page.keyboard.press("Escape")
        page.wait_for_timeout(500)
    except Exception:
        pass

    return _load_urls_from_csv(download_path)


def _load_urls_from_csv(csv_path: Path) -> set:
    """CSVからsupplier_urlを読み込み"""
    urls = set()
    try:
        with open(csv_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                u = (row.get('supplier_url') or '').strip()
                if u:
                    urls.add(u)
        logger.info(f"  既存supplier_url: {len(urls)}件 (from {csv_path.name})")
    except Exception as e:
        logger.warning(f"  CSV読み込みエラー: {e}")
    return urls


def detect_category(name: str, description: str) -> str:
    """商品名と説明からカテゴリを自動判定"""
    text = f"{name} {description}".lower()
    for keyword, cat_value in CATEGORY_KEYWORDS.items():
        if keyword.lower() in text:
            logger.info(f"  カテゴリ自動判定: 「{keyword}」→ value={cat_value}")
            return cat_value
    logger.info(f"  カテゴリ自動判定: デフォルト（ナイロン）")
    return DEFAULT_CATEGORY


def search_netsea(page, keyword: str) -> None:
    """Netsea検索を実行"""
    logger.info(f"Netsea検索: 「{keyword}」")
    page.goto(SEARCH_URL, wait_until="networkidle")
    page.wait_for_timeout(1500)

    # 検索モードを「Netseaから検索(推奨)」に変更
    page.select_option("select", value="netsea2")
    page.wait_for_timeout(1000)

    # キーワード入力
    keyword_input = page.locator('input[placeholder*="フリーワード"]')
    keyword_input.fill(keyword)
    page.wait_for_timeout(300)

    # 検索ボタンクリック
    page.locator('button:has-text("検索")').click()
    logger.info("  検索実行中...")

    # 結果を待つ
    try:
        page.locator('text=商品追加に進む').first.wait_for(timeout=30_000)
        logger.info("  検索結果が表示されました")
    except PWTimeout:
        logger.warning("  検索結果が表示されませんでした（タイムアウト）")


def get_product_cards(page) -> list:
    """検索結果の商品カードから「商品追加に進む」リンクを取得"""
    links = page.locator('text=商品追加に進む').all()
    logger.info(f"  商品カード数: {len(links)}")
    return links


def close_modal(page) -> None:
    """モーダルを確実に閉じる（Radix UI対応）"""
    for _ in range(3):
        try:
            dialog = page.locator('[role="dialog"]')
            if dialog.count() > 0:
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)
            else:
                break
        except Exception:
            page.keyboard.press("Escape")
            page.wait_for_timeout(800)

    # Radix UIのオーバーレイをJSで強制削除
    try:
        page.evaluate("""
            () => {
                // data-state="closed" のダイアログとオーバーレイを削除
                document.querySelectorAll('[role="dialog"]').forEach(el => el.remove());
                document.querySelectorAll('[data-aria-hidden="true"]').forEach(el => el.remove());
                document.querySelectorAll('.fixed.inset-0.z-50').forEach(el => el.remove());
            }
        """)
    except Exception:
        pass
    page.wait_for_timeout(500)


def add_single_product(page, card_link, existing_urls: set, existing_names: set, session_tried: set, dry_run: bool) -> bool:
    """1つの商品を追加する"""
    # まず既存のモーダルが開いていたら閉じる
    close_modal(page)

    try:
        # 「商品追加に進む」をクリック
        card_link.click(timeout=10_000)
        page.wait_for_timeout(2000)
    except Exception as e:
        logger.warning(f"  カードクリック失敗: {e}")
        close_modal(page)
        return False

    # モーダルが表示されるのを待つ
    try:
        page.locator('[role="dialog"][data-state="open"]').wait_for(timeout=10_000)
        page.wait_for_timeout(1000)
    except PWTimeout:
        logger.warning("  モーダル表示タイムアウト")
        close_modal(page)
        return False

    modal = page.locator('[role="dialog"][data-state="open"]')

    # 商品URLを取得（重複チェック用）
    try:
        url_input = modal.locator('input[value*="netsea"]').first
        product_url = url_input.input_value().strip()
    except Exception:
        product_url = ""

    if product_url and (product_url in existing_urls or product_url in session_tried):
        logger.info(f"  既知URL → スキップ: {product_url[:60]}")
        close_modal(page)
        return False

    if product_url:
        session_tried.add(product_url)

    # 商品名を取得（モーダル内のinput）
    try:
        inputs = modal.locator('input').all()
        product_name = ""
        for inp in inputs:
            val = inp.input_value()
            if val and "netsea" not in val and len(val) > 3:
                product_name = val
                break
        if not product_name:
            product_name = "不明"
    except Exception:
        product_name = "不明"

    # 商品名での重複チェック
    if product_name in existing_names:
        logger.info(f"  既知商品名 → スキップ: {product_name[:50]}")
        close_modal(page)
        return False

    # 商品説明を取得
    try:
        description = modal.locator('textarea').first.input_value().strip()
    except Exception:
        description = ""

    logger.info(f"  商品: {product_name[:50]}")
    logger.info(f"  URL: {product_url[:60]}")

    if dry_run:
        logger.info(f"  [DRY-RUN] 追加スキップ")
        close_modal(page)
        return True

    # カテゴリを自動選択（モーダル内の最初のselect = カテゴリ）
    cat_value = detect_category(product_name, description)
    try:
        cat_select = modal.locator('select').nth(0)
        cat_select.select_option(value=cat_value)
        logger.info(f"  カテゴリ選択: value={cat_value}")
        page.wait_for_timeout(500)
    except Exception as e:
        logger.warning(f"  カテゴリ選択失敗: {e}")

    # 配達情報を選択（モーダル内の2つ目のselect）
    delivery_value = os.getenv(
        "DELIVERY_OPTION",
        "ご注文確定から3~7日でお届け予定"
    )
    try:
        delivery_select = modal.locator('select').nth(1)
        delivery_select.select_option(value=delivery_value)
        logger.info(f"  配達情報選択: {delivery_value}")
        page.wait_for_timeout(500)
    except Exception as e:
        logger.warning(f"  配達情報選択失敗: {e}")

    # 「商品を追加」ボタンをクリック
    try:
        add_btn = modal.locator('button:has-text("商品を追加")').first
        add_btn.scroll_into_view_if_needed()
        page.wait_for_timeout(300)
        add_btn.click(timeout=10_000)
        logger.info("  「商品を追加」をクリック")
    except Exception as e:
        logger.warning(f"  追加ボタンクリック失敗: {e}")
        close_modal(page)
        return False

    # 完了シグナルを待つ（最大60秒）
    # モーダルが閉じる / ボタンがdisabledになる / トーストが出る のいずれか
    deadline = 60_000
    start = 0
    poll = 1_000
    success = False
    while start < deadline:
        page.wait_for_timeout(poll)
        start += poll
        try:
            # モーダルが閉じた
            if not page.locator('[role="dialog"]').first.is_visible():
                logger.info(f"  モーダル消失 @ {start/1000:.0f}秒 → 追加完了")
                success = True
                break
            # ボタンがdisabledに
            if modal.locator('button:has-text("商品を追加")').first.is_disabled():
                logger.info(f"  追加ボタンdisabled @ {start/1000:.0f}秒")
            # モーダル内に完了メッセージ
            modal_text = modal.inner_text()[:500]
            if any(kw in modal_text for kw in ["追加されました", "追加完了", "successfully", "登録しました"]):
                logger.info(f"  成功メッセージ検出 @ {start/1000:.0f}秒")
                success = True
                break
        except Exception:
            # dialog消失時の例外を成功と見なす
            logger.info(f"  dialog操作失敗（消失済み）@ {start/1000:.0f}秒 → 追加完了")
            success = True
            break

    if not success:
        logger.warning(f"  完了シグナルを{deadline/1000:.0f}秒以内に検出できず")
        # 最後のモーダル状態をスクショに記録
        try:
            snap(page, f"no_complete_signal")
        except Exception:
            pass
        close_modal(page)
        return False

    logger.info(f"  ✓ 追加成功: {product_name[:50]}")
    if product_url:
        existing_urls.add(product_url)

    # モーダルを閉じる（まだ開いていれば）
    close_modal(page)
    return True


def main():
    parser = argparse.ArgumentParser(description="Netsea検索で商品追加")
    parser.add_argument("--dry-run", action="store_true", help="実際には追加しない確認モード")
    parser.add_argument("--count", type=int, default=2, help="追加する商品数")
    parser.add_argument("--keyword", default="サコッシュ", help="検索キーワード")
    args = parser.parse_args()

    logger.info(f"=== add_netsea.py 開始 | keyword={args.keyword} | dry_run={args.dry_run} | 目標={args.count}件 ===")

    session_tried: set = set()
    added_count = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=HEADLESS)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            accept_downloads=True,
        )
        page = ctx.new_page()

        try:
            login(page)
            snap(page, "after_login")

            # 最新CSVをダウンロードして重複チェック
            if os.getenv("SKIP_CSV", "0") == "1":
                logger.info("SKIP_CSV=1: CSVダウンロードをスキップ")
                existing_urls = set()
            else:
                existing_urls = download_and_load_csv(page)
            existing_names = set()  # 商品名重複チェック用

            search_netsea(page, args.keyword)
            snap(page, f"search_{args.keyword}")

            page_num = 1
            card_idx = 0  # 現在のカードインデックス

            while added_count < args.count:
                logger.info(f"\n--- ページ {page_num} / カード {card_idx + 1} ---")

                # 商品カードを毎回再取得（モーダル操作後にDOMが変わる）
                card_links = get_product_cards(page)

                if not card_links or card_idx >= len(card_links):
                    # 次ページへ
                    try:
                        next_btn = page.locator('button:has-text("次のページ")')
                        if next_btn.is_visible() and next_btn.is_enabled():
                            next_btn.click()
                            page.wait_for_timeout(3000)
                            page_num += 1
                            card_idx = 0
                            continue
                        else:
                            logger.info("  全ページを処理しました")
                            break
                    except Exception:
                        logger.info("  次ページへの遷移に失敗")
                        break

                link = card_links[card_idx]
                card_idx += 1

                logger.info(f"  [{card_idx}/{len(card_links)}] 商品確認中...")
                try:
                    success = add_single_product(page, link, existing_urls, existing_names, session_tried, args.dry_run)
                    if success:
                        added_count += 1
                        logger.info(f"  ✓✓✓ {added_count}/{args.count}件 追加完了")
                        snap(page, f"added_{added_count:02d}")
                except Exception as e:
                    logger.warning(f"  商品処理エラー: {e}")
                    close_modal(page)

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            try:
                page.screenshot(path="logs/netsea_unexpected_error.png")
            except Exception:
                pass

        finally:
            logger.info(f"\n{'='*50}")
            logger.info(f"完了: {added_count}/{args.count}件 追加しました")
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
