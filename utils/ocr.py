"""
EasyOCR を使った画像テキスト検出ユーティリティ
"""
from __future__ import annotations
import logging
import io
from pathlib import Path

import easyocr
from PIL import Image

from config import EXCLUDED_LANGUAGES, OCR_CONFIDENCE_THRESHOLD

logger = logging.getLogger(__name__)

# EasyOCR Reader はコスト高なので一度だけ初期化する
# ch_sim=簡体字, ch_tra=繁体字, en=英語（補助）
_reader: easyocr.Reader | None = None


def _get_reader() -> easyocr.Reader:
    global _reader
    if _reader is None:
        logger.info("EasyOCR Reader を初期化中（初回のみ時間がかかります）...")
        _reader = easyocr.Reader(["ch_sim", "ch_tra", "en"], gpu=False)
    return _reader


def has_chinese_text(image_bytes: bytes) -> bool:
    """
    画像バイト列に中国語テキストが含まれるか判定する。

    Args:
        image_bytes: 画像のバイト列

    Returns:
        True: 中国語テキストが検出された（除外すべき）
        False: 検出されなかった（通過）
    """
    reader = _get_reader()

    try:
        results = reader.readtext(image_bytes, detail=1)
        for _bbox, text, confidence in results:
            if confidence < OCR_CONFIDENCE_THRESHOLD:
                continue
            if _is_chinese(text):
                logger.debug(f"中国語検出: 「{text}」(信頼度:{confidence:.2f})")
                return True
    except Exception as e:
        logger.warning(f"OCR処理失敗（スキップ）: {e}")

    return False


def _is_chinese(text: str) -> bool:
    """文字列に中国語文字が含まれるか判定（Unicode範囲で判定）。"""
    for ch in text:
        cp = ord(ch)
        # CJK統合漢字: U+4E00–U+9FFF
        # CJK拡張A:    U+3400–U+4DBF
        # CJK拡張B:    U+20000–U+2A6DF
        if 0x4E00 <= cp <= 0x9FFF or 0x3400 <= cp <= 0x4DBF or 0x20000 <= cp <= 0x2A6DF:
            return True
    return False


def check_image_size(image_bytes: bytes, min_short_side: int) -> bool:
    """
    画像の短辺が最小サイズ以上かチェックする。

    Returns:
        True: サイズOK（通過）
        False: サイズ不足（除外）
    """
    try:
        img = Image.open(io.BytesIO(image_bytes))
        short_side = min(img.size)
        if short_side < min_short_side:
            logger.debug(f"画像サイズ不足: 短辺 {short_side}px < {min_short_side}px")
            return False
        return True
    except Exception as e:
        logger.warning(f"画像サイズ確認失敗: {e}")
        return False
