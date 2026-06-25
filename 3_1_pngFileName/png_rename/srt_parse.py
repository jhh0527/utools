# -*- coding: utf-8 -*-
"""SRT 자막 파싱."""

from __future__ import annotations

import re
from pathlib import Path

_TS = re.compile(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$")


def parse_srt_timestamp_ms(ts: str) -> int:
    ts = ts.strip().replace(".", ",")
    m = _TS.match(ts)
    if not m:
        raise ValueError(f"SRT 타임스탬프 형식이 아닙니다: {ts!r}")
    h, mi, s, z = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return ((h * 60 + mi) * 60 + s) * 1000 + z


def parse_srt_cues(path: Path) -> list[tuple[int, str]]:
    """``(srt_map_id, text)`` — map_id 는 자막 블록 첫 줄 번호(시작초와 동일한 경우가 많음)."""
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
    cues: list[tuple[int, str]] = []
    if not raw:
        return cues
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln is not None]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        left, _, _right = lines[1].partition("-->")
        try:
            st = parse_srt_timestamp_ms(left)
        except ValueError:
            continue
        head = lines[0].strip()
        if head.isdigit() and int(head) >= 0:
            map_id = int(head)
        else:
            map_id = max(0, st // 1000)
        text = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        cues.append((map_id, text))
    return cues


def search_srt_cues(
    path: Path,
    keyword: str,
) -> list[tuple[int, str]]:
    """키워드가 포함된 대본 항목 ``(번호, 텍스트)``."""
    kw = keyword.strip().lower()
    if not kw:
        return []
    hits: list[tuple[int, str]] = []
    for map_id, text in parse_srt_cues(path):
        blob = f"{map_id} {text}".lower()
        if kw in blob:
            hits.append((map_id, text))
    hits.sort(key=lambda h: int(h[0]))
    return hits


def nearest_cue_id(value: int, cue_ids: list[int]) -> int:
    """``cue_ids`` 중 ``value`` 와 숫자 차이가 가장 작은 대본 번호."""
    if not cue_ids:
        return value
    return min(cue_ids, key=lambda cid: abs(int(cid) - int(value)))
