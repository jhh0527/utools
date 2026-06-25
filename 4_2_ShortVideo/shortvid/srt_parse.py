"""SRT 파싱 (밀리초 타임라인) — wisdom 다른 패키지에 의존하지 않습니다."""

from __future__ import annotations

import re
from pathlib import Path


def parse_srt_timestamp_ms(ts: str) -> int:
    """`HH:MM:SS,mmm` 또는 `HH:MM:SS.mmm` → 밀리초."""
    ts = ts.strip().replace(".", ",")
    m = re.match(r"^(\d{2}):(\d{2}):(\d{2}),(\d{3})$", ts)
    if not m:
        raise ValueError(f"SRT 타임스탬프 형식이 아닙니다: {ts!r}")
    h, mi, s, z = (int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
    return ((h * 60 + mi) * 60 + s) * 1000 + z


def _srt_image_map_id(first_line: str, ordinal: int) -> int:
    """첫 줄이 양의 정수면 그 값(SRT 표시 번호 → images/srt_NN.*), 아니면 순번."""
    s = first_line.strip()
    if s.isdigit():
        n = int(s)
        if n >= 0:
            return n
    return ordinal


def parse_srt_cues_ms(content: str) -> list[tuple[int, int, int, str]]:
    """SRT 본문을 (image_map_id, start_ms, end_ms, text) 리스트로 파싱합니다.

    image_map_id는 보통 블록 첫 줄의 자막 번호이며, 이미지 매칭은 ``start_ms`` 초(``SRT_000``=0초) 기준입니다.
    첫 줄이 번호가 아니면 해당 블록의 파일 내 순번(1부터)을 씁니다.
    """
    cues: list[tuple[int, int, int, str]] = []
    raw = content.replace("\r\n", "\n").strip()
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
        ordinal = len(cues) + 1
        map_id = _srt_image_map_id(lines[0], ordinal)
        text = "\n".join(lines[2:]).strip() if len(lines) > 2 else ""
        cues.append((map_id, st, en, text))
    return cues


def load_srt_cues_ms(path: Path) -> list[tuple[int, int, int, str]]:
    return parse_srt_cues_ms(path.read_text(encoding="utf-8", errors="replace"))
