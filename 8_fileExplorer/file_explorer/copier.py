# -*- coding: utf-8 -*-
"""파일·폴더 복사."""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path


@dataclass
class CopyItem:
    source: Path
    dest: Path
    kind: str  # "file" | "dir"


def _collect_targets(
    sources: list[Path],
    dest_dir: Path,
    *,
    recursive: bool,
) -> list[CopyItem]:
    items: list[CopyItem] = []
    for src in sources:
        src = src.resolve()
        if not src.exists():
            continue
        if src.is_file():
            items.append(CopyItem(src, dest_dir / src.name, "file"))
            continue
        if not src.is_dir():
            continue
        if not recursive:
            for child in sorted(src.iterdir()):
                if child.is_file():
                    items.append(CopyItem(child, dest_dir / child.name, "file"))
            continue
        for root, _dirs, files in os.walk(src):
            root_p = Path(root)
            rel = root_p.relative_to(src)
            target_root = dest_dir / src.name / rel
            for name in files:
                items.append(
                    CopyItem(
                        root_p / name,
                        target_root / name,
                        "file",
                    )
                )
    return items


def count_copy_targets(
    sources: list[Path],
    dest_dir: Path,
    *,
    recursive: bool,
) -> int:
    return len(_collect_targets(sources, dest_dir, recursive=recursive))


def copy_items(
    sources: list[Path],
    dest_dir: Path,
    *,
    recursive: bool = True,
    overwrite: bool = True,
    on_progress: Callable[[int, int, CopyItem], None] | None = None,
) -> tuple[int, list[str]]:
    """선택 항목을 ``dest_dir`` 로 복사. (성공 건수, 오류 메시지 목록)"""
    dest_dir = dest_dir.resolve()
    dest_dir.mkdir(parents=True, exist_ok=True)

    targets = _collect_targets(sources, dest_dir, recursive=recursive)
    total = len(targets)
    ok = 0
    errors: list[str] = []

    for i, item in enumerate(targets, start=1):
        try:
            item.dest.parent.mkdir(parents=True, exist_ok=True)
            if item.dest.exists():
                if not overwrite:
                    errors.append(f"건너뜀(이미 있음): {item.dest.name}")
                    if on_progress:
                        on_progress(i, total, item)
                    continue
                if item.dest.is_file():
                    item.dest.unlink()
            shutil.copy2(item.source, item.dest)
            ok += 1
        except OSError as e:
            errors.append(f"{item.source.name}: {e}")
        if on_progress:
            on_progress(i, total, item)

    return ok, errors
