# -*- coding: utf-8 -*-
"""저장 JPG → mp4 폴더 복사 (기존 mp4/*.jpg 삭제 후)."""

from __future__ import annotations

import shutil
from pathlib import Path

from png2jpg.paths import resolve_mp4_dir

_JPG_EXTS = frozenset({".jpg", ".jpeg"})


def list_jpg_files(folder: Path) -> list[Path]:
    if not folder.is_dir():
        return []
    return sorted(
        p
        for p in folder.iterdir()
        if p.is_file() and p.suffix.lower() in _JPG_EXTS
    )


def copy_jpgs_to_mp4(
    jpg_dir: Path,
    *,
    mp4_dir: Path | None = None,
) -> tuple[Path, int, int]:
    """mp4 폴더의 기존 JPG를 모두 지운 뒤 ``jpg_dir`` JPG를 복사.

    반환: (mp4 폴더, 삭제한 개수, 복사한 개수)
    """
    src = Path(jpg_dir).expanduser().resolve()
    if not src.is_dir():
        raise FileNotFoundError(f"JPG 폴더가 없습니다: {src}")
    dest = Path(mp4_dir).resolve() if mp4_dir else resolve_mp4_dir(src)
    dest.mkdir(parents=True, exist_ok=True)

    deleted = 0
    for old in list_jpg_files(dest):
        old.unlink()
        deleted += 1

    sources = list_jpg_files(src)
    if not sources:
        raise FileNotFoundError(f"복사할 JPG가 없습니다:\n{src}")

    for f in sources:
        shutil.copy2(f, dest / f.name)
    return dest, deleted, len(sources)
