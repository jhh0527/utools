# -*- coding: utf-8 -*-
"""기본 경로."""

from __future__ import annotations

from pathlib import Path

from wisdom_root import module_dir, resolve_wisdom_root
from wisdom_workspace import get_workspace_dir, resolve_module_output

MODULE = "2_2_imgDown"
GUIDE_NAME = "image.ghibli.md.txt"
CHUNK_MS = 120_000
FIXED_PROMPT = (
    "첨부의 지침을 참조로, 대본의 이미지를 생성해 주세요. "
    "모든 이미지에 들어가는 텍스트는 한글로 작성합니다."
)


def default_png_dir() -> Path:
    ws = get_workspace_dir()
    if ws is not None:
        return ws / "png"
    return resolve_module_output(MODULE) / "png"


def default_srt_file() -> Path | None:
    tts_out = resolve_module_output("2_1_ttsToVoice")
    for name in ("all.srt", "all.SRT"):
        p = tts_out / name
        if p.is_file():
            return p
    return None


def default_guide_file() -> Path:
    wisdom = resolve_wisdom_root()
    candidates = [
        wisdom / "2_1_ttsToVoice" / "md" / GUIDE_NAME,
        module_dir("2_1_ttsToVoice") / "md" / GUIDE_NAME,
        module_dir(MODULE) / "md" / GUIDE_NAME,
    ]
    for p in candidates:
        if p.is_file():
            return p
    return candidates[0]
