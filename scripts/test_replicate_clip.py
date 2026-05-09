"""Replicate API 接続テスト: item 105 の表紙から1本だけ5秒クリップを生成。

実行:
  python scripts/test_replicate_clip.py
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from utils.ai_video import generate_clip  # noqa: E402

# item 105 の img8: ネイビーバッグを腰の位置で手で持つライフスタイルショット
IMAGE_URL = "https://fulmo-img-server.com/sacoche-sacolla/6bae40931b134fc990cad7526ed438cf.jepg"

PROMPT = (
    "A young woman gently adjusts the navy nylon sacoche bag at her waist, "
    "soft natural daylight, subtle hand movement, lifestyle photography, "
    "minimal motion, shallow depth of field"
)

MODEL = "wan-video/wan-2.5-i2v-fast"
OUT = ROOT / "data" / "instagram" / "reels" / "clips" / "105_wan_test.mp4"


def main() -> None:
    print(f"モデル: {MODEL}")
    print(f"画像: {IMAGE_URL}")
    print(f"プロンプト: {PROMPT}")
    print("生成開始...(30〜90秒)")
    t0 = time.time()
    out = generate_clip(IMAGE_URL, PROMPT, OUT, model=MODEL, duration=5)
    elapsed = time.time() - t0
    size_mb = out.stat().st_size / 1024 / 1024
    print(f"\n完了: {out}")
    print(f"  時間: {elapsed:.1f}秒")
    print(f"  サイズ: {size_mb:.2f} MB")


if __name__ == "__main__":
    main()
