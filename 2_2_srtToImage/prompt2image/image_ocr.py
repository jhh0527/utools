# -*- coding: utf-8 -*-
"""미리보기용 OCR (한글 단어, 쉼표 구분)."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_png_rename_path() -> None:
    from wisdom_root import resolve_wisdom_root

    root = resolve_wisdom_root() / "3_1_pngFileName"
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


def ocr_comma_words(path: Path) -> str:
    """이미지에서 인식한 한글·단어를 쉼표로 연결."""
    _ensure_png_rename_path()
    from png_rename.ocr import analyze_image_text, format_ocr_display

    ocr_text, sized = analyze_image_text(path)
    preview = format_ocr_display(sized, ocr_text).strip()
    if preview:
        return preview
    return "(인식된 단어 없음)"
