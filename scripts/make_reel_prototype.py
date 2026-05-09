"""item 105 のリール動画プロトタイプ。

スタイル検証用:
  - 商品画像3枚を Ken Burns で繋ぐ
  - 各シーンに白文字×黒角丸ボックスのコピー
  - 9:16 1080x1920 MP4、約12秒、無音

実行:
  python scripts/make_reel_prototype.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from utils.reel_video import make_reel  # noqa: E402

OUT = ROOT / "data" / "instagram" / "reels" / "105_proto.mp4"

SCENES = [
    {
        "image": str(ROOT / "data" / "instagram" / "covers" / "105.jpg"),
        "text": "肩が軽い、\n毎日が軽い。",
        "duration": 3.5,
        "motion": "zoom_in",
        "text_y_ratio": 0.55,
    },
    {
        "image": "https://fulmo-img-server.com/sacoche-sacolla/94913927203541b68978e3b73a224b4f.jepg",
        "text": "わずか50g。\n持っていることを\n忘れる軽さ。",
        "duration": 4.0,
        "motion": "zoom_out",
        "text_y_ratio": 0.62,
    },
    {
        "image": "https://fulmo-img-server.com/sacoche-sacolla/6bae40931b134fc990cad7526ed438cf.jepg",
        "text": "全6色から、\nあなたの一枚を。",
        "duration": 4.0,
        "motion": "zoom_in",
        "text_y_ratio": 0.62,
    },
]


def main() -> None:
    print(f"生成中: {OUT}")
    make_reel(SCENES, OUT)
    print(f"完了: {OUT}")
    print(f"ファイルサイズ: {OUT.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
