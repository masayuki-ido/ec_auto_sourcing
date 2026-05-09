"""Instagram Reels 用の縦動画(9:16, 1080x1920)を生成。

構成:
  - 商品画像をシーンごとに表示(Ken Burns: ゆっくりズーム/パン)
  - 各シーンに白文字×黒角丸ボックスのテキストオーバーレイ
  - ffmpeg で H.264 MP4 にエンコード(IG Reels 仕様)

依存: Pillow, requests, ffmpeg(システム)
"""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from io import BytesIO
from pathlib import Path
from typing import Literal, TypedDict

import requests
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONT_PATH = ROOT / "assets" / "fonts" / "NotoSansJP-Bold.otf"

REEL_W = 1080
REEL_H = 1920
FPS = 30
ZOOM_MAX = 1.15  # Ken Burns の最大ズーム倍率


class Scene(TypedDict, total=False):
    image: str            # URL またはローカルパス
    text: str             # 改行は "\n"
    duration: float       # 秒
    motion: Literal["zoom_in", "zoom_out", "pan_right", "pan_left"]
    text_y_ratio: float   # 0..1, テキストボックスの縦位置(中心)。デフォルト 0.62


def _load_image(url_or_path: str) -> Image.Image:
    if url_or_path.startswith(("http://", "https://")):
        r = requests.get(url_or_path, timeout=30)
        r.raise_for_status()
        return Image.open(BytesIO(r.content)).convert("RGB")
    return Image.open(Path(url_or_path).expanduser().resolve()).convert("RGB")


def _cover_fit(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """target サイズを「覆う」ようにスケール → センタークロップ。"""
    iw, ih = img.size
    scale = max(target_w / iw, target_h / ih)
    nw, nh = int(iw * scale), int(ih * scale)
    img = img.resize((nw, nh), Image.LANCZOS)
    x = (nw - target_w) // 2
    y = (nh - target_h) // 2
    return img.crop((x, y, x + target_w, y + target_h))


def _ken_burns_crop(base: Image.Image, t: float, motion: str) -> Image.Image:
    """base (REEL_W*ZOOM_MAX × REEL_H*ZOOM_MAX) から t 時刻の表示領域をcrop→resize。"""
    bw, bh = base.size

    if motion == "zoom_in":
        scale = ZOOM_MAX - (ZOOM_MAX - 1.0) * t   # 1.15 → 1.00
    elif motion == "zoom_out":
        scale = 1.0 + (ZOOM_MAX - 1.0) * t        # 1.00 → 1.15
    else:
        scale = 1.05

    cw = int(REEL_W * scale)
    ch = int(REEL_H * scale)
    cx = (bw - cw) // 2
    cy = (bh - ch) // 2
    if motion == "pan_right":
        cx = int((bw - cw) * t)
    elif motion == "pan_left":
        cx = int((bw - cw) * (1 - t))

    crop = base.crop((cx, cy, cx + cw, cy + ch))
    return crop.resize((REEL_W, REEL_H), Image.LANCZOS)


def _draw_caption_box(
    canvas: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    y_ratio: float = 0.62,
    padding_x: int = 36,
    padding_y: int = 28,
    radius: int = 18,
    bg_alpha: int = 210,
) -> None:
    """中央揃えの白文字×半透明黒角丸ボックスを描画。"""
    draw = ImageDraw.Draw(canvas, "RGBA")
    lines = text.split("\n")
    line_h = font.size + 14

    widths = []
    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font)
        widths.append(bbox[2] - bbox[0])
    max_w = max(widths) if widths else 0
    total_h = line_h * len(lines)

    box_w = max_w + padding_x * 2
    box_h = total_h + padding_y * 2
    box_x = (REEL_W - box_w) // 2
    box_y = int(REEL_H * y_ratio - box_h / 2)

    draw.rounded_rectangle(
        (box_x, box_y, box_x + box_w, box_y + box_h),
        radius=radius,
        fill=(0, 0, 0, bg_alpha),
    )

    for i, (line, w) in enumerate(zip(lines, widths)):
        x = (REEL_W - w) // 2
        y = box_y + padding_y + i * line_h
        draw.text((x, y), line, font=font, fill="white")


def _font(size: int) -> ImageFont.FreeTypeFont:
    if not FONT_PATH.exists():
        raise FileNotFoundError(f"日本語フォントが見つかりません: {FONT_PATH}")
    return ImageFont.truetype(str(FONT_PATH), size)


def render_text_overlay_png(
    text: str,
    out_path: Path,
    *,
    font_size: int = 62,
    y_ratio: float = 0.62,
) -> Path:
    """テキストボックスだけ描画した透明PNG (1080x1920) を生成。
    動画オーバーレイ用 (ffmpeg overlay フィルタで合成)。
    """
    canvas = Image.new("RGBA", (REEL_W, REEL_H), (0, 0, 0, 0))
    if text:
        _draw_caption_box(canvas, text, _font(font_size), y_ratio=y_ratio)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, "PNG")
    return out_path


def _normalize_clip(src: Path, dst: Path, *, fps: int = FPS) -> Path:
    """AIクリップを 1080x1920 / 指定fps / yuv420p に正規化。"""
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-vf", f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
               f"crop={REEL_W}:{REEL_H},fps={fps}",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "medium",
        "-an",  # 音声なし(後でIGアプリで付ける)
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg normalize failed:\n{result.stderr[-2000:]}")
    return dst


def _overlay_text_on_clip(
    clip: Path, overlay_png: Path, dst: Path, *, fps: int = FPS
) -> Path:
    """クリップにテキストPNGをオーバーレイ。"""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(clip),
        "-i", str(overlay_png),
        "-filter_complex", "[0:v][1:v]overlay=0:0:format=auto",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "medium", "-an",
        str(dst),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg overlay failed:\n{result.stderr[-2000:]}")
    return dst


def compose_ai_reel(
    clips: list[dict],
    out_path: Path,
    *,
    fps: int = FPS,
    font_size: int = 62,
) -> Path:
    """AI生成済みクリップ群にテキストを合成し、1本のリールに連結。

    各クリップ:
      video_path:    Path or str (生成済みMP4)
      text:          str ("\\n" 改行可、空文字でテキストなし)
      text_y_ratio:  float (省略時 0.62)
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が見つかりません")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        composed_paths: list[Path] = []

        for i, c in enumerate(clips):
            src = Path(c["video_path"])
            text = c.get("text", "")
            y_ratio = c.get("text_y_ratio", 0.62)

            normalized = _normalize_clip(src, tmp_dir / f"norm_{i:02d}.mp4", fps=fps)
            if text:
                overlay_png = render_text_overlay_png(
                    text, tmp_dir / f"overlay_{i:02d}.png",
                    font_size=font_size, y_ratio=y_ratio,
                )
                composed = _overlay_text_on_clip(
                    normalized, overlay_png, tmp_dir / f"with_text_{i:02d}.mp4", fps=fps,
                )
            else:
                composed = normalized
            composed_paths.append(composed)

        # concat 用のリストファイル
        concat_list = tmp_dir / "concat.txt"
        concat_list.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in composed_paths),
            encoding="utf-8",
        )

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0",
            "-i", str(concat_list),
            "-c", "copy",
            "-movflags", "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg concat failed:\n{result.stderr[-2000:]}")

    return out_path


def make_reel(
    scenes: list[Scene],
    out_path: Path,
    *,
    fps: int = FPS,
    font_size: int = 62,
) -> Path:
    """シーン群から MP4 を生成。

    各シーン:
      image: URL or path
      text:  オーバーレイ文 ("\\n" 改行可)
      duration: 秒
      motion: zoom_in / zoom_out / pan_right / pan_left (省略時 zoom_in)
      text_y_ratio: 0..1 (省略時 0.62)
    """
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg が見つかりません。`brew install ffmpeg` で導入してください。")

    font = _font(font_size)
    base_w = int(REEL_W * ZOOM_MAX)
    base_h = int(REEL_H * ZOOM_MAX)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_dir = Path(tmp)
        frame_idx = 0

        for scene in scenes:
            img = _load_image(scene["image"])
            base = _cover_fit(img, base_w, base_h)
            duration = float(scene.get("duration", 3.5))
            motion = scene.get("motion", "zoom_in")
            text = scene.get("text", "")
            y_ratio = scene.get("text_y_ratio", 0.62)
            n_frames = max(1, int(duration * fps))

            for i in range(n_frames):
                t = i / max(1, n_frames - 1)
                frame = _ken_burns_crop(base, t, motion)
                if text:
                    _draw_caption_box(frame, text, font, y_ratio=y_ratio)
                frame.save(tmp_dir / f"{frame_idx:05d}.png", "PNG", optimize=False)
                frame_idx += 1

        out_path.parent.mkdir(parents=True, exist_ok=True)
        cmd = [
            "ffmpeg", "-y",
            "-framerate", str(fps),
            "-i", str(tmp_dir / "%05d.png"),
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-crf", "20",
            "-preset", "medium",
            "-movflags", "+faststart",
            str(out_path),
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"ffmpeg failed:\n{result.stderr[-2000:]}")

    return out_path
