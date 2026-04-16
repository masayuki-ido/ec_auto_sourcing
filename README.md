# EC商品自動追加システム

Alibaba商品DBから対象商品を自動で選定し、ECサイト管理画面に追加するPythonツールです。

---

## 全体フロー

```
起動
 │
 ├─① ログイン
 │    管理画面（https://sacoche-sacolla.flumo-admin-server.com/login）に
 │    Playwrightでブラウザアクセスし、ID/パスワードで認証する
 │
 ├─② 商品検索
 │    管理画面経由でAlibabaベース商品DBをキーワード検索する
 │    例: 「サコッシュ」「ポーチ」
 │
 ├─③ 価格・画像フィルタ
 │    ・価格が15,000円以内の商品のみ通過
 │    ・商品画像が存在する商品のみ通過
 │
 ├─④ 画像フィルタ（OCR・サイズ）
 │    ・EasyOCRで画像内テキストを解析
 │      → 中国語（簡体字・繁体字）が含まれる画像は除外
 │    ・短辺500px未満の低解像度画像は除外
 │
 ├─⑤ カラー整合性チェック
 │    ・Pillowで画像の主要色（上位3色）を抽出
 │    ・管理画面の自動検出カラーリストと照合
 │      → 管理画面にあるが画像にない色: リストから削除
 │      → 画像にあるが管理画面にない色: リストに追加
 │
 ├─⑥ カテゴリ自動選択
 │    ・商品名のキーワードからカテゴリを自動判定
 │      例: 「サコッシュ」→「ショルダーバッグ」
 │    ・管理画面のプルダウンで自動選択
 │
 └─⑦ 商品追加
      ・「追加」ボタンをクリックして保存
      ・追加済みIDをadded_products.jsonに記録（重複防止）
      ・ログに商品名・価格・日時を記録
```

---

## セットアップ

### 1. リポジトリ準備

```bash
cd ec-auto-add
```

### 2. 仮想環境の作成と有効化

```bash
python -m venv .venv
source .venv/bin/activate      # Mac/Linux
.venv\Scripts\activate         # Windows
```

### 3. 依存ライブラリのインストール

```bash
pip install -r requirements.txt
playwright install chromium     # Playwrightのブラウザをインストール
```

### 4. 環境変数の設定

```bash
cp .env.example .env
```

`.env` を編集してログイン情報を入力してください:

```
ADMIN_URL=https://sacoche-sacolla.flumo-admin-server.com/login
ADMIN_USER=your_login_id
ADMIN_PASS=your_password
SEARCH_KEYWORDS=サコッシュ,ポーチ
ADD_LIMIT=10
SCHEDULE_TIME=09:00
HEADLESS=True
```

---

## 実行方法

### 手動実行（1回）

```bash
python main.py
```

### キーワードを指定して実行

```bash
python main.py --keyword サコッシュ ポーチ
```

### 確認モード（実際には追加しない）

```bash
python main.py --dry-run
```

### 個別ステップのテスト実行

```bash
python main.py --step login       # ログインのみテスト
python main.py --step search      # 検索まで実行
python main.py --step filter      # 価格フィルタまで
python main.py --step image       # 画像フィルタまで
python main.py --step color       # カラーチェックまで
python main.py --step category    # カテゴリ選択まで
```

### 常駐実行（スケジューラ）

```bash
python scheduler.py               # 毎日 SCHEDULE_TIME に自動実行
python scheduler.py --now         # 即時1回実行してからスケジュール待機
```

---

## cronへの登録（Linux/Mac）

毎日朝9時に自動実行する例:

```bash
crontab -e
```

以下を追記（パスは環境に合わせて変更）:

```
0 9 * * * cd /path/to/ec-auto-add && /path/to/.venv/bin/python main.py >> logs/cron.log 2>&1
```

パスの確認方法:

```bash
which python                    # または: which python3
pwd                             # プロジェクトの絶対パスを確認
```

---

## ファイル構成

```
ec-auto-add/
├── main.py               # メイン処理・エントリポイント
├── scheduler.py          # 日次スケジュール実行
├── config.py             # 設定値・マッピング辞書
├── steps/
│   ├── login.py          # ログイン処理
│   ├── search.py         # 商品検索
│   ├── filter_products.py # 価格・画像フィルタ
│   ├── filter_images.py  # OCR・サイズフィルタ
│   ├── color_check.py    # カラー整合性チェック
│   ├── category_select.py # カテゴリ自動選択
│   └── add_product.py    # 商品追加
├── utils/
│   ├── ocr.py            # EasyOCR ユーティリティ
│   └── color_detect.py   # 主要色抽出ユーティリティ
├── logs/                 # 実行ログ（YYYY-MM-DD.log）
├── added_products.json   # 追加済み商品ID（自動生成）
├── .env                  # 環境変数（要作成）
├── .env.example          # 環境変数テンプレート
├── requirements.txt      # 依存ライブラリ
└── README.md             # このファイル
```

---

## 管理画面セレクタの調整

このツールは管理画面のHTML構造に依存しています。  
各ステップファイルの `SEL_*` 変数を実際の管理画面に合わせて調整してください。

1. ブラウザで管理画面を開く
2. 対象要素を右クリック → 「検証」
3. 該当のCSSセレクタを各ファイルの `SEL_*` 変数に設定

調整が必要なファイル:

| ファイル | 調整する変数 |
|---|---|
| steps/login.py | SEL_USERNAME, SEL_PASSWORD, SEL_SUBMIT, SEL_AFTER_LOGIN |
| steps/search.py | SEARCH_PAGE_PATH, SEL_SEARCH_INPUT, SEL_SEARCH_BUTTON, SEL_RESULT_ROW |
| steps/color_check.py | SEL_COLOR_LIST, SEL_COLOR_LABEL, SEL_COLOR_ADD_BTN |
| steps/category_select.py | SEL_CATEGORY_SELECT |
| steps/add_product.py | SEL_DETAIL_LINK, SEL_ADD_BUTTON, SEL_SUCCESS_MSG |

---

## ログ

- 実行ログは `logs/YYYY-MM-DD.log` に日付別で保存されます
- エラー時のスクリーンショットは `logs/error_*.png` に保存されます

---

## 注意事項

- EasyOCRの初回起動時はモデルのダウンロードが発生します（数分かかる場合があります）
- `HEADLESS=False` にするとブラウザ画面が表示されます（動作確認に便利）
- 3件連続で追加失敗した場合、コンソールに警告が表示されます
