# -*- coding: utf-8 -*-
"""SRT 대본 파싱."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_png_rename_path() -> None:
    from wisdom_root import resolve_wisdom_root

    root = resolve_wisdom_root() / "3_1_pngFileName"
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


def parse_srt_cues(path: Path) -> list[tuple[int, str]]:
    """``(대본번호, 대본 텍스트)``."""
    _ensure_png_rename_path()
    from png_rename.srt_parse import parse_srt_cues as _parse

    return _parse(path)


def read_srt_file_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def extract_cue_block(path: Path, map_id: int) -> str:
    """Genspark 입력용 SRT 한 블록(번호·타임코드·대본)."""
    try:
        raw = read_srt_file_text(path).replace("\r\n", "\n")
    except OSError:
        return ""
    target = str(map_id)
    for block in raw.split("\n\n"):
        lines = [ln for ln in block.strip().split("\n") if ln.strip()]
        if lines and lines[0].strip() == target:
            return block.strip()
    for mid, text in parse_srt_cues(path):
        if int(mid) == int(map_id):
            return f"{map_id}\n\n{text}"
    return ""
