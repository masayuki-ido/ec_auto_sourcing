"""
設定値・定数・マッピング辞書を一元管理するモジュール
"""
import os
from dotenv import load_dotenv

load_dotenv()

# ─── 管理画面 ───────────────────────────────────────────
ADMIN_URL   = os.getenv("ADMIN_URL", "https://sacoche-sacolla.flumo-admin-server.com/login")
ADMIN_USER  = os.getenv("ADMIN_USER", "")
ADMIN_PASS  = os.getenv("ADMIN_PASS", "")

# ─── 実行パラメータ ─────────────────────────────────────
SEARCH_KEYWORDS = [k.strip() for k in os.getenv("SEARCH_KEYWORDS", "サコッシュ").split(",")]
ADD_LIMIT       = int(os.getenv("ADD_LIMIT", 10))
SCHEDULE_TIME   = os.getenv("SCHEDULE_TIME", "09:00")
HEADLESS        = os.getenv("HEADLESS", "True").lower() == "true"

# ─── 商品フィルタ条件 ───────────────────────────────────
MAX_PRICE_JPY     = 15_000          # 価格上限（円）
MIN_IMAGE_SHORT_SIDE = 500          # 画像短辺の最小値（px）

# ─── OCR除外言語 ────────────────────────────────────────
# EasyOCR の言語コード: 簡体字=ch_sim, 繁体字=ch_tra
EXCLUDED_LANGUAGES = ["ch_sim", "ch_tra"]
OCR_CONFIDENCE_THRESHOLD = 0.5     # この信頼度以上のテキストを検出扱いにする

# ─── カラー名 ↔ RGB マッピング ──────────────────────────
# キー: 管理画面で使われるカラー名（日本語 or 英語）
# 値  : 代表 RGB タプル（許容誤差は color_detect.py で定義）
COLOR_MAP: dict[str, tuple[int, int, int]] = {
    "ブラック":   (20,  20,  20),
    "ホワイト":   (235, 235, 235),
    "レッド":     (200, 30,  30),
    "ネイビー":   (20,  30,  80),
    "ブルー":     (30,  80,  180),
    "ライトブルー":(100, 160, 220),
    "グリーン":   (40,  130, 60),
    "カーキ":     (120, 120, 60),
    "ベージュ":   (210, 190, 160),
    "ブラウン":   (120, 70,  40),
    "グレー":     (130, 130, 130),
    "ピンク":     (230, 130, 160),
    "イエロー":   (230, 200, 40),
    "オレンジ":   (230, 110, 30),
    "パープル":   (130, 50,  160),
}

# カラー判定の許容距離（RGB ユークリッド距離）
COLOR_TOLERANCE = 80

# ─── カテゴリマッピング ─────────────────────────────────
# キー: 検索キーワードや商品名に含まれる文字列
# 値  : 管理画面のプルダウンに表示されるカテゴリ名
CATEGORY_MAP: dict[str, str] = {
    "サコッシュ":     "ショルダーバッグ",
    "ショルダー":     "ショルダーバッグ",
    "ポーチ":         "ポーチ・小物",
    "コインケース":   "ポーチ・小物",
    "財布":           "財布",
    "長財布":         "財布",
    "トートバッグ":   "トートバッグ",
    "リュック":       "バックパック",
    "バックパック":   "バックパック",
    "クラッチ":       "クラッチバッグ",
    "ウエストポーチ": "ウエストバッグ",
    "ボディバッグ":   "ウエストバッグ",
}
DEFAULT_CATEGORY = "その他"

# ─── ファイルパス ───────────────────────────────────────
import pathlib
BASE_DIR            = pathlib.Path(__file__).parent
ADDED_PRODUCTS_FILE = BASE_DIR / "added_products.json"
LOGS_DIR            = BASE_DIR / "logs"
LOGS_DIR.mkdir(exist_ok=True)
