# -*- coding: utf-8 -*-
"""SRT 자막 → 주요 구간(섹션) 그룹."""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENTENCE_END = re.compile(r"[.!?。！？…]\s*")


@dataclass(frozen=True)
class ScriptSection:
    """주요 구간 한 행."""

    srt_id: int
    cue_ids: list[int]
    main_text: str
    search_text: str


def _merge_cue_text(parts: list[str]) -> str:
    return " ".join(p.strip() for p in parts if p.strip())


def _extract_main_text(full: str, *, display_max: int = 72) -> str:
    """구간 전체에서 대표(주요) 문장·구절 추출."""
    text = " ".join(full.split())
    if not text:
        return ""
    sentences = [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]
    if not sentences:
        sentences = [text]
    main = max(sentences, key=len)
    if len(sentences) > 1 and len(main) < len(text) * 0.4:
        main = sentences[0]
    if len(main) > display_max:
        return main[: display_max - 1] + "…"
    if len(sentences) > 1 and main != text:
        return main + " …"
    return main


def group_srt_cues(
    cues: list[tuple[int, str]],
    *,
    target_chars: int = 55,
    max_chars: int = 110,
    max_cues: int = 6,
) -> list[ScriptSection]:
    """연속 자막을 주요 구간으로 묶습니다."""
    if not cues:
        return []

    sections: list[ScriptSection] = []
    buf_ids: list[int] = []
    buf_texts: list[str] = []

    def flush() -> None:
        nonlocal buf_ids, buf_texts
        if not buf_ids:
            return
        full = _merge_cue_text(buf_texts)
        sections.append(
            ScriptSection(
                srt_id=buf_ids[0],
                cue_ids=list(buf_ids),
                main_text=_extract_main_text(full),
                search_text=full,
            )
        )
        buf_ids = []
        buf_texts = []

    for srt_id, text in cues:
        piece = (text or "").strip()
        if not piece:
            continue
        buf_ids.append(srt_id)
        buf_texts.append(piece)
        merged = _merge_cue_text(buf_texts)
        ends_sentence = bool(re.search(r"[.!?。！？…]$", piece))
        if len(merged) >= max_chars or len(buf_ids) >= max_cues or (
            len(merged) >= target_chars and ends_sentence
        ):
            flush()

    flush()
    return sections
