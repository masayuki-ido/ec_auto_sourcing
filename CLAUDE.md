# EC商品自動追加システム

## プロジェクト概要

Alibaba商品DBから商品を自動選定し、ECサイト管理画面（sacoche-sacolla.flumo-admin-server.com）に追加するPlaywright自動化ツール。

## 処理フロー

1. **ログイン** → 管理画面に認証
2. **検索** → キーワードで商品DB検索（サコッシュ、ポーチ等）
3. **価格フィルタ** → 15,000円以内の商品のみ通過
4. **画像フィルタ** → OCRで中国語テキスト含む画像を除外、短辺500px未満を除外
5. **カラーチェック** → 画像の主要色と管理画面のカラーリストを同期
6. **カテゴリ選択** → 商品名からカテゴリを自動判定しプルダウン選択
7. **商品追加** → 「追加」ボタンをクリックして保存

## 実行方法

```bash
# 環境セットアップ（初回のみ）
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

# 商品追加（件数は.envのADD_LIMITで制御）
python main.py

# キーワード指定
python main.py --keyword サコッシュ

# 確認のみ（追加しない）
python main.py --dry-run

# 個別ステップテスト
python main.py --step login
```

## 重要ファイル

| ファイル | 役割 |
|---|---|
| main.py | エントリポイント。全ステップを順に実行 |
| config.py | 設定値・カテゴリマッピング・カラーマッピング |
| .env | 認証情報・検索キーワード・追加件数（**git管理外**） |
| steps/*.py | 各ステップの処理（login, search, filter等） |
| utils/*.py | OCR・カラー検出ユーティリティ |
| probe.py〜probe5.py | 管理画面のHTML構造調査用スクリプト |
| test_one.py | 1件だけの統合テスト（--dry-run対応） |

## セレクタについて

各steps/*.pyファイルの先頭にある `SEL_*` 変数は管理画面のCSSセレクタ。
管理画面のHTMLが変更された場合は probe.py を実行して最新のセレクタを確認し、該当ファイルを更新する。

## タスク実行時の注意

- **初回実行時**: まず `python probe.py` でログイン〜検索の動作確認をする。スクリーンショットが logs/ に保存されるので、セレクタが合っているか確認。合っていなければ steps/ 内の SEL_* を修正。
- **HEADLESS=False** にすると画面が見えるのでデバッグに便利。
- **追加済み商品**: added_products.json にIDが記録される（重複防止）。
- **ログ**: logs/YYYY-MM-DD.log に実行ログが出る。
- **スクリーンショット**: 各ステップ実行後に logs/ 配下に保存すること。特にエラー時は必ずスクリーンショットを取る。
- **商品追加後**: 追加した商品の管理画面詳細ページのスクリーンショットを保存して、結果を報告する。

## .env テンプレート

```
ADMIN_URL=https://sacoche-sacolla.flumo-admin-server.com/login
ADMIN_USER=（メールアドレス）
ADMIN_PASS=（パスワード）
SEARCH_KEYWORDS=サコッシュ,ポーチ
ADD_LIMIT=5
SCHEDULE_TIME=09:00
HEADLESS=False
```
