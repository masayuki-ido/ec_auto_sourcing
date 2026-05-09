"""画像→動画(Image-to-Video) を Replicate API で生成。

使い方:
    from utils.ai_video import generate_clip
    clip_path = generate_clip(
        image_url="https://....jpg",
        prompt="A black sacoche bag swaying gently on its strap",
        out_path=Path("data/instagram/reels/clips/scene1.mp4"),
        duration=5,
    )

環境変数:
    REPLICATE_API_TOKEN
"""
from __future__ import annotations

import os
from pathlib import Path

import replicate
import requests

# 推奨モデル(コスト・品質バランス)。後で差し替え可。
DEFAULT_MODEL = "bytedance/seedance-1-pro"

# モデルごとの input スキーマ差を吸収
_MODEL_INPUT_BUILDERS = {
    "bytedance/seedance-1-pro": lambda image, prompt, duration, ratio: {
        "image": image,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": ratio,
        "resolution": "1080p",
        "fps": 24,
    },
    "wan-video/wan-2.5-i2v-fast": lambda image, prompt, duration, ratio: {
        "image": image,
        "prompt": prompt,
        "duration": duration,
        "resolution": "720p",
    },
    "kwaivgi/kling-v2.1": lambda image, prompt, duration, ratio: {
        "start_image": image,
        "prompt": prompt,
        "duration": duration,
        "aspect_ratio": ratio,
    },
}


def _build_input(model: str, image: str, prompt: str, duration: int, aspect_ratio: str) -> dict:
    builder = _MODEL_INPUT_BUILDERS.get(model)
    if builder:
        return builder(image, prompt, duration, aspect_ratio)
    # フォールバック
    return {"image": image, "prompt": prompt, "duration": duration}


def _save_output(output, out_path: Path) -> Path:
    """Replicate の出力(FileOutput / str URL / list)を MP4 として保存。"""
    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Replicate SDK 1.0+ は FileOutput を返す
    if hasattr(output, "read"):
        out_path.write_bytes(output.read())
        return out_path

    if isinstance(output, list) and output:
        output = output[0]

    if isinstance(output, str) and output.startswith(("http://", "https://")):
        r = requests.get(output, timeout=180)
        r.raise_for_status()
        out_path.write_bytes(r.content)
        return out_path

    raise RuntimeError(f"想定外の Replicate 出力形式: {type(output)} / {output!r:.200s}")


def generate_clip(
    image_url: str,
    prompt: str,
    out_path: Path,
    *,
    model: str = DEFAULT_MODEL,
    duration: int = 5,
    aspect_ratio: str = "9:16",
) -> Path:
    """画像URLから duration 秒のMP4クリップを生成。

    image_url: 公開URL (Replicateからアクセス可能なこと)
    prompt:    動きの英語指示。例 "A black sacoche bag swaying gently"
    duration:  秒(モデル依存。Seedance 5/10、Kling 5/10、Wan 5)
    aspect_ratio: "9:16" / "16:9" / "1:1"
    """
    if not os.getenv("REPLICATE_API_TOKEN"):
        raise RuntimeError("REPLICATE_API_TOKEN が環境変数にありません(.env を確認)")

    inputs = _build_input(model, image_url, prompt, duration, aspect_ratio)
    output = replicate.run(model, input=inputs)
    return _save_output(output, out_path)
