# -*- coding: utf-8 -*-
"""폴더 MP4 목록 — all.mp4·임시·부분본 제외."""

from __future__ import annotations

import re
from pathlib import Path

from mp4_merge.paths import ALL_MP4_NAME

_SRT_ASSET = re.compile(r"^srt[-_]?0*(\d+)\.mp4$", re.IGNORECASE)
_LEADING_NUM = re.compile(r"^(\d+)")
_CHAPTER_PART_STEM = re.compile(r"^(\d+)장(\d+)$")
_CHAPTER_ONLY_STEM = re.compile(r"^(\d+)장$")


def list_folder_mp4s(folder: Path) -> list[Path]:
    """폴더 직속 ``.mp4`` — ``all.mp4``·``_`` 접두·임시·부분본 제외.

    같은 회차(``01장``·``1장``)가 여러 개면 용량이 큰 본편만.
    정렬: ``SRT_NNN`` → 앞 숫자 → 이름.
    """
    folder = Path(folder)
    if not folder.is_dir():
        return []
    try:
        children = list(folder.iterdir())
    except OSError:
        return []
    skip = {ALL_MP4_NAME.lower()}
    out: list[Path] = []
    for child in children:
        if not child.is_file() or child.suffix.lower() != ".mp4":
            continue
        name_l = child.name.lower()
        if name_l in skip or name_l.startswith("_"):
            continue
        if ".tmp." in name_l or name_l.endswith(".tmp.mp4") or ".concat." in name_l:
            continue
        if _CHAPTER_PART_STEM.match(child.stem):
            continue
        out.append(child)

    chapter_best: dict[int, Path] = {}
    rest: list[Path] = []
    for p in out:
        m = _CHAPTER_ONLY_STEM.match(p.stem)
        if not m:
            rest.append(p)
            continue
        key = int(m.group(1))
        prev = chapter_best.get(key)
        try:
            sz = p.stat().st_size
        except OSError:
            sz = 0
        if prev is None:
            chapter_best[key] = p
            continue
        try:
            prev_sz = prev.stat().st_size
        except OSError:
            prev_sz = 0
        if sz >= prev_sz:
            chapter_best[key] = p
    out = rest + list(chapter_best.values())

    def sort_key(p: Path) -> tuple[int, int, str]:
        m = _SRT_ASSET.match(p.name)
        if m:
            return (0, int(m.group(1)), p.name.lower())
        m2 = _LEADING_NUM.match(p.stem)
        if m2:
            return (1, int(m2.group(1)), p.name.lower())
        return (2, 0, p.name.lower())

    out.sort(key=sort_key)
    return out
