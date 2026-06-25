# -*- coding: utf-8 -*-
"""wisdom 워크스페이스(열린 폴더) 기준 기본 입·출력 경로."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIRNAME = "3_2_pngToJpg"
OUTPUT_DIRNAME = "output"


def _ensure_wisdom_on_path(from_file: str | Path) -> None:
    for base in [Path.cwd(), *Path(from_file).resolve().parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            return
    raise ImportError("wisdom_root.py not found — wisdom 폴더를 워크스페이스 루트로 여세요.")


_ensure_wisdom_on_path(__file__)
from wisdom_root import module_dir, module_output
from wisdom_workspace import get_workspace_dir, resolve_module_output


def _project_root() -> Path:
    found = module_dir(PROJECT_DIRNAME)
    if found.is_dir():
        return found
    if getattr(sys, "frozen", False):
        start = Path(sys.executable).resolve().parent
    else:
        start = Path(__file__).resolve().parent.parent
    for p in [start, *start.parents]:
        if p.name == PROJECT_DIRNAME:
            return p
    return start


def default_output_dir() -> Path:
    try:
        from wisdom_content_paths import default_jpg_dir

        jpg = default_jpg_dir()
        if jpg is not None:
            return jpg
    except ImportError:
        pass
    return resolve_module_output(PROJECT_DIRNAME)


def default_input_dir() -> Path:
    """기본 입력: 작업 폴더 ``png`` (없으면 ``2_2_srtToImage/output``)."""
    try:
        from wisdom_content_paths import default_png_dir

        png = default_png_dir()
        if png is not None:
            return png
    except ImportError:
        pass
    ws = get_workspace_dir()
    if ws is not None:
        srt_out = ws / "2_2_srtToImage" / "output"
        if srt_out.is_dir():
            return srt_out
    srt_out = module_output("2_2_srtToImage")
    if srt_out.is_dir():
        return srt_out
    inp = module_dir("3_2_pngToJpg") / "input"
    if inp.is_dir():
        return inp
    return _project_root() / "input"
