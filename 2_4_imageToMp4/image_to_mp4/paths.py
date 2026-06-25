# -*- coding: utf-8 -*-
"""2_4_imageToMp4 기본 경로."""

from __future__ import annotations

from pathlib import Path

from wisdom_workspace import resolve_module_output

MODULE = "2_4_imageToMp4"


def default_output_dir() -> Path:
    return resolve_module_output(MODULE)


def default_input_dir() -> Path:
    return resolve_module_output("2_2_srtToImage") / "png"


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}


def list_input_images(folder: Path, *, recursive: bool = False) -> list[Path]:
    if not folder.is_dir():
        return []
    if recursive:
        files = [p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    else:
        files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in _IMAGE_EXTS]
    return sorted(files, key=lambda p: p.name.lower())


def describe_input_folder(folder: Path, *, recursive: bool = False) -> str:
    """상태 표시용 — 폴더·이미지 개수 안내."""
    if not folder.exists():
        return f"입력 폴더 없음: {folder}"
    if not folder.is_dir():
        return f"입력 경로가 폴더가 아닙니다: {folder}"
    n = len(list_input_images(folder, recursive=recursive))
    if n == 0 and not recursive:
        sub = len(list_input_images(folder, recursive=True))
        if sub:
            return f"입력 이미지 0개 (하위 폴더에 {sub}개 — 「하위 폴더 포함」 체크)"
    mode = "하위 포함" if recursive else "현재 폴더"
    return f"입력 이미지 {n}개 ({mode})"
