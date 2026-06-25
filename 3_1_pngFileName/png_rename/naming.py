# -*- coding: utf-8 -*-
"""``SRT_XXX.png`` 출력 파일명."""

from __future__ import annotations

import re

_SRT_STEM = re.compile(r"^srt[-_]?0*(\d+)\.png$", re.IGNORECASE)
_SRT_JUNK_STEM = re.compile(r"^srt[-_]?0*(\d+)_.+\.png$", re.IGNORECASE)


def srt_png_name(number: int, *, pad: int = 3) -> str:
    if number < 0:
        raise ValueError(f"SRT 번호는 0 이상이어야 합니다: {number}")
    return f"SRT_{number:0{pad}d}.png"


def is_clean_srt_png_name(name: str) -> bool:
    """``SRT_XXX.png`` 형식(접미사 없음)이면 True."""
    return _SRT_STEM.match(name or "") is not None


def parse_srt_number_from_filename(name: str) -> int | None:
    """``SRT_XXX.png`` 또는 ``SRT_XXX_쓰레기.png`` 에서 번호 추출."""
    m = _SRT_STEM.match(name or "")
    if m:
        return int(m.group(1))
    m = _SRT_JUNK_STEM.match(name or "")
    if m:
        return int(m.group(1))
    return None


def normalized_srt_png_name(name: str, *, pad: int = 3) -> str | None:
    """``SRT_XXX_접미사.png`` → ``SRT_XXX.png``. 이미 정규 형식이면 ``None``."""
    if is_clean_srt_png_name(name):
        return None
    m = _SRT_JUNK_STEM.match(name or "")
    if not m:
        return None
    return srt_png_name(int(m.group(1)), pad=pad)
