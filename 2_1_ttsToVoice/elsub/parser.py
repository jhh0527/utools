# -*- coding: utf-8 -*-
"""2_1_ttsToVoice: knowledgetts 형식 줄 파싱 (`1-1 원본: ... TTS: ...`).

`CaptionLine.part_id` 프로퍼티로 caption_id의 앞 숫자(파트 번호)를 얻습니다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PART_HEADER = re.compile(r"^\s*\d+\.\{\}\s*$")
SUMMARY = re.compile(r"^\s*\*\*요약")
_SENTENCE_END = frozenset(".!?…")


@dataclass(frozen=True)
class CaptionLine:
    caption_id: str
    original: str
    tts: str

    @property
    def part_id(self) -> str:
        """caption_id가 "1-1" 형태일 때 앞 숫자(파트 번호)를 반환합니다."""
        return self.caption_id.split("-", 1)[0]


def parse_knowledgetts_block(text: str) -> list[CaptionLine]:
    out: list[CaptionLine] = []
    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if PART_HEADER.match(line) or SUMMARY.match(line):
            continue
        m = re.match(r"^\s*(\d+-\d+)\s+원본:\s*(.+)$", line)
        if not m:
            continue
        rest = m.group(2)
        sep = " TTS: "
        if sep not in rest:
            continue
        orig, tts = rest.split(sep, 1)
        out.append(CaptionLine(m.group(1), orig.strip(), tts.strip()))
    return merge_undersplit_captions(out)


def _original_ends_sentence(text: str) -> bool:
    t = text.rstrip()
    return bool(t) and t[-1] in _SENTENCE_END


def _join_original(a: str, b: str) -> str:
    a, b = a.rstrip(), b.lstrip()
    if not a:
        return b
    if not b:
        return a
    return f"{a} {b}"


def _join_merged_tts(a: str, b: str) -> str:
    a = a.rstrip()
    if a.endswith(","):
        a = a[:-1].rstrip()
    b = re.sub(r"^\s*\[continues\]\s*", "", b.strip(), flags=re.IGNORECASE)
    return f"{a} {b}".strip()


def merge_undersplit_captions(
    entries: list[CaptionLine],
    *,
    max_chars: int = 25,
) -> list[CaptionLine]:
    """인접 조각 원본 합이 max_chars 이하이면 한 자막으로 병합."""
    if len(entries) < 2:
        return entries
    out: list[CaptionLine] = []
    buf: CaptionLine | None = None
    for e in entries:
        if buf is None:
            buf = e
            continue
        combined = _join_original(buf.original, e.original)
        if (
            buf.part_id == e.part_id
            and len(combined) <= max_chars
            and not _original_ends_sentence(buf.original)
        ):
            buf = CaptionLine(
                buf.caption_id,
                combined,
                _join_merged_tts(buf.tts, e.tts),
            )
        else:
            out.append(buf)
            buf = e
    if buf is not None:
        out.append(buf)
    return out
