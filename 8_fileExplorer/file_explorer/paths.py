# -*- coding: utf-8 -*-
"""드라이브·기본 경로."""

from __future__ import annotations

import sys
from pathlib import Path

SOURCE_DRIVES: tuple[str, ...] = ("C:", "S:", "T:", "U:", "X:")
DEFAULT_DEST_DRIVE = "W:"
_DRIVE_REMOVABLE = 2
_KNOWN_FIXED_DRIVES = frozenset(
    {*SOURCE_DRIVES, DEFAULT_DEST_DRIVE, "D:"},
)


def drive_root(letter: str) -> Path:
    d = letter.strip().rstrip("\\/")
    if not d.endswith(":"):
        d = f"{d}:"
    return Path(f"{d}/")


def default_dest_dir() -> Path:
    w = drive_root(DEFAULT_DEST_DRIVE)
    return w if w.exists() else Path.home()


def available_source_drives() -> list[str]:
    out: list[str] = []
    for letter in SOURCE_DRIVES:
        if drive_root(letter).exists():
            out.append(letter)
    return out


def first_available_source() -> Path:
    for letter in SOURCE_DRIVES:
        root = drive_root(letter)
        if root.exists():
            return root
    return drive_root("C:")


def _windows_drive_type(letter: str) -> int | None:
    if sys.platform != "win32":
        return None
    import ctypes

    root = str(drive_root(letter))
    try:
        return int(ctypes.windll.kernel32.GetDriveTypeW(root))
    except (AttributeError, OSError, ValueError):
        return None


def available_usb_drives() -> list[str]:
    """연결된 이동식(USB) 드라이브 문자 목록."""
    if sys.platform != "win32":
        return []
    out: list[str] = []
    for code in range(ord("A"), ord("Z") + 1):
        letter = f"{chr(code)}:"
        if letter in _KNOWN_FIXED_DRIVES:
            continue
        root = drive_root(letter)
        if not root.exists():
            continue
        if _windows_drive_type(letter) == _DRIVE_REMOVABLE:
            out.append(letter)
    return out


def path_on_drive(path: Path, drive: str) -> bool:
    """경로가 지정 드라이브 아래인지."""
    root = drive_root(drive)
    if not root.exists():
        return False
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def dest_on_export_drive(dest_dir: Path) -> bool:
    """대상 경로가 반출 드라이브(W:) 아래인지."""
    return path_on_drive(dest_dir, DEFAULT_DEST_DRIVE)


def dest_on_usb_drive(dest_dir: Path) -> bool:
    """대상 경로가 연결된 USB 드라이브 아래인지."""
    drive = dest_dir.drive.upper()
    if not drive:
        return False
    return drive in {d.upper() for d in available_usb_drives()}
