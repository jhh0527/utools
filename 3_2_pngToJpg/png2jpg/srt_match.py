# -*- coding: utf-8 -*-
"""``3. SRT_image.md`` 타임스탬프 → SRT 번호 매칭 (4-2절 알고리즘)."""

from __future__ import annotations

import re
from pathlib import Path

# 파일명: ``06_timestamp_120s_bear`` / ``06_timestamp_01_43_096_bear``
_TIMESTAMP_SEC = re.compile(
    r"timestamp[-_]?(?P<sec>\d+)s(?:ec(?:ond)?s?)?",
    re.IGNORECASE,
)
# ``timestamp_00_01_43_096`` → 00:01:43,096
_TIMESTAMP_HHMMSS = re.compile(
    r"timestamp[-_]?"
    r"(?P<h>\d{2})[-_.](?P<m>\d{2})[-_.](?P<s>\d{2})[-_.](?P<ms>\d{3})",
    re.IGNORECASE,
)
# ``timestamp_01_43_096`` → 01분 43.096초 (SRT 00:01:43,096 과 동일)
_TIMESTAMP_MMSS = re.compile(
    r"timestamp[-_]?"
    r"(?P<m>\d{2})[-_.](?P<s>\d{2})[-_.](?P<ms>\d{3})",
    re.IGNORECASE,
)


def parse_srt_timestamp_ms(ts: str) -> int:
    """``HH:MM:SS,mmm`` → 밀리초."""
    ts = ts.strip().replace(".", ",")
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", ts)
    if not m:
        raise ValueError(f"SRT 타임스탬프 형식이 아닙니다: {ts!r}")
    h, mi, s, z = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return ((h * 60 + mi) * 60 + s) * 1000 + z


def parse_srt_cues(path: Path) -> list[tuple[int, int, int, str]]:
    """``(srt_map_id, start_ms, end_ms, text)`` 리스트."""
    raw = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "\n").strip()
    cues: list[tuple[int, int, int, str]] = []
    if not raw:
        return cues
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln is not None]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        left, _, right = lines[1].partition("-->")
        try:
            st = parse_srt_timestamp_ms(left)
            en = parse_srt_timestamp_ms(right)
        except ValueError:
            continue
        head = lines[0].strip()
        if head.isdigit() and int(head) >= 0:
            map_id = int(head)
        else:
            map_id = max(0, st // 1000)
        text = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        cues.append((map_id, st, en, text))
    return cues


def extract_timestamp_ms_from_stem(stem: str) -> int | None:
    """``timestamp`` 가 포함된 파일명에서 영상 시각(밀리초)을 추출합니다.

    - ``06_timestamp_120s_bear`` → 120초 (120000ms)
    - ``06_timestamp_01_43_096_bear`` → 00:01:43,096
    """
    if "timestamp" not in stem.lower():
        return None

    m = _TIMESTAMP_HHMMSS.search(stem)
    if m:
        h = int(m.group("h"))
        mi = int(m.group("m"))
        s = int(m.group("s"))
        ms = int(m.group("ms"))
        return ((h * 60 + mi) * 60 + s) * 1000 + ms

    m = _TIMESTAMP_MMSS.search(stem)
    if m:
        mi = int(m.group("m"))
        s = int(m.group("s"))
        ms = int(m.group("ms"))
        return (mi * 60 + s) * 1000 + ms

    m = _TIMESTAMP_SEC.search(stem)
    if m:
        return int(m.group("sec")) * 1000

    return None


def match_srt_at_timestamp_ms(
    cues: list[tuple[int, int, int, str]],
    t_ms: int,
    used_map_ids: set[int],
) -> int | None:
    """``3. SRT_image.md`` 4-2절: 타임스탬프 T 에 맞는 SRT 표시 번호(map_id).

    1) 시작시간 ≤ T 이고 아직 미사용인 항목 중 시작시간이 가장 큰 것
    2) 없으면 시작시간 > T 이고 미사용인 항목 중 시작시간이 가장 작은 것
    """
    if not cues:
        return None

    before = [(mid, st) for mid, st, _en, _tx in cues if st <= t_ms and mid not in used_map_ids]
    if before:
        return max(before, key=lambda x: x[1])[0]

    after = [(mid, st) for mid, st, _en, _tx in cues if st > t_ms and mid not in used_map_ids]
    if after:
        return min(after, key=lambda x: x[1])[0]

    return None


def resolve_output_srt_number(
    stem: str,
    cues: list[tuple[int, int, int, str]],
    used_map_ids: set[int],
    *,
    fallback_from_name: int | None = None,
) -> tuple[int | None, str]:
    """출력 SRT 번호와 출처 설명."""
    t_ms = extract_timestamp_ms_from_stem(stem)
    if t_ms is not None:
        sec_n = max(0, int(t_ms) // 1000)
        if sec_n in used_map_ids:
            return None, f"SRT_{sec_n:03d} 번호 중복"
        if cues:
            mid = match_srt_at_timestamp_ms(cues, t_ms, used_map_ids)
            if mid is not None:
                sec = t_ms / 1000.0
                return sec_n, f"SRT 매칭 T={sec:.3f}s→SRT_{sec_n:03d}"
        return sec_n, f"타임스탬프 {sec_n}s→SRT_{sec_n:03d}"
    if fallback_from_name is not None:
        return fallback_from_name, "파일명 선행 번호"
    return None, "번호 없음"
