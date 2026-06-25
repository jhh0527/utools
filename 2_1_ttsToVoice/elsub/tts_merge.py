# -*- coding: utf-8 -*-
"""TTS 줄 병합: 문장부호·호흡 태그로 끊고, 이어 읽을 줄만 한 API 호출로 합성."""

from __future__ import annotations

import re

from elsub.elevenlabs_client import strip_tts_tags
from elsub.parser import CaptionLine

# 마침표·쉼표·느낌표·물음표·콜론·세미콜론·말줄임(ASCII·전각·일부 CJK)
_PAUSE_END_CHARS = frozenset(
    ".,!?;:…"
    "．，、！？：；"
    "」』\"')】〉"
)

_LEADING_PART_OPENER_RE = re.compile(
    r"^\s*\[short pause\]\s*\[breathes\]\s*\[continues\]\s*",
    re.IGNORECASE,
)
_LEADING_PAUSE_TAG_RE = re.compile(
    r"^\s*\[(?:short pause|breathes)(?:\]\s*\[(?:breathes|continues))*\]",
    re.IGNORECASE,
)
_LEADING_TAG_STRIP_PATTERNS = (
    r"^\s*\[short pause\]\s*\[breathes\]\s*\[continues\]\s*",
    r"^\s*\[short pause\]\s*\[breathes\]\s*",
    r"^\s*\[short pause\]\s*",
    r"^\s*\[breathes\]\s*",
    r"^\s*\[continues\]\s*",
)
_LEADING_CONTINUES_RE = re.compile(r"^\s*\[continues\]\s*", re.IGNORECASE)
_TRAILING_PAUSE_TAG_RE = re.compile(r"\[(?:short pause|breathes)\]\s*$", re.IGNORECASE)


def tts_has_leading_pause_marker(tts: str) -> bool:
    """TTS 앞에 ``[short pause]``·``[breathes]`` 계열이 있으면 True."""
    return bool(_LEADING_PAUSE_TAG_RE.match(tts.strip()))


def leading_pause_ms(tts: str) -> int:
    """TTS 맨 앞 호흡·쉼 태그에 대응하는 무음 길이(ms). API 선행 ``<break>`` 대신 ffmpeg 무음용."""
    s = tts.strip()
    if _LEADING_PART_OPENER_RE.match(s):
        return 1000
    if re.match(r"^\s*\[short pause\]\s*\[breathes\]", s, re.IGNORECASE):
        return 1000
    if re.match(r"^\s*\[short pause\]", s, re.IGNORECASE):
        return 400
    if re.match(r"^\s*\[breathes\]", s, re.IGNORECASE):
        return 500
    return 0


def remove_leading_pause_tags(tts: str) -> str:
    """맨 앞 쉼·호흡 태그만 제거(본문·줄 중간 태그는 유지)."""
    s = tts.strip()
    while True:
        changed = False
        for pat in _LEADING_TAG_STRIP_PATTERNS:
            ns = re.sub(pat, "", s, count=1, flags=re.IGNORECASE)
            if ns != s:
                s = ns
                changed = True
                break
        if not changed:
            break
    return s.strip()


def tts_synthesis_weight(tts: str) -> int:
    """합성 MP3 길이를 줄별로 나눌 때 선행 무음 구간을 반영한 가중치."""
    w = len(strip_tts_tags(tts).strip()) or 1
    pause = leading_pause_ms(tts)
    if pause:
        w += max(8, pause // 40)
    return w


def tts_has_trailing_pause_marker(tts: str) -> bool:
    """TTS 끝에 ``[breathes]``·``[short pause]`` 가 있으면 True."""
    return bool(_TRAILING_PAUSE_TAG_RE.search(tts.strip()))


def tts_ends_with_pause_punctuation(tts: str) -> bool:
    """문장·호흡 태그·파트 단위 끊김이면 True (다음 줄을 새 합성 묶음으로)."""
    s = tts.strip()
    if tts_has_trailing_pause_marker(s):
        return True
    plain = strip_tts_tags(s).strip()
    if plain and plain[-1] in _PAUSE_END_CHARS:
        return True
    if re.search(r"\[short pause\]", s, re.IGNORECASE):
        return True
    return False


def strip_trailing_line_breath_tags(tts: str) -> str:
    """줄바꿈용 끝 ``[breathes]``·``[short pause]`` 제거(이어 읽기 시 자연스럽게 붙임)."""
    return _TRAILING_PAUSE_TAG_RE.sub("", tts.strip()).rstrip()


def strip_leading_continues_marker(tts: str) -> str:
    """같은 묶음 다음 줄 앞 ``[continues]`` 제거."""
    return _LEADING_CONTINUES_RE.sub("", tts.strip())


def group_entries_for_synthesis(entries: list[CaptionLine]) -> list[list[CaptionLine]]:
    """이전 줄이 끊김 지점이면 다음 줄을 새 합성 묶음으로 시작합니다."""
    if not entries:
        return []
    groups: list[list[CaptionLine]] = [[entries[0]]]
    for e in entries[1:]:
        if tts_has_leading_pause_marker(e.tts):
            groups.append([e])
        elif tts_ends_with_pause_punctuation(groups[-1][-1].tts):
            groups.append([e])
        else:
            groups[-1].append(e)
    return groups


def merge_group_tts(group: list[CaptionLine]) -> str:
    """한 묶음 TTS. 문장부호 없이 이어지는 줄은 공백으로 이어 한 번에 낭독합니다."""
    if not group:
        return ""
    if len(group) == 1:
        return group[0].tts
    parts: list[str] = [group[0].tts]
    for prev, curr in zip(group, group[1:]):
        if not tts_ends_with_pause_punctuation(prev.tts):
            parts[-1] = strip_trailing_line_breath_tags(parts[-1])
            parts.append(strip_leading_continues_marker(curr.tts))
        else:
            parts.append(curr.tts)
    return " ".join(p.strip() for p in parts if p.strip())


def split_duration_ms(total_ms: int, weights: list[int], *, min_ms: int = 1) -> list[int]:
    """묶음 MP3 길이를 줄별 가중치(예: 글자 수)로 나눕니다."""
    if not weights:
        return []
    if len(weights) == 1:
        return [max(min_ms, int(total_ms))]
    w = [max(1, int(x)) for x in weights]
    s = sum(w)
    scaled = [max(min_ms, int(round(total_ms * x / s))) for x in w]
    drift = int(total_ms) - sum(scaled)
    scaled[-1] = max(min_ms, scaled[-1] + drift)
    return scaled
