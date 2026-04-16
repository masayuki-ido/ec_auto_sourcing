"""
商品一覧と重複しない商品を最大N件追加するスクリプト

改善点:
  - セッション内で試みたsupplier_urlを記録 → 同じ商品を繰り返さない
  - 検索ごとに別の画像URLを使う
  - EasyOCR + PIL で中国語・空白画像をフィルタリング
  - サイズ画像も適切に選択する

実行方法:
    python add_five.py
    python add_five.py --dry-run
    python add_five.py --count 3
    python add_five.py --csv /path/to/items.csv
"""
import argparse, logging, re, sys, csv, time
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
LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"
DEFAULT_CSV = Path.home() / "Downloads" / "item_sacoche-sacolla.csv"

# ─── 検索に使う画像URL（多様な素材・毎回ローテーション） ───
SEARCH_IMAGE_URLS = [
    "https://fulmo-img-server.com/sacoche-sacolla/788f2d22-0fb6-43b9-bb9e-7cd8d2ffdf26.jpg",
    "https://g-search1.alicdn.com/img/bao/uploaded/i4/i1/1049653664/O1CN01iPes6U1cw9q46zYvI_!!0-item_pic.jpg",
    "https://g-search3.alicdn.com/img/bao/uploaded/i4/i2/2207984893161/O1CN01mO1jkz1MoApCiKNvP_!!2207984893161-0-lubanu-s.jpg",
    "https://g-search2.alicdn.com/img/bao/uploaded/i4/i2/3481871984/O1CN01bQhGjE23kCTw5XEDF_!!3481871984-0-lubanu-s.jpg",
    "https://g-search2.alicdn.com/img/bao/uploaded/i4/i1/2207991009063/O1CN01q9b2fU24vvWPQg4pt_!!2207991009063-0-lubanu-s.jpg",
    "https://g-search3.alicdn.com/img/bao/uploaded/i4/i2/2206732831278/O1CN01P3JvYB22hJxODi8OM_!!2206732831278-0-lubanu-s.jpg",
    "https://fulmo-img-server.com/sacoche-sacolla/7be920cacd3944409004d524bc4df2cd.jepg",
    "https://fulmo-img-server.com/sacoche-sacolla/d6a784c84e304707bda7ad073ea31171.jepg",
    "https://fulmo-img-server.com/sacoche-sacolla/ad8c94fe5bea4b16b0c3efb7e63b8946.jepg",
]

CATEGORY_ORDER = [
    "ナイロン", "キャンバス", "コットン", "レザーサコッシュ",
    "防水", "メッシュ", "レザー", "クリア",
]

PRODUCT_VARIANTS = [
    {"concept": "軽量で使いやすい、毎日のお出かけにぴったりのサコッシュ",
     "color": "ブラック, ネイビー, ベージュ", "size": "縦15cm × 横25cm × マチ3cm"},
    {"concept": "シンプルなデザインで、コーデを選ばないミニショルダーバッグ",
     "color": "ブラック, グレー, カーキ", "size": "縦16cm × 横24cm × マチ4cm"},
    {"concept": "アウトドアにも街歩きにも対応する多機能サコッシュ",
     "color": "ブラック, ネイビー, グリーン", "size": "縦14cm × 横23cm × マチ3cm"},
    {"concept": "スポーティでカジュアルなデイリーサコッシュバッグ",
     "color": "ブラック, ホワイト, レッド", "size": "縦15cm × 横22cm × マチ3cm"},
    {"concept": "旅行やショッピングに便利な大容量スリムサコッシュ",
     "color": "ブラウン, ベージュ, ブラック", "size": "縦17cm × 横27cm × マチ5cm"},
    {"concept": "軽やかなカジュアルスタイルに映えるコンパクトサコッシュ",
     "color": "ピンク, ベージュ, ブルー", "size": "縦14cm × 横22cm × マチ3cm"},
    {"concept": "シーンを選ばないオールマイティなショルダーポーチ",
     "color": "ブラック, グレー, ネイビー", "size": "縦16cm × 横25cm × マチ4cm"},
]

# ─── EasyOCR（遅延ロード・1回だけ初期化） ──────────────────
_ocr_reader = None
def get_ocr_reader():
    global _ocr_reader
    if _ocr_reader is None:
        import easyocr
        logger.info("EasyOCRモデルをロード中（初回のみ時間がかかります）...")
        _ocr_reader = easyocr.Reader(['ch_sim'], gpu=False, verbose=False)
        logger.info("EasyOCRロード完了")
    return _ocr_reader

# ─── 画像フィルタリング ──────────────────────────────────────
_img_cache: dict[str, bool] = {}  # URL → True=使用可, False=除外

def is_usable_image(img_url: str) -> bool:
    """
    True: 使用OK
    False: 除外（空白画像 or 中国語/韓国語テキストあり）
    """
    if img_url in _img_cache:
        return _img_cache[img_url]

    result = True
    try:
        resp = requests.get(img_url, timeout=6)
        img = Image.open(BytesIO(resp.content)).convert('RGB')
        arr = np.array(img.resize((300, 300)))

        # ── 空白チェック ──
        if arr.mean() > 245 or arr.var() < 50:
            logger.debug(f"  画像除外（空白）: {img_url[-40:]}")
            result = False
        else:
            # ── 中国語テキストチェック ──
            reader = get_ocr_reader()
            detections = reader.readtext(arr, detail=1)
            for (bbox, text, conf) in detections:
                if conf > 0.55 and len(text) >= 2:
                    cjk   = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
                    hira  = sum(1 for c in text if '\u3040' <= c <= '\u309f')
                    kana  = sum(1 for c in text if '\u30a0' <= c <= '\u30ff')
                    # 漢字のみで、ひらがな・カタカナが一切ない → 中国語と判定
                    if cjk >= 2 and hira == 0 and kana == 0:
                        logger.debug(f"  画像除外（中国語テキスト: 「{text}」 conf={conf:.2f}）: {img_url[-40:]}")
                        result = False
                        break
    except Exception as e:
        logger.debug(f"  画像チェック失敗（スキップ）: {e}")
        result = True  # 判定できなければ使用

    _img_cache[img_url] = result
    return result


def get_slide_img_urls(page, modal) -> list[str]:
    """カルーセル内の各スライドの画像URLをリストで返す"""
    urls = []
    try:
        imgs = modal.locator('img').all()
        for img in imgs:
            src = img.get_attribute('src') or img.get_attribute('data-src') or ''
            if src and src.startswith('http') and src not in urls:
                urls.append(src)
    except Exception:
        pass
    return urls


def load_existing_urls(csv_path: Path) -> set:
    urls = set()
    if not csv_path.exists():
        logger.warning(f"CSVが見つかりません: {csv_path}")
        return urls
    try:
        with open(csv_path, newline='', encoding='utf-8') as f:
            for row in csv.DictReader(f):
                u = (row.get('supplier_url') or '').strip().replace('.html', '.htm')
                if u:
                    urls.add(u)
        logger.info(f"既存supplier_url: {len(urls)}件")
    except Exception as e:
        logger.warning(f"CSV読み込みエラー: {e}")
    return urls


def login(page) -> None:
    logger.info("ログイン中...")
    page.goto(f"{BASE}/login", wait_until="domcontentloaded")
    page.wait_for_timeout(1000)
    page.fill('input[name="email"]', ADMIN_USER)
    page.fill('input[name="password"]', ADMIN_PASS)
    page.click('button[type="submit"]')
    page.wait_for_url(lambda url: "login" not in url, timeout=15_000)
    logger.info("ログイン成功")


def search_products(page, image_url: str) -> bool:
    page.goto(f"{BASE}/item/search", wait_until="networkidle")
    page.wait_for_timeout(1000)
    page.select_option("select", value="image")
    page.wait_for_timeout(500)
    page.fill('input[placeholder*="URL"]', image_url)
    page.click('button:has-text("検索")')
    logger.info(f"  検索中: {image_url[:70]}...")
    try:
        page.wait_for_selector('button:has-text("詳細を見る")', timeout=30_000)
        return True
    except PWTimeout:
        logger.warning("  検索タイムアウト")
        return False


def get_modal_supplier_url(page) -> str:
    try:
        modal = page.locator('[role="dialog"]')
        links = modal.locator('a[href*="1688.com"], a[href*="taobao.com"]').all()
        for link in links:
            href = (link.get_attribute("href") or '').replace('.html', '.htm').strip()
            if href:
                return href
    except Exception:
        pass
    return ""


def select_images_for_product(page, modal) -> None:
    """
    スライド画像をフィルタリングして選択:
      - 商品画像: フィルタ通過した最初の5枚
      - サイズ画像: フィルタ通過した末尾2枚
    """
    product_btns = modal.locator('button:has-text("商品画像に追加")').all()
    size_btns    = modal.locator('button:has-text("サイズ画像に追加")').all()
    img_urls     = get_slide_img_urls(page, modal)
    total        = len(product_btns)

    logger.info(f"  スライド数: {total}  取得画像URL数: {len(img_urls)}")

    # フィルタ結果を記録（URL取得できた分だけ）
    usable_indices = []
    for idx in range(total):
        if idx < len(img_urls):
            ok = is_usable_image(img_urls[idx])
            status = "OK" if ok else "NG"
            logger.info(f"    [{idx}] {status}  {img_urls[idx][-50:]}")
        else:
            ok = True  # URLが取得できなければデフォルト使用
        if ok:
            usable_indices.append(idx)

    if not usable_indices:
        logger.warning("  フィルタ通過画像なし → 全画像を使用")
        usable_indices = list(range(total))

    # 商品画像: 先頭から最大5枚
    product_indices = usable_indices[:5]
    for idx in product_indices:
        try:
            product_btns[idx].click()
            page.wait_for_timeout(250)
        except Exception:
            pass
    logger.info(f"  商品画像を追加: {product_indices}")

    # サイズ画像: 末尾から2枚（商品画像と重複してもOK）
    size_indices = usable_indices[-2:] if len(usable_indices) >= 2 else usable_indices
    for idx in size_indices:
        try:
            size_btns[idx].click()
            page.wait_for_timeout(250)
        except Exception:
            pass
    logger.info(f"  サイズ画像を追加: {size_indices}")

    page.wait_for_timeout(600)


def try_add_product(page, concept: str, color: str, size: str, dry_run: bool) -> tuple[bool, str]:
    """モーダルを埋めて追加。カテゴリは変えながら試みる。"""
    modal = page.locator('[role="dialog"]')

    # カテゴリ取得
    try:
        cat_select = modal.locator("select").first
        options = cat_select.locator("option").all()
        available_cats = [(o.get_attribute("value"), o.inner_text().strip())
                          for o in options if o.get_attribute("value")]
        logger.info(f"  カテゴリ: {[t for _, t in available_cats]}")
    except Exception as e:
        return False, f"カテゴリ取得失敗: {e}"

    cats_to_try = []
    for name in CATEGORY_ORDER:
        for val, text in available_cats:
            if name in text or text in name:
                cats_to_try.append((val, text))
                break
    for val, text in available_cats:
        if not any(v == val for v, _ in cats_to_try):
            cats_to_try.append((val, text))

    for cat_val, cat_text in cats_to_try:
        # モーダル存在確認
        try:
            if not modal.is_visible():
                return True, "モーダル自動クローズ（追加完了）"
        except Exception:
            return True, "モーダル消失（追加完了）"

        logger.info(f"  カテゴリ「{cat_text}」で試みます")

        try:
            cat_select.select_option(value=cat_val)
            page.wait_for_timeout(400)
        except Exception:
            return True, "カテゴリ選択中にモーダルが閉じた（追加完了の可能性）"

        try:
            modal.locator('input[placeholder="商品のコンセプトを入力"]').fill(concept)
        except Exception:
            pass
        try:
            modal.locator('input[placeholder="カラー情報"]').fill(color)
        except Exception:
            pass
        try:
            modal.locator('input[placeholder="サイズ情報"]').fill(size)
        except Exception:
            pass

        # 画像選択（フィルタリング付き）
        select_images_for_product(page, modal)

        if dry_run:
            return True, f"DRY-RUN: {cat_text}"

        try:
            add_btn = modal.locator('button:has-text("この商品をTaobaoからサイトに追加")')
            add_btn.wait_for(timeout=5_000)
            if add_btn.is_disabled():
                logger.info("  追加ボタンdisabled → 次のカテゴリへ")
                continue

            add_btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            add_btn.click()
            page.wait_for_timeout(8_000)

            # 成功判定
            try:
                modal_text = modal.inner_text()
            except Exception:
                logger.info(f"  ✓ 追加成功（モーダル消失）カテゴリ={cat_text}")
                return True, cat_text

            if any(kw in modal_text for kw in ["正常に追加されました", "追加されました", "successfully added"]):
                logger.info(f"  ✓ 追加成功（成功メッセージ）カテゴリ={cat_text}")
                page.wait_for_timeout(2_000)
                return True, cat_text

            try:
                page.locator('[role="dialog"]').wait_for(state="hidden", timeout=5_000)
                logger.info(f"  ✓ 追加成功（モーダルが閉じた）カテゴリ={cat_text}")
                return True, cat_text
            except PWTimeout:
                err_lines = [l.strip() for l in modal_text.split('\n')
                             if 10 < len(l.strip()) < 200]
                logger.warning(f"  バリデーションエラー: {' | '.join(err_lines[-3:])[-200:]}")
                continue

        except Exception as e:
            if any(kw in str(e).lower() for kw in ["dialog", "detached", "hidden", "target"]):
                logger.info(f"  ✓ 追加成功（操作中にモーダル消失）カテゴリ={cat_text}")
                return True, cat_text
            logger.warning(f"  追加ボタンエラー: {e}")
            continue

    return False, "すべてのカテゴリで失敗"


def get_google_image_urls(browser, keyword: str = "サコッシュ", max_count: int = 20) -> list:
    """Google画像検索からURLリストを動的に取得する（別タブで実行）"""
    logger.info(f"Google画像検索: 「{keyword}」でURL取得中...")
    urls = []
    gpage = browser.new_page(viewport={"width": 1280, "height": 900})
    try:
        gpage.goto(
            f"https://www.google.com/search?q={keyword}&tbm=isch&hl=ja",
            wait_until="domcontentloaded"
        )
        gpage.wait_for_timeout(2000)

        # 同意ページ対応
        try:
            btn = gpage.locator('button:has-text("同意する"), button:has-text("Accept all")').first
            if btn.is_visible(timeout=2000):
                btn.click()
                gpage.wait_for_timeout(1000)
        except Exception:
            pass

        # サムネイルをクリックして大きい画像URLを収集
        thumbs = gpage.locator('div[data-id] img, g-img img, div[jsname] img[src^="http"]').all()
        logger.info(f"  サムネイル数: {len(thumbs)}")

        for thumb in thumbs:
            if len(urls) >= max_count:
                break
            try:
                thumb.scroll_into_view_if_needed()
                thumb.click()
                gpage.wait_for_timeout(800)
                # サイドパネルの大きい画像を取得
                for sel in ['img.iPVvYb', 'img.r48jcc', 'img[jsname="kn3ccd"]', 'img[jsname="JuXqh"]']:
                    try:
                        big = gpage.locator(sel).first
                        src = big.get_attribute('src') or ''
                        if src.startswith('http') and 'google' not in src and src not in urls:
                            urls.append(src)
                            logger.info(f"  [{len(urls)}] {src[:80]}")
                            break
                    except Exception:
                        continue
            except Exception:
                continue

    except Exception as e:
        logger.warning(f"Google画像検索エラー: {e}")
    finally:
        gpage.close()

    logger.info(f"Google画像URL取得完了: {len(urls)}件")
    return urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--count",   type=int, default=2)
    parser.add_argument("--csv",     default=str(DEFAULT_CSV))
    parser.add_argument("--no-filter", action="store_true", help="画像フィルタリングを無効化")
    parser.add_argument("--keyword", default="サコッシュ", help="Google画像検索キーワード")
    args = parser.parse_args()

    logger.info(f"=== add_five.py 開始 | dry_run={args.dry_run} | 目標={args.count}件 ===")

    existing_urls = load_existing_urls(Path(args.csv))

    # セッション内で試みたsupplier_urlも除外対象に追加
    session_tried: set = set()

    if not args.no_filter:
        # EasyOCRを事前ロード（時間がかかるので先にやっておく）
        get_ocr_reader()

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)

            # Google画像検索でURLを動的取得
            search_image_urls = get_google_image_urls(browser, keyword=args.keyword, max_count=20)
            if not search_image_urls:
                logger.warning("Google画像URLが取得できませんでした → ハードコードURLにフォールバック")
                search_image_urls = SEARCH_IMAGE_URLS

            added_count = 0
            variant_idx = 0
            search_url_idx = 0

            while added_count < args.count:
                if search_url_idx >= len(search_image_urls) * 3:
                    logger.warning("すべての検索URLを試しましたが目標件数に届きませんでした")
                    break

                search_url = search_image_urls[search_url_idx % len(search_image_urls)]
                search_url_idx += 1
                logger.info(f"\n--- 検索URL [{search_url_idx}]: {search_url[:60]}... ---")

                # イテレーション単位でエラーを吸収して次のURLへ続行
                try:
                    if not search_products(page, search_url):
                        continue

                    detail_btns = page.query_selector_all('button:has-text("詳細を見る")')
                    logger.info(f"  「詳細を見る」ボタン数: {len(detail_btns)}")

                    found_new = False
                    for i, btn in enumerate(detail_btns[:20]):
                        try:
                            btn.click()
                            page.wait_for_selector('[role="dialog"]', timeout=8_000)
                            page.wait_for_timeout(1500)

                            # 画像枚数チェック
                            modal_text = page.locator('[role="dialog"]').inner_text()
                            slide_m = re.search(r'(\d+)/(\d+)', modal_text)
                            total_slides = int(slide_m.group(2)) if slide_m else 0

                            if total_slides < 3:
                                logger.info(f"  [{i}] 画像{total_slides}枚（不足）→ スキップ")
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(500)
                                continue

                            # supplier_url 取得・重複チェック
                            supplier_url = get_modal_supplier_url(page)
                            norm_url = supplier_url.replace('.html', '.htm') if supplier_url else ''

                            if norm_url and (norm_url in existing_urls or norm_url in session_tried):
                                logger.info(f"  [{i}] 既知URL → スキップ: {supplier_url[:60]}")
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(500)
                                continue

                            logger.info(f"  [{i}] 新規商品 ({total_slides}枚) supplier_url={supplier_url[:60]}")
                            if norm_url:
                                session_tried.add(norm_url)

                            found_new = True

                            variant = PRODUCT_VARIANTS[variant_idx % len(PRODUCT_VARIANTS)]
                            variant_idx += 1

                            success, result = try_add_product(
                                page, variant["concept"], variant["color"], variant["size"],
                                dry_run=args.dry_run
                            )

                            if success:
                                added_count += 1
                                if norm_url:
                                    existing_urls.add(norm_url)
                                logger.info(f"✓✓✓ {added_count}/{args.count}件目 追加完了！（{result}）")
                                try:
                                    page.screenshot(path=f"logs/added_{added_count:02d}.png", full_page=True)
                                except Exception:
                                    pass
                                # モーダルを確実に閉じてから次へ
                                try:
                                    page.keyboard.press("Escape")
                                    page.wait_for_timeout(800)
                                    page.locator('[role="dialog"]').wait_for(state="hidden", timeout=3_000)
                                except Exception:
                                    pass
                                logger.info(f"  → 次の商品へ ({added_count}/{args.count}件完了)")
                            else:
                                logger.warning(f"  失敗: {result}")
                                try:
                                    page.keyboard.press("Escape")
                                    page.wait_for_timeout(500)
                                except Exception:
                                    pass

                            break  # 1商品試したら次の検索URLへ

                        except Exception as e:
                            logger.warning(f"  [{i}] エラー: {e}")
                            try:
                                page.keyboard.press("Escape")
                                page.wait_for_timeout(400)
                            except Exception:
                                pass

                    if not found_new:
                        logger.info("  この検索結果では新規商品が見つかりませんでした")

                except Exception as e:
                    logger.warning(f"  検索URLスキップ（エラー）: {e}")
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            page.screenshot(path="logs/unexpected_error.png")

        finally:
            logger.info(f"\n{'='*50}")
            logger.info(f"完了: {added_count}/{args.count}件 追加しました")
            logger.info(f"{'='*50}")
            logger.info("\nブラウザはそのまま開いています。")
            try:
                input("Enterキーで終了...")
            except (EOFError, KeyboardInterrupt):
                pass
            browser.close()


if __name__ == "__main__":
    main()
