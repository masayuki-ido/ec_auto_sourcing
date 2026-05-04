"""Instagram投稿用の表紙画像を生成 (Pillow + rembg)。

マガジン風レイアウト:
  - 単色背景に、商品画像を背景除去して中央配置
  - 上部: 【cover_top】 黒文字
  - 左縦書き: cover_left (素材など)
  - 右縦書き: cover_right (キャッチなど)
  - 下部中央: 価格バッジ
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import numpy as np
import requests
from PIL import Image, ImageDraw, ImageFont
from rembg import remove, new_session

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "NotoSansJP-Bold.otf"

CANVAS = 1080

# 背景色パレット(日本のファッションIGで多用される、商品が映える落ち着き色)
BG_PALETTE = [
    (181, 219, 200),  # mint
    (245, 200, 200),  # dusty pink
    (232, 197, 108),  # mustard
    (197, 197, 197),  # warm gray
    (232, 221, 200),  # beige
    (168, 184, 158),  # sage
    (220, 210, 230),  # lavender
    (255, 218, 185),  # peach
]

# rembg セッション (使い回しで高速化)
_session = None

def _get_session():
    global _session
    if _session is None:
        _session = new_session("u2netp")  # 軽量モデル(~5MB)、商品なら十分
    return _session


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


def _pick_bg(seed: str) -> tuple[int, int, int]:
    """item_id から決定論的に背景色を選ぶ(同じ商品=同じ色)"""
    h = int(hashlib.md5(seed.encode()).hexdigest(), 16)
    return BG_PALETTE[h % len(BG_PALETTE)]


def _draw_vertical(
    draw: ImageDraw.ImageDraw,
    x: int,
    text: str,
    font: ImageFont.FreeTypeFont,
    canvas_h: int,
    fill: str = "black",
) -> None:
    """文字を1文字ずつ縦に並べる(中央寄せ)"""
    chars = list(text)
    char_h = font.size + 4
    total_h = char_h * len(chars)
    start_y = (canvas_h - total_h) // 2
    for i, c in enumerate(chars):
        bbox = draw.textbbox((0, 0), c, font=font)
        char_w = bbox[2] - bbox[0]
        # 各文字を x を中心に左右調整
        draw.text(
            (x - char_w // 2, start_y + i * char_h),
            c,
            font=font,
            fill=fill,
        )


def make_cover(
    image_url: str,
    top_text: str,
    bottom_text: str,
    out_path: Path,
    *,
    item_id: str = "0",
    price: str = "",
    cover_left: str = "",
    cover_right: str = "",
) -> Path:
    """マガジン風カバー画像を生成。

    後方互換のため bottom_text は旧フィールドだが、
    cover_left/cover_right が指定されない場合は bottom_text を縦書き2分割で使う。
    """
    # 背景色決定 (item_id ハッシュ)
    bg_color = _pick_bg(item_id)

    # 商品画像ダウンロード → 背景除去(元のアスペクト比のまま)
    src = _download(image_url)
    no_bg = remove(src, session=_get_session())  # RGBA, original size

    # alpha の重心(主にバッグ本体に偏る)を中心とする対称crop
    # → ストラップが片側に長くても、バッグ本体が画像中央に来る
    alpha = np.array(no_bg.split()[-1])
    ys, xs = np.where(alpha > 30)
    if len(ys) > 0:
        x_min, x_max = int(xs.min()), int(xs.max())
        y_min, y_max = int(ys.min()), int(ys.max())
        # 重心は alpha 値で重み付け (バッグ本体の方が密度が高い)
        weights = alpha[ys, xs].astype(np.float64)
        com_x = int(np.average(xs, weights=weights))
        com_y = int(np.average(ys, weights=weights))
        # 重心からの最大半径で対称bboxを作る
        half_w = max(com_x - x_min, x_max - com_x)
        half_h = max(com_y - y_min, y_max - com_y)
        crop_box = (
            com_x - half_w,
            com_y - half_h,
            com_x + half_w,
            com_y + half_h,
        )
        # キャンバス外も含む対称領域を確保するため、必要なら透明パディングを足してからcrop
        pad_left = max(0, -crop_box[0])
        pad_top = max(0, -crop_box[1])
        pad_right = max(0, crop_box[2] - no_bg.width)
        pad_bottom = max(0, crop_box[3] - no_bg.height)
        if any([pad_left, pad_top, pad_right, pad_bottom]):
            new_w = no_bg.width + pad_left + pad_right
            new_h = no_bg.height + pad_top + pad_bottom
            padded = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
            padded.paste(no_bg, (pad_left, pad_top))
            no_bg = padded
            crop_box = (
                crop_box[0] + pad_left,
                crop_box[1] + pad_top,
                crop_box[2] + pad_left,
                crop_box[3] + pad_top,
            )
        no_bg = no_bg.crop(crop_box)
    else:
        # rembg失敗時のフォールバック
        bbox = no_bg.getbbox()
        if bbox:
            no_bg = no_bg.crop(bbox)

    # アスペクト比保持で内側エリアにフィット
    PAD = 100
    inner = CANVAS - PAD * 2
    bw, bh = no_bg.size
    scale = min(inner / bw, inner / bh)
    new_w, new_h = max(1, int(bw * scale)), max(1, int(bh * scale))
    no_bg_fit = no_bg.resize((new_w, new_h), Image.LANCZOS)

    # 単色背景キャンバスに配置。商品本体を画面中央よりやや下に置く(下三分の一エリア)
    canvas = Image.new("RGB", (CANVAS, CANVAS), bg_color)
    paste_x = (CANVAS - new_w) // 2
    paste_y = (CANVAS - new_h) // 2 + 100  # 下方向オフセット
    canvas.paste(no_bg_fit, (paste_x, paste_y), no_bg_fit)

    draw = ImageDraw.Draw(canvas, "RGBA")

    # ─── 上部 【top_text】 ────────────
    top_str = f"【{top_text}】"
    top_font = _font(58)
    bbox = draw.textbbox((0, 0), top_str, font=top_font)
    top_w = bbox[2] - bbox[0]
    draw.text(((CANVAS - top_w) // 2, 40), top_str, font=top_font, fill="black")

    # ─── 左右縦書き ────────────
    # cover_left/right 未指定なら bottom_text を改行で分割
    if not cover_left and not cover_right:
        parts = (bottom_text or "").split("\n")
        cover_left = parts[0] if parts else ""
        cover_right = parts[1] if len(parts) > 1 else ""

    vert_font = _font(110)
    if cover_left:
        _draw_vertical(draw, x=80, text=cover_left, font=vert_font, canvas_h=CANVAS)
    if cover_right:
        _draw_vertical(draw, x=CANVAS - 80, text=cover_right, font=vert_font, canvas_h=CANVAS)

    # ─── 下部 価格バッジ ────────────
    if price:
        price_str = price
        price_font = _font(72)
        bbox_p = draw.textbbox((0, 0), price_str, font=price_font)
        pw = bbox_p[2] - bbox_p[0]
        ph = bbox_p[3] - bbox_p[1]
        # 白丸風背景
        cx, cy = CANVAS // 2, CANVAS - 110
        r = max(pw, ph) // 2 + 30
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 255, 255, 235))
        draw.text((cx - pw // 2, cy - ph // 2 - 8), price_str, font=price_font, fill="black")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path
