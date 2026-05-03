"""Instagram投稿用の表紙画像を生成 (Pillow)。

商品画像にテキストオーバーレイを重ねた1080x1080のJPEGを出力する。
構成:
  - 上部中央: ＼{top_text}／  (中サイズ・白文字+黒縁)
  - 下部左: {bottom_text}     (大サイズ・改行可・白文字+黒縁)
"""
from __future__ import annotations

from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "NotoSansJP-Bold.otf"

CANVAS = 1080
TOP_FONT_SIZE = 48
BOTTOM_FONT_SIZE = 170
BOTTOM_LINE_GAP = 10
BOTTOM_MARGIN_LEFT = 60
BOTTOM_MARGIN_BOTTOM = 60
TOP_MARGIN_TOP = 60


def _font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():
        raise FileNotFoundError(
            f"日本語フォントが見つかりません: {FONT_PATH}\n"
            f"  assets/fonts/NotoSansJP-Bold.otf を配置してください。"
        )
    return ImageFont.truetype(str(FONT_PATH), size)


def _square_crop(img: Image.Image) -> Image.Image:
    w, h = img.size
    s = min(w, h)
    return img.crop(((w - s) // 2, (h - s) // 2, (w + s) // 2, (h + s) // 2))


def _download(url: str) -> Image.Image:
    res = requests.get(url, timeout=30)
    res.raise_for_status()
    return Image.open(BytesIO(res.content)).convert("RGB")


def make_cover(image_url: str, top_text: str, bottom_text: str, out_path: Path) -> Path:
    img = _download(image_url)
    img = _square_crop(img).resize((CANVAS, CANVAS), Image.LANCZOS)

    draw = ImageDraw.Draw(img, "RGBA")

    # 上部の煽り文 ＼xxx／
    top_str = f"＼{top_text}／"
    top_font = _font(TOP_FONT_SIZE)
    bbox = draw.textbbox((0, 0), top_str, font=top_font)
    top_x = (CANVAS - (bbox[2] - bbox[0])) // 2
    draw.text(
        (top_x, TOP_MARGIN_TOP),
        top_str,
        font=top_font,
        fill="white",
        stroke_width=4,
        stroke_fill=(30, 30, 30, 255),
    )

    # 下部の大字 (改行で複数行対応)
    bot_font = _font(BOTTOM_FONT_SIZE)
    lines = bottom_text.strip().split("\n")
    line_heights = []
    for line in lines:
        b = draw.textbbox((0, 0), line, font=bot_font)
        line_heights.append(b[3] - b[1])
    total_h = sum(line_heights) + BOTTOM_LINE_GAP * (len(lines) - 1)
    y = CANVAS - BOTTOM_MARGIN_BOTTOM - total_h
    for line, lh in zip(lines, line_heights):
        draw.text(
            (BOTTOM_MARGIN_LEFT, y),
            line,
            font=bot_font,
            fill="white",
            stroke_width=8,
            stroke_fill=(30, 30, 30, 255),
        )
        y += lh + BOTTOM_LINE_GAP

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path
