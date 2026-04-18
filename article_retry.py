"""
記事の自動リトライスクリプト

タイトルに「5選」「10選」を含む記事に対して:
  1. 自動編集モーダルを開く
  2. キーワードに合った商品を5つ追加
  3. タイトルを「5選→10選」「10選→15選」に変更
  4. 更新ボタンで保存

実行方法:
    python article_retry.py
    python article_retry.py --dry-run
    python article_retry.py --count 3
"""
import argparse, logging, re, sys, time
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

from config import ADMIN_USER, ADMIN_PASS
from add_five import login

LOGS = Path("logs"); LOGS.mkdir(exist_ok=True)
BASE = "https://sacoche-sacolla.flumo-admin-server.com"
SEO_ARTICLE_URL = f"{BASE}/seo_article"


def get_target_articles(page) -> list[dict]:
    """記事一覧から「5選」「10選」を含む記事を上から順に取得"""
    logger.info("記事一覧ページにアクセス中...")
    page.goto(SEO_ARTICLE_URL, wait_until="networkidle")
    page.wait_for_timeout(2000)

    articles = []
    rows = page.query_selector_all("tr")
    for row in rows:
        cells = row.query_selector_all("td")
        if len(cells) < 5:
            continue
        article_id = cells[0].inner_text().strip()
        keyword = cells[2].inner_text().strip()
        title = cells[3].inner_text().strip()

        # 「5選」or「10選」を含む記事のみ対象
        match = re.search(r'(\d+)選', title)
        if match:
            count = int(match.group(1))
            if count in (5, 10):
                link = cells[0].query_selector("a")
                href = link.get_attribute("href") if link else f"/article/{article_id}"
                articles.append({
                    "id": article_id,
                    "keyword": keyword,
                    "title": title,
                    "current_count": count,
                    "url": f"{BASE}{href}" if href.startswith("/") else href
                })

    logger.info(f"対象記事: {len(articles)}件")
    for a in articles:
        logger.info(f"  ID={a['id']} | {a['title']} | KW={a['keyword']}")
    return articles


def extract_keywords_from_title(title: str, keyword: str) -> list[str]:
    """タイトルとキーワードから検索用のキーワードリストを生成"""
    keywords = []
    # 記事のキーワードをスペースで分割
    for kw in keyword.split():
        kw = kw.strip()
        if kw:
            keywords.append(kw)
    # タイトルからも追加
    for kw in re.split(r'[　\s]+', title):
        kw = re.sub(r'\d+選.*', '', kw).strip()
        if kw and kw not in keywords and len(kw) >= 2:
            keywords.append(kw)
    return keywords


def select_matching_products(page, keywords: list[str], existing_values: set, count: int = 5) -> list[str]:
    """
    「商品を検索...」ドロップダウンからキーワードに合った商品を選択。
    既に選択済みの商品は除外する。
    Returns: 選択した商品のvalue（ID）リスト
    """
    # 検索用ドロップダウンを取得（モーダル内の最後のselect）
    search_select = page.locator('.flex.w-full.mt-4.mb-4 select').first

    # 全商品オプションを取得
    options = search_select.locator("option").all()
    all_products = []
    for opt in options:
        val = opt.get_attribute("value") or ""
        text = opt.inner_text().strip()
        if val and val != "" and text != "選択してください":
            all_products.append({"value": val, "text": text})

    # キーワードでフィルタリング（全キーワードのいずれかに一致）
    matching = []
    for prod in all_products:
        if prod["value"] in existing_values:
            continue
        score = sum(1 for kw in keywords if kw in prod["text"])
        if score > 0:
            matching.append((score, prod))

    # スコア順にソート（マッチ度の高いものから）
    matching.sort(key=lambda x: x[0], reverse=True)

    selected = []
    for score, prod in matching:
        if len(selected) >= count:
            break
        selected.append(prod)
        logger.info(f"    商品追加候補: [score={score}] {prod['text'][:50]}")

    # キーワードマッチが足りない場合はランダムに追加
    if len(selected) < count:
        logger.info(f"    キーワードマッチ不足 ({len(selected)}/{count}) → 追加で選択")
        for prod in all_products:
            if len(selected) >= count:
                break
            if prod["value"] not in existing_values and prod not in selected:
                selected.append(prod)
                logger.info(f"    追加選択: {prod['text'][:50]}")

    return selected


def retry_single_article(page, article: dict, dry_run: bool) -> bool:
    """1つの記事をリトライ（商品追加 + タイトル変更）"""
    logger.info(f"\n--- 記事ID {article['id']}: {article['title']} ---")

    page.goto(article["url"], wait_until="networkidle")
    page.wait_for_timeout(3000)

    if dry_run:
        logger.info(f"  [DRY-RUN] リトライスキップ: {article['title']}")
        return True

    # 「自動編集」ボタンをクリック
    try:
        auto_edit_btn = page.locator('button:has-text("自動編集")')
        auto_edit_btn.click()
        logger.info("  「自動編集」をクリック")
        page.wait_for_timeout(2000)
    except Exception as e:
        logger.warning(f"  「自動編集」ボタンクリック失敗: {e}")
        return False

    # モーダルが表示されるのを待つ
    try:
        page.locator('text=選択中の商品数').wait_for(timeout=10_000)
        logger.info("  自動編集モーダル表示")
    except PWTimeout:
        logger.warning("  モーダル表示タイムアウト")
        page.screenshot(path=f"logs/article_modal_timeout_{article['id']}.png")
        return False

    # 現在選択中の商品IDを取得（重複防止用）
    existing_values = set()
    product_selects = page.locator('select').all()
    for sel in product_selects:
        try:
            val = sel.input_value()
            if val and val not in ("", "選択してください"):
                existing_values.add(val)
        except Exception:
            pass
    logger.info(f"  既存商品ID: {existing_values}")

    # キーワードを抽出
    keywords = extract_keywords_from_title(article["title"], article["keyword"])
    logger.info(f"  検索キーワード: {keywords}")

    # キーワードに合った商品を選択
    products_to_add = select_matching_products(page, keywords, existing_values, count=5)
    if not products_to_add:
        logger.warning("  追加する商品が見つかりません")
        page.keyboard.press("Escape")
        return False

    # 1つずつ商品を追加（ドロップダウンから選択）
    added = 0
    for prod in products_to_add:
        try:
            # 「商品を検索...」ドロップダウンを取得（毎回再取得）
            search_select = page.locator('.flex.w-full.mt-4.mb-4 select').first
            search_select.select_option(value=prod["value"])
            page.wait_for_timeout(1000)
            added += 1
            logger.info(f"  商品追加 [{added}]: {prod['text'][:50]}")
        except Exception as e:
            logger.warning(f"  商品追加失敗: {prod['text'][:50]} - {e}")

    if added == 0:
        logger.warning("  商品を1つも追加できませんでした")
        page.keyboard.press("Escape")
        return False

    logger.info(f"  {added}商品を追加")

    # タイトルを変更（5選→10選、10選→15選）
    new_count = article["current_count"] + 5
    old_label = f"{article['current_count']}選"
    new_label = f"{new_count}選"

    try:
        # モーダル内のタイトルinputを取得
        title_input = page.locator('input').first
        current_title = title_input.input_value()

        if old_label in current_title:
            new_title = current_title.replace(old_label, new_label)
            title_input.fill(new_title)
            logger.info(f"  タイトル変更: {current_title} → {new_title}")
        else:
            logger.info(f"  タイトルに「{old_label}」が見つかりません（変更スキップ）")
    except Exception as e:
        logger.warning(f"  タイトル変更失敗: {e}")

    # 「更新」ボタンをクリック
    try:
        update_btn = page.locator('button:has-text("更新")')
        update_btn.click()
        logger.info("  「更新」をクリック")
        page.wait_for_timeout(5000)
    except Exception as e:
        logger.warning(f"  更新ボタンクリック失敗: {e}")
        return False

    logger.info(f"  ✓ 記事リトライ完了: {article['title']} → {new_label}")
    try:
        page.screenshot(path=f"logs/article_retried_{article['id']}.png")
    except Exception:
        pass

    return True


def main():
    parser = argparse.ArgumentParser(description="記事リトライ自動スクリプト")
    parser.add_argument("--dry-run", action="store_true", help="実際には更新しない確認モード")
    parser.add_argument("--count", type=int, default=5, help="処理する記事数")
    args = parser.parse_args()

    logger.info(f"=== article_retry.py 開始 | dry_run={args.dry_run} | 目標={args.count}件 ===")

    retried_count = 0

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=False)
        page = browser.new_page(viewport={"width": 1280, "height": 900})

        try:
            login(page)

            # 対象記事リストを取得
            articles = get_target_articles(page)

            if not articles:
                logger.info("対象となる記事はありません")
                return

            # 上から順に処理
            for article in articles[:args.count]:
                try:
                    success = retry_single_article(page, article, dry_run=args.dry_run)
                    if success:
                        retried_count += 1
                        logger.info(f"✓✓✓ {retried_count}/{args.count}件 リトライ完了")
                    else:
                        logger.warning(f"  記事 {article['id']} のリトライに失敗")
                except Exception as e:
                    logger.error(f"  記事 {article['id']} 処理中にエラー: {e}")
                    try:
                        page.keyboard.press("Escape")
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass

                if retried_count >= args.count:
                    break

        except Exception as e:
            logger.error(f"予期しないエラー: {e}", exc_info=True)
            page.screenshot(path="logs/article_unexpected_error.png")

        finally:
            logger.info(f"\n{'='*50}")
            logger.info(f"完了: {retried_count}/{args.count}件 リトライしました")
            logger.info(f"{'='*50}")
            logger.info("\nブラウザはそのまま開いています。")
            try:
                input("Enterキーで終了...")
            except (EOFError, KeyboardInterrupt):
                pass
            browser.close()


if __name__ == "__main__":
    main()
