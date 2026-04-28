"""
Pillow を使った画像の主要色（ドミナントカラー）抽出ユーティリティ
"""
from __future__ import annotations
import io
import math
import logging
from collections import Counter

from PIL import Image

from config import COLOR_MAP, COLOR_TOLERANCE

logger = logging.getLogger(__name__)

# 抽出する主要色の最大数
TOP_N_COLORS = 3
# 量子化のパレット数（大きいほど精度UP、速度DOWN）
QUANTIZE_COLORS = 16
# 背景とみなすカラー（白・透明付近）を除外するための閾値
BG_BRIGHTNESS_THRESHOLD = 240


def extract_dominant_colors(image_bytes: bytes, top_n: int = TOP_N_COLORS) -> list[tuple[int, int, int]]:
    """
    画像バイト列から主要色 top_n 個を RGB タプルのリストで返す。

    Args:
        image_bytes: 画像のバイト列
        top_n: 返す色の数

    Returns:
        [(R, G, B), ...] 出現頻度の高い順
    """
    try:
        img = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        # パレット量子化で色数を削減してからカウント
        quantized = img.quantize(colors=QUANTIZE_COLORS).convert("RGB")
        pixels = list(quantized.getdata())

        # 白・明度高すぎる背景色を除外
        filtered = [
            p for p in pixels
            if not _is_background(p)
        ]
        if not filtered:
            filtered = pixels  # 全部除外されたら戻す

        counts = Counter(filtered)
        dominant = [color for color, _ in counts.most_common(top_n)]
        logger.debug(f"主要色抽出: {dominant}")
        return dominant

    except Exception as e:
        logger.warning(f"色抽出失敗: {e}")
        return []


def _is_background(rgb: tuple[int, int, int]) -> bool:
    """白・明るすぎるピクセルを背景とみなす。"""
    r, g, b = rgb
    brightness = (r + g + b) / 3
    return brightness > BG_BRIGHTNESS_THRESHOLD


def rgb_to_color_name(rgb: tuple[int, int, int]) -> str | None:
    """
    RGB タプルを COLOR_MAP のカラー名にマッピングする。
    許容距離内に収まるものがなければ None を返す。

    Args:
        rgb: (R, G, B)

    Returns:
        カラー名 or None
    """
    best_name = None
    best_dist = float("inf")

    for name, ref_rgb in COLOR_MAP.items():
        dist = _color_distance(rgb, ref_rgb)
        if dist < best_dist:
            best_dist = dist
            best_name = name

    if best_dist <= COLOR_TOLERANCE:
        return best_name
    return None


def _color_distance(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    """2つの RGB タプル間のユークリッド距離を返す。"""
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def get_color_names_from_image(image_bytes: bytes) -> list[str]:
    """
    画像から抽出した主要色を COLOR_MAP のカラー名リストに変換する。
    マッピングできなかった色は除外される。

    Returns:
        重複なしカラー名のリスト
    """
    dominant = extract_dominant_colors(image_bytes)
    names = []
    for rgb in dominant:
        name = rgb_to_color_name(rgb)
        if name and name not in names:
            names.append(name)
    return names
