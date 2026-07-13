# -*- coding: utf-8 -*-
"""SRT를 시간 간격(기본 2분)으로 분할."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from img_down.paths import CHUNK_MS

_TS_RE = re.compile(
    r"^(\d{2}):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2})[,.](\d{3})"
)
_INDEX_RE = re.compile(r"^\d+$")


def script_sec(start_ms: int) -> int:
    """대본초 — SRT 시작 시각 정수 초 (예: 00:07:51,040 → 471 → ``SRT_471.png``)."""
    return max(0, int(start_ms) // 1000)


@dataclass(frozen=True)
class SrtCue:
    index: int
    start_ms: int
    end_ms: int
    text: str
    raw_block: str = ""

    @property
    def start_sec(self) -> int:
        """대본초 — SRT 시작 시각 정수 초 (예: 00:07:51 → 471, ``SRT_471.png``)."""
        return script_sec(self.start_ms)

    @property
    def end_sec(self) -> int:
        return max(0, int(self.end_ms) // 1000)

    @property
    def file_index(self) -> int:
        """SRT 파일 첫 줄 번호 (all.srt 에서는 대개 대본초와 동일)."""
        return self.index


@dataclass(frozen=True)
class SrtTimeline:
    """SRT 전체 타임라인 요약."""

    first_start_ms: int
    last_end_ms: int
    cue_count: int

    @property
    def first_start_sec(self) -> int:
        return script_sec(self.first_start_ms)

    @property
    def last_end_sec(self) -> int:
        return max(0, int(self.last_end_ms) // 1000)

    @property
    def duration_sec(self) -> int:
        return max(0, self.last_end_sec - self.first_start_sec)

    def summary(self) -> str:
        return (
            f"시작 {self.first_start_sec}초 ({_ms_to_ts(self.first_start_ms)})  ·  "
            f"종료 {self.last_end_sec}초 ({_ms_to_ts(self.last_end_ms)})  ·  "
            f"구간 {self.duration_sec}초  ·  큐 {self.cue_count}개"
        )


@dataclass(frozen=True)
class SrtChunk:
    index: int
    start_ms: int
    end_ms: int
    cues: tuple[SrtCue, ...]
    bucket_start_ms: int

    @property
    def start_sec(self) -> int:
        return script_sec(self.start_ms)

    @property
    def end_sec(self) -> int:
        return max(0, int(self.end_ms) // 1000)

    @property
    def label(self) -> str:
        first = self.cues[0].start_sec if self.cues else 0
        last = self.cues[-1].start_sec if self.cues else 0
        first_png = srt_png_name(first) if self.cues else ""
        last_png = srt_png_name(last) if self.cues else ""
        return (
            f"청크 {self.index + 1}  "
            f"대본초 {first}~{last}  "
            f"{first_png}~{last_png}  "
            f"({len(self.cues)}큐)"
        )

    def cue_start_secs(self) -> list[int]:
        """청크 내 각 큐의 대본초 — ``SRT_XXX.png`` 파일명 폴백."""
        return [c.start_sec for c in self.cues]

    def as_srt_text(self) -> str:
        """청크에 해당하는 SRT 원문 블록 (타임스탬프·번호 그대로)."""
        if self.cues and all((c.raw_block or "").strip() for c in self.cues):
            return "\n\n".join(c.raw_block.strip() for c in self.cues) + "\n"
        blocks: list[str] = []
        for cue in self.cues:
            body = cue.text.replace("\r\n", "\n").strip()
            blocks.append(
                f"{cue.index}\n{_ms_to_ts(cue.start_ms)} --> {_ms_to_ts(cue.end_ms)}\n{body}\n"
            )
        return "\n".join(blocks)


def _ms_to_ts(ms: int) -> str:
    if ms < 0:
        ms = 0
    h, r = divmod(ms, 3_600_000)
    m, r = divmod(r, 60_000)
    s, z = divmod(r, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{z:03d}"


def _ts_to_ms(h: int, mi: int, s: int, z: int) -> int:
    return ((h * 60 + mi) * 60 + s) * 1000 + z


def parse_srt_file(path: Path) -> list[SrtCue]:
    raw = path.read_text(encoding="utf-8-sig").replace("\r\n", "\n").strip()
    if not raw:
        return []
    cues: list[SrtCue] = []
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln is not None]
        if len(lines) < 2:
            continue
        ts_line = lines[1] if "-->" in lines[1] else (lines[0] if "-->" in lines[0] else "")
        m = _TS_RE.match(ts_line.strip())
        if not m:
            continue
        st = _ts_to_ms(*(int(m.group(i)) for i in range(1, 5)))
        en = _ts_to_ms(*(int(m.group(i)) for i in range(5, 9)))
        text_lines = lines[2:] if "-->" in lines[1] else lines[1:]
        text = "\n".join(text_lines).strip()
        file_index = len(cues) + 1
        if "-->" in lines[1] and _INDEX_RE.match(lines[0].strip()):
            file_index = int(lines[0].strip())
        cues.append(
            SrtCue(
                index=file_index,
                start_ms=st,
                end_ms=en,
                text=text,
                raw_block=block.strip(),
            )
        )
    return cues


def analyze_timeline(cues: list[SrtCue]) -> SrtTimeline | None:
    if not cues:
        return None
    return SrtTimeline(
        first_start_ms=cues[0].start_ms,
        last_end_ms=cues[-1].end_ms,
        cue_count=len(cues),
    )


def split_cues(cues: list[SrtCue], *, chunk_ms: int = CHUNK_MS) -> list[SrtChunk]:
    """절대 타임라인 기준 2분 버킷. 큐의 실제 시작초는 0이 아닐 수 있음."""
    if not cues:
        return []
    chunk_ms = max(1_000, int(chunk_ms))
    buckets: dict[int, list[SrtCue]] = {}
    for cue in cues:
        bi = max(0, cue.start_ms) // chunk_ms
        buckets.setdefault(bi, []).append(cue)
    out: list[SrtChunk] = []
    for bi in sorted(buckets):
        group = buckets[bi]
        out.append(
            SrtChunk(
                index=len(out),
                start_ms=group[0].start_ms,
                end_ms=group[-1].end_ms,
                bucket_start_ms=bi * chunk_ms,
                cues=tuple(group),
            )
        )
    return out


def load_chunks(path: Path, *, chunk_ms: int = CHUNK_MS) -> list[SrtChunk]:
    return split_cues(parse_srt_file(path), chunk_ms=chunk_ms)


def load_timeline(path: Path) -> SrtTimeline | None:
    return analyze_timeline(parse_srt_file(path))


_SRT_NAME_RE = re.compile(r"SRT[_\s-]?(\d{1,6})", re.IGNORECASE)


def extract_srt_labels(text: str) -> list[int]:
    """텍스트에서 SRT_XXX 대본초 번호를 등장 순으로 추출."""
    seen: set[int] = set()
    out: list[int] = []
    for m in _SRT_NAME_RE.finditer(text or ""):
        n = int(m.group(1))
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def srt_png_name(sec: int) -> str:
    """``SRT_XXX.png`` — XXX는 대본초 (00:07:51 → 471 → ``SRT_471.png``)."""
    return f"SRT_{max(0, int(sec)):03d}.png"
