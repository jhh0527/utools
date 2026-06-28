# -*- coding: utf-8 -*-
"""2_1_ttsToVoice: knowledgetts 형식 줄 파싱.

지원 형식:
- 한 줄: ``1-1 원본: ... TTS: ...`` / ``1-1 原稿: ... TTS: ...`` / ``1-1 Original: ... TTS: ...``
- 여러 줄(v2.0): ``1-1`` 다음 ``Original:`` / ``TTS:`` / ``STT_Reference:`` (STT_Reference는 무시)
"""

from __future__ import annotations

import re
from dataclasses import dataclass

PART_HEADER = re.compile(r"^\s*\d+\.\{\}\s*$")
SUMMARY = re.compile(r"^\s*\*\*요약")
# 한국어·일본어 문장 종결 부호
_SENTENCE_END = frozenset(".!?…。！？")
# 원본 라벨: 한국어(원본) · 일본어(原稿) · 영어(Original)
_ORIGINAL_LABEL = r"(?:원본|原稿|Original)"
_CAPTION_ID_ONLY = re.compile(r"^\s*(\d+-\d+)\s*$")
_CAPTION_LINE_RE = re.compile(
    rf"^\s*(\d+-\d+)\s+{_ORIGINAL_LABEL}:\s*(.+)$",
    re.IGNORECASE,
)
_ORIGINAL_LINE = re.compile(
    rf"^\s*{_ORIGINAL_LABEL}:\s*(.*)$",
    re.IGNORECASE,
)
_TTS_LINE = re.compile(r"^\s*TTS:\s*(.*)$", re.IGNORECASE)
_STT_REF_LINE = re.compile(r"^\s*STT_Reference:\s*(.*)$", re.IGNORECASE)
_TTS_SEP = re.compile(r"\s+TTS:\s+", re.IGNORECASE)
_STT_REF_SEP = re.compile(r"\s+STT_Reference:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class CaptionLine:
    caption_id: str
    original: str
    tts: str

    @property
    def part_id(self) -> str:
        """caption_id가 "1-1" 형태일 때 앞 숫자(파트 번호)를 반환합니다."""
        return self.caption_id.split("-", 1)[0]


def _strip_stt_reference(text: str) -> str:
    return _STT_REF_SEP.split(text, 1)[0].strip()


def _parse_single_line(caption_id: str, rest: str) -> CaptionLine | None:
    parts = _TTS_SEP.split(rest, 1)
    if len(parts) != 2:
        return None
    orig, tts = parts
    return CaptionLine(caption_id, orig.strip(), _strip_stt_reference(tts))


def parse_knowledgetts_block(text: str) -> list[CaptionLine]:
    out: list[CaptionLine] = []
    pending_id: str | None = None
    pending_orig: str | None = None

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        if PART_HEADER.match(line) or SUMMARY.match(line):
            continue

        m = _CAPTION_LINE_RE.match(line)
        if m:
            pending_id = pending_orig = None
            parsed = _parse_single_line(m.group(1), m.group(2))
            if parsed:
                out.append(parsed)
            continue

        id_m = _CAPTION_ID_ONLY.match(line)
        if id_m:
            pending_id = id_m.group(1)
            pending_orig = None
            continue

        if _STT_REF_LINE.match(line):
            continue

        orig_m = _ORIGINAL_LINE.match(line)
        if orig_m and pending_id:
            pending_orig = orig_m.group(1).strip()
            continue

        tts_m = _TTS_LINE.match(line)
        if tts_m and pending_id and pending_orig is not None:
            out.append(CaptionLine(pending_id, pending_orig, tts_m.group(1).strip()))
            pending_id = pending_orig = None
            continue

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
    if a.endswith(",") or a.endswith("、"):
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
