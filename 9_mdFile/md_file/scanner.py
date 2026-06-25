# -*- coding: utf-8 -*-
"""wisdom 루트 아래 각 모듈 ``md/`` 폴더의 ``*.txt`` 수집."""

from __future__ import annotations

from pathlib import Path


def _is_listed_txt(path: Path) -> bool:
    name = path.name.lower()
    if name.endswith(".md"):
        return False
    return name.endswith(".txt")


def scan_module_txt_files(wisdom_root: Path) -> list[Path]:
    """``{모듈}/md/`` 아래 ``.txt`` 파일만 (``.md`` 제외)."""
    if not wisdom_root.is_dir():
        return []
    found: list[Path] = []
    try:
        for child in sorted(wisdom_root.iterdir(), key=lambda p: p.name.lower()):
            if not child.is_dir():
                continue
            md_dir = child / "md"
            if not md_dir.is_dir():
                continue
            for p in md_dir.rglob("*"):
                if p.is_file() and _is_listed_txt(p):
                    found.append(p.resolve())
    except OSError:
        return []
    found.sort(key=lambda x: (str(x.parent).lower(), x.name.lower()))
    return found


def read_text_file(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except (OSError, UnicodeDecodeError):
            continue
    raise OSError(f"파일을 읽을 수 없습니다: {path}")
