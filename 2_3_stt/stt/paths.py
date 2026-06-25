# -*- coding: utf-8 -*-
"""2_3_stt 기본 경로."""

from __future__ import annotations

from pathlib import Path

from wisdom_workspace import workspace_module_output

MODULE = "2_3_stt"


def default_output_dir() -> Path:
    return workspace_module_output(MODULE)


def guess_original_txt(mp3_path: Path) -> Path | None:
    """같은 폴더·같은 이름의 txt 가 있으면 반환합니다."""
    cand = mp3_path.with_suffix(".txt")
    if cand.is_file():
        return cand
    return None
