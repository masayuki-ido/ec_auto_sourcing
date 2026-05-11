"""Instagram 「○○サコッシュN選」投稿用の画像生成。

レイアウト:
  - カバー(1枚目): タイトル + 黒帯 + サブタイトル + 下部にプレビュー商品画像3枚
  - 商品スライド(2〜N+1枚目): ナビ + 商品画像(背景除去) + 商品名・価格 + 推し理由3点
"""
from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from rembg import remove

from utils.cover_image import (
    CANVAS,
    BG_PALETTE,
    _download,
    _font,
    _get_session,
    _pick_bg,
)

ACCENT_DARK = (30, 30, 30)


def _safe_remove_bg(img: Image.Image) -> Image.Image:
    """背景除去。失敗時は元画像のRGBAを返す。"""
    try:
        return remove(img, session=_get_session())
    except Exception:
        return img.convert("RGBA")


def make_curation_cover(
    theme_title: str,
    theme_subtitle: str,
    audience_label: str,
    preview_images: list[str],
    out_path: Path,
    bg_seed: str = "cover",
) -> Path:
    """5選表紙スライドを生成。"""
    canvas = Image.new("RGB", (CANVAS, CANVAS), (250, 248, 244))
    draw = ImageDraw.Draw(canvas)

    # 上端 audience label (例: 「コスパで選ばない大人の」)
    if audience_label:
        font_aud = _font(50)
        bbox = draw.textbbox((0, 0), audience_label, font=font_aud)
        w = bbox[2] - bbox[0]
        draw.text(((CANVAS - w) // 2, 130), audience_label, font=font_aud, fill="black")

    # 中央 theme_title (黒帯)
    font_title = _font(110)
    bbox = draw.textbbox((0, 0), theme_title, font=font_title)
    title_w = bbox[2] - bbox[0]
    title_h = bbox[3] - bbox[1]
    bar_y = 240
    bar_pad_v = 30
    draw.rectangle(
        (50, bar_y - bar_pad_v, CANVAS - 50, bar_y + title_h + bar_pad_v + 10),
        fill=ACCENT_DARK,
    )
    draw.text(
        ((CANVAS - title_w) // 2, bar_y - 5),
        theme_title,
        font=font_title,
        fill="white",
    )

    # subtitle (- 5選 -)
    font_sub = _font(74)
    sub_text = f"- {theme_subtitle} -"
    bbox = draw.textbbox((0, 0), sub_text, font=font_sub)
    sub_w = bbox[2] - bbox[0]
    draw.text(
        ((CANVAS - sub_w) // 2, bar_y + title_h + bar_pad_v + 60),
        sub_text,
        font=font_sub,
        fill="black",
    )

    # 下部: 商品プレビュー3枚 (背景除去して並べる)
    n = min(3, len(preview_images))
    if n > 0:
        slot_top = 660
        slot_h = 360
        margin = 50
        slot_w = (CANVAS - margin * (n + 1)) // n
        for i, url in enumerate(preview_images[:n]):
            try:
                src = _download(url)
                no_bg = _safe_remove_bg(src)
                bbox_alpha = no_bg.getbbox()
                if bbox_alpha:
                    no_bg = no_bg.crop(bbox_alpha)
                bw, bh = no_bg.size
                if bw <= 0 or bh <= 0:
                    continue
                scale = min(slot_w / bw, slot_h / bh)
                new_w = max(1, int(bw * scale))
                new_h = max(1, int(bh * scale))
                resized = no_bg.resize((new_w, new_h), Image.LANCZOS)
                x = margin + i * (slot_w + margin) + (slot_w - new_w) // 2
                y = slot_top + (slot_h - new_h) // 2
                canvas.paste(resized, (x, y), resized)
            except Exception:
                continue

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path


def _wrap_text(text: str, max_chars: int) -> list[str]:
    """日本語テキストをバランス良く改行。
    - max_chars以下ならそのまま1行
    - 超える場合は2行に均等分割(オーファン文字を避ける)
    """
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]
    # 2行に均等分割。中点近くの句読点・空白・中黒で切る
    target = len(text) // 2
    break_chars = ["、", "。", " ", "・", "/", "ー"]
    best = target
    # target 周辺(±max_chars//2 の範囲)で区切り候補を探し、最も target に近いものを採用
    search_range = max_chars // 2
    candidates: list[int] = []
    for offset in range(0, search_range + 1):
        for sign in (-1, 1):
            pos = target + sign * offset
            if 0 < pos < len(text) and text[pos] in break_chars:
                candidates.append(pos + 1)
    if candidates:
        best = min(candidates, key=lambda x: abs(x - target))
    return [text[:best].rstrip(), text[best:].lstrip()]


def make_product_slide(
    product_image_url: str,
    product_name: str,
    price_text: str,
    reasons: list[str],
    theme_label: str,
    slide_no: int,
    total_slides: int,
    out_path: Path,
    item_id: str = "0",
) -> Path:
    """各商品の紹介スライドを生成。"""
    bg_color = _pick_bg(item_id)
    canvas = Image.new("RGB", (CANVAS, CANVAS), bg_color)
    draw = ImageDraw.Draw(canvas)

    # 上端ナビ: テーマラベル + N/total
    font_nav = _font(34)
    nav_y = 45
    draw.text((55, nav_y), theme_label, font=font_nav, fill="black")
    no_text = f"{slide_no}/{total_slides}"
    bbox = draw.textbbox((0, 0), no_text, font=font_nav)
    nw = bbox[2] - bbox[0]
    draw.text((CANVAS - 55 - nw, nav_y), no_text, font=font_nav, fill="black")

    # 商品画像エリア (上部)
    image_top = 120
    image_bottom = 660
    image_h = image_bottom - image_top
    image_w = CANVAS - 100
    try:
        src = _download(product_image_url)
        no_bg = _safe_remove_bg(src)
        bbox_alpha = no_bg.getbbox()
        if bbox_alpha:
            no_bg = no_bg.crop(bbox_alpha)
        bw, bh = no_bg.size
        if bw > 0 and bh > 0:
            scale = min(image_w / bw, image_h / bh)
            new_w = max(1, int(bw * scale))
            new_h = max(1, int(bh * scale))
            resized = no_bg.resize((new_w, new_h), Image.LANCZOS)
            x = (CANVAS - new_w) // 2
            y = image_top + (image_h - new_h) // 2
            canvas.paste(resized, (x, y), resized)
    except Exception:
        pass

    # 商品名 (中央寄せ、最大2行)
    name_y = 690
    font_name = _font(34)
    name_lines = _wrap_text(product_name, max_chars=22)[:2]
    for i, line in enumerate(name_lines):
        bbox = draw.textbbox((0, 0), line, font=font_name)
        w = bbox[2] - bbox[0]
        draw.text(((CANVAS - w) // 2, name_y + i * 44), line, font=font_name, fill="black")

    # 価格 (大きく中央)
    price_y = name_y + (len(name_lines) * 44) + 8
    font_price = _font(70)
    bbox = draw.textbbox((0, 0), price_text, font=font_price)
    pw = bbox[2] - bbox[0]
    draw.text(((CANVAS - pw) // 2, price_y), price_text, font=font_price, fill=ACCENT_DARK)

    # 推し理由 (3点、左揃え)
    reasons_y = price_y + 95
    font_reason = _font(27)
    reason_marks = ["①", "②", "③"]
    for i, reason in enumerate(reasons[:3]):
        prefix = reason_marks[i] if i < len(reason_marks) else f"{i + 1}."
        line = f"{prefix} {reason}"
        # 横幅に収まる程度に切り詰め
        max_chars = 30
        if len(line) > max_chars:
            line = line[: max_chars - 1] + "…"
        draw.text((75, reasons_y + i * 38), line, font=font_reason, fill="black")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "JPEG", quality=88, optimize=True)
    return out_path
