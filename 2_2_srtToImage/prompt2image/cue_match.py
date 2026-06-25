# -*- coding: utf-8 -*-
"""OCR 텍스트와 대본 일치 여부."""

from __future__ import annotations

import sys


def _ensure_png_rename_path() -> None:
    from wisdom_root import resolve_wisdom_root

    root = resolve_wisdom_root() / "3_1_pngFileName"
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


def ocr_matches_cue(ocr_preview: str, cue_text: str) -> bool:
    """OCR 단어가 해당 대본에 하나라도 포함되면 일치."""
    if not (ocr_preview or "").strip() or not (cue_text or "").strip():
        return False
    _ensure_png_rename_path()
    from png_rename.text_norm import ocr_words_in_cue_text

    ok, _matched = ocr_words_in_cue_text(ocr_preview, cue_text)
    return ok
