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
import argparse, logging, re, sys, csv, time, threading, http.server, socketserver
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
_ocr_filter_enabled = True  # --no-filter で False になる

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
    if not _ocr_filter_enabled:
        return True
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


def search_products(page, keyword: str = "サコッシュ") -> bool:
    page.goto(f"{BASE}/item/search", wait_until="networkidle")
    page.wait_for_timeout(1000)

    # 利用可能なセレクトオプションをログ出力
    try:
        sel_opts = page.locator("select").first.locator("option").all()
        opts_info = [(o.get_attribute("value"), o.inner_text().strip()) for o in sel_opts]
        logger.info(f"  検索タイプ選択肢: {opts_info}")
        # "image" 以外のキーワード系オプションを優先
        kw_val = None
        for val, text in opts_info:
            if val and val != "image":
                kw_val = val
                logger.info(f"  キーワード検索オプション使用: value='{val}' ({text})")
                break
        if kw_val:
            page.select_option("select", value=kw_val)
        else:
            logger.warning("  キーワード検索オプションが見つかりません。imageモードで試みます")
            page.select_option("select", value="image")
    except Exception as e:
        logger.warning(f"  セレクトオプション取得失敗: {e}")

    page.wait_for_timeout(1000)

    # キーワード入力欄を探す（より広いセレクタで）
    filled = False
    for sel in ['input[placeholder*="キーワード"]', 'input[placeholder*="検索"]',
                'input[name="keyword"]', 'input[type="search"]',
                'input[placeholder*="URL"]', 'input[type="text"]', 'input']:
        try:
            el = page.locator(sel).first
            if el.is_visible(timeout=800):
                val = el.input_value(timeout=500)
                el.fill(keyword)
                logger.info(f"  キーワード入力: 「{keyword}」→ {sel}")
                filled = True
                break
        except Exception:
            continue

    if not filled:
        logger.warning("  キーワード入力欄が見つかりませんでした")

    # ボタンが有効になるまで最大5秒待つ
    page.wait_for_timeout(500)
    try:
        page.wait_for_selector('button:has-text("検索"):not([disabled])', timeout=5_000)
    except Exception:
        pass

    page.click('button:has-text("検索")', timeout=10_000)
    logger.info(f"  検索実行: 「{keyword}」")
    try:
        page.wait_for_selector('button:has-text("詳細を見る")', timeout=30_000)
        return True
    except PWTimeout:
        logger.warning("  検索タイムアウト")
        return False


def get_modal_price(page) -> int:
    """モーダルの販売価格を取得（取得できなければ0を返す）"""
    try:
        modal = page.locator('[role="dialog"]')
        # 販売価格フィールド（数値のinput）
        for sel in ['input[placeholder="販売価格"]', 'input[name*="price"]', 'input[name*="Price"]']:
            try:
                el = modal.locator(sel).first
                val = el.input_value(timeout=1000).strip().replace(',', '')
                if val:
                    return int(float(val))
            except Exception:
                continue
        # セレクタが合わない場合はラベル「販売価格」の隣のinputを探す
        try:
            price_label = modal.locator('text=販売価格').first
            price_input = price_label.locator('..').locator('input').first
            val = price_input.input_value(timeout=1000).strip().replace(',', '')
            if val:
                return int(float(val))
        except Exception:
            pass
    except Exception:
        pass
    return 0


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

    # 商品画像: 先頭から最大5枚（ボタンリストは一度だけ取得）
    product_indices = usable_indices[:5]
    clicked_product = []
    for idx in product_indices:
        if idx >= len(product_btns):
            break
        try:
            btn = product_btns[idx]
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(300)
            btn.click(force=True)
            page.wait_for_timeout(500)
            clicked_product.append(idx)
        except Exception as e:
            logger.debug(f"    商品画像ボタン[{idx}]クリック失敗: {e}")
    logger.info(f"  商品画像を追加: {clicked_product}")

    page.wait_for_timeout(800)

    # サイズ画像: 先頭2枚を使用（ボタンリストは一度だけ取得・インデックスずれを防ぐ）
    size_target = size_btns[:2] if len(size_btns) >= 2 else size_btns
    clicked_size = []
    for i, btn in enumerate(size_target):
        try:
            btn.scroll_into_view_if_needed()
            page.wait_for_timeout(500)
            btn.click(force=True)
            page.wait_for_timeout(1000)
            clicked_size.append(i)
            logger.info(f"    サイズ画像[{i}]クリック完了")
        except Exception as e:
            logger.debug(f"    サイズ画像ボタン[{i}]クリック失敗: {e}")
    logger.info(f"  サイズ画像を追加: {clicked_size}")

    page.wait_for_timeout(800)


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
            page.wait_for_timeout(1200)
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


URL_CACHE_FILE = Path("search_image_urls.txt")


def load_cached_image_urls() -> list:
    """キャッシュファイルからURLリストを読み込む"""
    if not URL_CACHE_FILE.exists():
        return []
    urls = [line.strip() for line in URL_CACHE_FILE.read_text(encoding="utf-8").splitlines()
            if line.strip() and line.strip().startswith("http")]
    logger.info(f"キャッシュから {len(urls)} 件のURLを読み込みました: {URL_CACHE_FILE}")
    return urls


def save_image_urls_to_cache(urls: list) -> None:
    """URLリストをキャッシュファイルに保存"""
    URL_CACHE_FILE.write_text("\n".join(urls), encoding="utf-8")
    logger.info(f"{len(urls)} 件のURLをキャッシュに保存: {URL_CACHE_FILE}")


IMAGES_DIR = Path("search_images")


def download_images_from_urls(urls: list, max_images: int = 30) -> list:
    """URLリストから画像をローカルに保存し、保存済みファイルパスを返す"""
    IMAGES_DIR.mkdir(exist_ok=True)
    saved = []
    for i, url in enumerate(urls[:max_images]):
        dest = IMAGES_DIR / f"img_{i:03d}.jpg"
        if dest.exists():
            saved.append(str(dest))
            continue
        try:
            resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
            if resp.status_code == 200 and resp.content:
                dest.write_bytes(resp.content)
                saved.append(str(dest))
                logger.info(f"  DL [{len(saved)}] {url[:70]}")
        except Exception as e:
            logger.debug(f"  DL失敗: {e}")
    logger.info(f"ローカル画像保存完了: {len(saved)}件 → {IMAGES_DIR}/")
    return saved


def start_local_image_server(port: int = 18765) -> "http.server.HTTPServer":
    """search_images/ を提供するローカルHTTPサーバーを別スレッドで起動"""
    import http.server
    import socketserver

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(IMAGES_DIR.resolve()), **kw)
        def log_message(self, *_):
            pass  # ログ抑制

    server = socketserver.TCPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    logger.info(f"ローカル画像サーバー起動: http://127.0.0.1:{port}/")
    return server


def fetch_1688_image_urls(browser, keyword: str = "サコッシュ", max_count: int = 50) -> list:
    """1688.comの商品検索からAliCDN画像URLを取得する"""
    logger.info(f"1688.com検索: 「{keyword}」でURL取得中...")
    urls = []
    import urllib.parse
    gpage = browser.new_page(
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )
    try:
        encoded = urllib.parse.quote(keyword)
        gpage.goto(
            f"https://s.1688.com/selloffer/offer_search.htm?keywords={encoded}",
            wait_until="domcontentloaded",
            timeout=60_000
        )
        gpage.wait_for_timeout(4000)

        for _ in range(5):
            gpage.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            gpage.wait_for_timeout(1500)

        # ページ内の全imgからalicdnを抽出
        all_imgs = gpage.locator("img").all()
        logger.info(f"  img要素数: {len(all_imgs)}")
        for img in all_imgs:
            if len(urls) >= max_count:
                break
            try:
                src = (img.get_attribute("src") or
                       img.get_attribute("data-src") or
                       img.get_attribute("data-lazy-src") or "")
                if src.startswith("//"):
                    src = "https:" + src
                if src and "alicdn.com" in src and src not in urls:
                    urls.append(src)
                    logger.info(f"  [{len(urls)}] {src[:80]}")
            except Exception:
                continue

        if not urls:
            logger.warning("  URLが取得できませんでした（スクリーンショット保存）")
            try:
                gpage.screenshot(path="logs/1688_debug.png")
            except Exception:
                pass

    except Exception as e:
        logger.warning(f"1688.com検索エラー: {e}")
        try:
            gpage.screenshot(path="logs/1688_error.png")
        except Exception:
            pass
    finally:
        gpage.close()

    logger.info(f"1688.com画像URL取得完了: {len(urls)}件")
    return urls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--count",   type=int, default=2)
    parser.add_argument("--csv",     default=str(DEFAULT_CSV))
    parser.add_argument("--no-filter", action="store_true", help="画像フィルタリングを無効化")
    parser.add_argument("--keyword", default="サコッシュ", help="Google画像検索キーワード")
    parser.add_argument("--max-price", type=int, default=10000, help="販売価格上限（円）")
    parser.add_argument("--refresh-urls", action="store_true", help="Bingから画像URLを再取得してキャッシュを更新")
    args = parser.parse_args()

    logger.info(f"=== add_five.py 開始 | dry_run={args.dry_run} | 目標={args.count}件 ===")

    global _ocr_filter_enabled
    if args.no_filter:
        _ocr_filter_enabled = False

    existing_urls = load_existing_urls(Path(args.csv))

    # セッション内で試みたsupplier_urlも除外対象に追加
    session_tried: set = set()

    if not args.no_filter:
        # EasyOCRを事前ロード（時間がかかるので先にやっておく）
        get_ocr_reader()

    added_count = 0       # finally で参照するため外側で初期化
    local_server = None   # finally で参照するため外側で初期化

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)

            # キーワード検索で商品一覧を取得
            logger.info(f"\nキーワード「{args.keyword}」で検索します...")
            if not search_products(page, args.keyword):
                logger.error("検索に失敗しました。終了します。")
                return

            detail_locator = page.locator('button:has-text("詳細を見る")')
            total_btns = detail_locator.count()
            logger.info(f"  「詳細を見る」ボタン数: {total_btns}")

            variant_idx = 0
            btn_idx = 0

            while added_count < args.count:
                if btn_idx >= total_btns:
                    logger.warning("検索結果の商品をすべて試しましたが目標件数に届きませんでした")
                    break

                i = btn_idx
                btn_idx += 1
                logger.info(f"\n--- 商品 [{i+1}/{total_btns}] ---")

                try:
                    btn = detail_locator.nth(i)
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

                    # 価格チェック（上限超えはスキップ）
                    price = get_modal_price(page)
                    if price > args.max_price:
                        logger.info(f"  [{i}] 価格{price}円 > {args.max_price}円 → スキップ")
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(500)
                        continue
                    if price > 0:
                        logger.info(f"  [{i}] 価格チェックOK: {price}円")

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

                except Exception as e:
                    logger.warning(f"  [{i}] エラー: {e}")
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(400)
                    except Exception:
                        pass

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            page.screenshot(path="logs/unexpected_error.png")

        finally:
            try:
                local_server.shutdown()
            except Exception:
                pass
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
