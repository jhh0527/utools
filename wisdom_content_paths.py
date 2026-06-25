# -*- coding: utf-8 -*-
"""콘텐츠 프로젝트 폴더 — 작업 폴더(루트) 아래 mp3 / png / jpg."""

from __future__ import annotations

from pathlib import Path

from wisdom_workspace import get_workspace_dir, set_workspace_dir

_MEDIA_CHILD_NAMES = frozenset({"mp3", "png", "jpg"})


def find_child_dir(root: Path, name: str) -> Path:
    """``root`` 아래 자식 폴더 (대소문자 무시). 없으면 ``root/name``."""
    try:
        base = root.expanduser().resolve()
    except OSError:
        return Path(name)
    if not base.is_dir():
        return base / name
    target = name.casefold()
    for child in base.iterdir():
        if child.is_dir() and child.name.casefold() == target:
            return child
    return base / name


def _dir_has_media_files(folder: Path) -> bool:
    if not folder.is_dir():
        return False
    try:
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            ext = entry.suffix.casefold()
            if ext in (".mp3", ".srt"):
                return True
    except OSError:
        return False
    return False


def infer_content_root(path: str | Path) -> Path:
    """선택 경로에서 콘텐츠 루트(프로젝트 폴더)를 추론합니다."""
    raw = Path(path).expanduser()
    try:
        p = raw.resolve()
    except OSError:
        p = raw

    if p.is_file() or (not p.is_dir() and p.suffix):
        p = p.parent

    if not p.is_dir():
        if p.name.casefold() in _MEDIA_CHILD_NAMES:
            return p.parent
        parent = p.parent
        return parent if parent.is_dir() else p

    if p.name.casefold() in _MEDIA_CHILD_NAMES:
        return p.parent

    if _dir_has_media_files(p):
        return p.parent

    for name in _MEDIA_CHILD_NAMES:
        if find_child_dir(p, name).is_dir():
            return p

    return p.parent


def touch_content_root_from_path(path: str | Path) -> Path | None:
    """선택 경로에서 콘텐츠 루트를 작업 폴더로 저장."""
    root = infer_content_root(path)
    if not root.is_dir():
        return None
    try:
        return set_workspace_dir(root)
    except OSError:
        return root if root.is_dir() else None


def content_root() -> Path | None:
    ws = get_workspace_dir()
    if ws is None:
        return None
    try:
        r = ws.expanduser().resolve()
    except OSError:
        return None
    return r if r.is_dir() else None


def default_mp3_dir() -> Path | None:
    root = content_root()
    if root is None:
        return None
    return find_child_dir(root, "mp3")


def default_png_dir() -> Path | None:
    root = content_root()
    if root is None:
        return None
    return find_child_dir(root, "png")


def default_jpg_dir() -> Path | None:
    root = content_root()
    if root is None:
        return None
    return find_child_dir(root, "jpg")
