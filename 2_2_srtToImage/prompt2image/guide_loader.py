# -*- coding: utf-8 -*-
"""``md/image*.md.txt`` 이미지 생성 지침."""

from __future__ import annotations

import sys
from pathlib import Path

_DEFAULT_GUIDE = "image.md.txt"

# GUI 표시명 → 파일명
GUIDE_OPTIONS: dict[str, str] = {
    "기본 (지식·일러스트)": "image.md.txt",
    "증시·스톡브리핑 (실사)": "image.stockbrief.md.txt",
    "증시·스틱맨 (일러스트)": "image.stock.md.txt",
    "원더 (일러스트)": "image.wonder.md.txt",
    "지브리 (일러스트)": "image.ghibli.md.txt",
}

_GUIDE_LABEL_BY_FILE = {v: k for k, v in GUIDE_OPTIONS.items()}


def md_dir() -> Path:
    from wisdom_root import module_dir

    return module_dir("2_2_srtToImage") / "md"


def guide_path(name: str | None = None) -> Path:
    fname = (name or _DEFAULT_GUIDE).strip() or _DEFAULT_GUIDE
    return md_dir() / fname


def list_guide_files() -> list[str]:
    d = md_dir()
    if not d.is_dir():
        return [_DEFAULT_GUIDE]
    files = sorted(p.name for p in d.glob("image*.md.txt") if p.is_file())
    return files or [_DEFAULT_GUIDE]


def guide_label_for_file(filename: str) -> str:
    return _GUIDE_LABEL_BY_FILE.get(filename, filename)


def guide_file_for_label(label: str) -> str:
    return GUIDE_OPTIONS.get(label, label)


def load_image_guide(name: str | None = None) -> str:
    fname = (name or _DEFAULT_GUIDE).strip() or _DEFAULT_GUIDE
    candidates: list[Path] = []
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            candidates.append(Path(meipass) / "md" / fname)
    candidates.append(guide_path(fname))
    candidates.append(Path(__file__).resolve().parents[1] / "md" / fname)
    for p in candidates:
        if p.is_file():
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
    return ""
