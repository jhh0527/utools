# -*- coding: utf-8 -*-
"""파일명에서 SRT(이미지) 번호 추출 → ``SRT_XXX.jpg`` 형식."""

from __future__ import annotations

import re

# 4_1_video ``compose_overrides`` 와 동일한 SRT stem 규칙 (전체 stem)
_SRT_STEM = re.compile(r"^srt[-_]?0*(\d+)$", re.IGNORECASE)
_IMAGE_STEM = re.compile(r"^image[-_]?0*(\d+)$", re.IGNORECASE)
_SCENE_STEM = re.compile(r"^scene[-_]?0*(\d+)$", re.IGNORECASE)
_PLAIN_NUM = re.compile(r"^0*(\d+)$")
# 파일명 맨 앞 2자리 숫자 → SRT 번호 (``00_...`` → 0 → ``SRT_000.jpg``, ``06_...`` → 6)
_LEADING_TWO_DIGITS = re.compile(r"^(\d{2})")

_LEADING_SRT = re.compile(r"^srt[-_]?0*(\d+)", re.IGNORECASE)
_LEADING_IMAGE = re.compile(r"^image[-_]?0*(\d+)", re.IGNORECASE)
_LEADING_SCENE = re.compile(r"^scene[-_]?0*(\d+)", re.IGNORECASE)
_LEADING_INDEX = re.compile(r"^0*(\d+)(?=[-_.])")

_DURATION_TAIL = re.compile(r"[-_.]?(\d+)s(?:ec(?:ond)?s?)?$", re.IGNORECASE)
_ANY_DIGITS = re.compile(r"(\d+)")


def srt_jpg_name(number: int, *, pad: int = 3) -> str:
    """``SRT_000.jpg`` … ``SRT_NNN.jpg`` 형식 출력 파일명 (번호 = 매칭 SRT 시작초)."""
    if number < 0:
        raise ValueError(f"SRT 번호는 0 이상이어야 합니다: {number}")
    return f"SRT_{number:0{pad}d}.jpg"


def _srt_index_int(s: str) -> int | None:
    try:
        n = int(s)
    except ValueError:
        return None
    return n if n >= 0 else None


def _stem_without_duration_suffix(stem: str) -> str:
    return _DURATION_TAIL.sub("", stem)


def extract_first_two_digit_srt_number(path_stem: str) -> int | None:
    """stem 맨 앞 2자리 숫자 (``06_...`` → 6)."""
    m = _LEADING_TWO_DIGITS.match(path_stem.strip())
    if not m:
        return None
    return _srt_index_int(m.group(1))


def extract_srt_number(path_stem: str) -> int | None:
    """파일명만으로 SRT 번호 추정."""
    stem = path_stem.strip()
    if not stem:
        return None

    n2 = extract_first_two_digit_srt_number(stem)
    if n2 is not None:
        return n2

    for pat in (_SRT_STEM, _IMAGE_STEM, _SCENE_STEM, _PLAIN_NUM):
        m = pat.match(stem)
        if m:
            return _srt_index_int(m.group(1))

    for pat in (_LEADING_SRT, _LEADING_IMAGE, _LEADING_SCENE):
        m = pat.match(stem)
        if m:
            return _srt_index_int(m.group(1))

    core = _stem_without_duration_suffix(stem)
    m = _LEADING_INDEX.match(core)
    if m:
        return _srt_index_int(m.group(1))

    hits = [int(g) for g in _ANY_DIGITS.findall(core) if int(g) >= 0]
    if hits:
        return hits[0]
    return None
