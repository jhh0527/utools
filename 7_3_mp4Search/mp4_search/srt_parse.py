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


def format_ms_ts(ms: int) -> str:
    ms = max(0, int(ms))
    sec, milli = divmod(ms, 1000)
    mi, sec = divmod(sec, 60)
    h, mi = divmod(mi, 60)
    return f"{h:02d}:{mi:02d}:{sec:02d},{milli:03d}"


def format_ms_short(ms: int) -> str:
    ms = max(0, int(ms))
    sec, _z = divmod(ms, 1000)
    mi, sec = divmod(sec, 60)
    h, mi = divmod(mi, 60)
    if h:
        return f"{h}:{mi:02d}:{sec:02d}"
    return f"{mi}:{sec:02d}"


def parse_srt_cues(path: Path) -> list[tuple[int, str]]:
    """``(srt_map_id, text)``."""
    return [(c[0], c[1]) for c in parse_srt_cues_timed(path)]


def parse_srt_cues_timed(path: Path) -> list[tuple[int, str, int, int]]:
    """``(srt_map_id, text, start_ms, end_ms)``."""
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
    cues: list[tuple[int, str, int, int]] = []
    if not raw:
        return cues
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln is not None]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        left, _, right = lines[1].partition("-->")
        try:
            st = parse_srt_timestamp_ms(left)
            end_part = right.strip().split()[0] if right.strip() else left
            en = parse_srt_timestamp_ms(end_part)
        except ValueError:
            continue
        head = lines[0].strip()
        if head.isdigit() and int(head) >= 0:
            map_id = int(head)
        else:
            map_id = max(0, st // 1000)
        text = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        cues.append((map_id, text, st, en))
    return cues
