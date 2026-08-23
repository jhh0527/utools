# -*- coding: utf-8 -*-
"""대본 ``[1]`` / ``[2]`` … 단락 분리."""

from __future__ import annotations

import re
from dataclasses import dataclass

_MARKER_RE = re.compile(r"^\s*\[(\d+)\]\s*(.*)$")


@dataclass(frozen=True)
class Paragraph:
    num: int
    text: str

    @property
    def mp3_name(self) -> str:
        n = self.num
        stem = f"{n:02d}" if n < 100 else str(n)
        return f"{stem}.mp3"


def parse_numbered_paragraphs(script: str) -> list[Paragraph]:
    """``[N]`` 마커로 단락을 나눕니다. 빈 본문은 제외."""
    raw = (script or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []

    paras: list[Paragraph] = []
    cur_num: int | None = None
    cur_parts: list[str] = []

    def flush() -> None:
        nonlocal cur_num, cur_parts
        if cur_num is None:
            return
        body = "\n".join(cur_parts).strip()
        body = re.sub(r"\n{3,}", "\n\n", body)
        if body:
            paras.append(Paragraph(num=int(cur_num), text=body))
        cur_num = None
        cur_parts = []

    for line in raw.split("\n"):
        m = _MARKER_RE.match(line)
        if m:
            flush()
            cur_num = int(m.group(1))
            rest = (m.group(2) or "").strip()
            cur_parts = [rest] if rest else []
            continue
        if cur_num is not None:
            cur_parts.append(line)

    flush()
    paras.sort(key=lambda p: p.num)
    return paras
