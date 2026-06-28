# -*- coding: utf-8 -*-
"""기본 경로."""

from __future__ import annotations

import sys
from pathlib import Path

from wisdom_workspace import workspace_module_output

MODULE = "7_3_mp4Search"


def default_output_dir() -> Path:
    return workspace_module_output(MODULE) / "mp4"


def _config_bases() -> list[Path]:
    bases: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        s = str(p)
        if s not in seen:
            seen.add(s)
            bases.append(p)

    if getattr(sys, "frozen", False):
        add(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            add(Path(meipass))
    try:
        from wisdom_root import module_dir

        mod = module_dir(MODULE)
        if mod.is_dir():
            add(mod)
    except ImportError:
        pass
    add(Path(__file__).resolve().parents[1])
    return bases


def stock_api_config_write_path() -> Path:
    """API 키 저장 권장 경로 (exe 옆 ``config/stock_api.json``)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config" / "stock_api.json"
    for base in _config_bases():
        if (base / "config").is_dir() or base.name == MODULE:
            return base / "config" / "stock_api.json"
    return Path(__file__).resolve().parents[1] / "config" / "stock_api.json"


def stock_api_config_candidates() -> list[Path]:
    """``stock_api.json`` → ``stock_api.example.json`` 순으로 탐색."""
    out: list[Path] = []
    seen: set[str] = set()
    for base in _config_bases():
        for name in ("stock_api.json", "stock_api.example.json"):
            p = base / "config" / name
            s = str(p)
            if s not in seen:
                seen.add(s)
                out.append(p)
    return out


def mp3_candidates_for_srt(srt: Path) -> list[Path]:
    """SRT·작업 폴더 기준 MP3 후보 (``all.mp3``, ``part01.mp3``, SRT와 같은 이름 등)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)

    srt = Path(srt)
    if srt.is_file():
        add(srt.with_suffix(".mp3"))
        for name in ("all.mp3", "part01.mp3"):
            add(srt.parent / name)
    try:
        from wisdom_content_paths import default_mp3_dir

        mp3_dir = default_mp3_dir()
        if mp3_dir and mp3_dir.is_dir():
            if srt.is_file():
                add(mp3_dir / srt.with_suffix(".mp3").name)
            for name in ("all.mp3", "part01.mp3"):
                add(mp3_dir / name)
    except ImportError:
        pass
    try:
        from wisdom_workspace import workspace_module_output

        tts_out = workspace_module_output("2_1_ttsToVoice")
        for name in ("all.mp3", "part01.mp3"):
            add(tts_out / name)
    except ImportError:
        pass
    return out


def resolve_mp3_for_srt(srt: Path) -> Path | None:
    for cand in mp3_candidates_for_srt(srt):
        if cand.is_file():
            return cand
    return None
