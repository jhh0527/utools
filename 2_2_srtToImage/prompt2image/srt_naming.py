# -*- coding: utf-8 -*-
"""SRT_XXX.png 파일명 규칙."""

from __future__ import annotations

import re
from pathlib import Path

SRT_NAME_RE = re.compile(r"^SRT_(\d+)\.png$", re.IGNORECASE)
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}
_INCOMPLETE_SUFFIXES = (".crdownload", ".tmp", ".part", ".download")


def parse_srt_number(filename: str) -> int | None:
    m = SRT_NAME_RE.match(filename)
    return int(m.group(1)) if m else None


def format_srt_filename(n: int) -> str:
    return f"SRT_{n:03d}.png"


def list_srt_pngs(png_dir: Path) -> list[Path]:
    if not png_dir.is_dir():
        return []
    files = [p for p in png_dir.iterdir() if p.is_file() and parse_srt_number(p.name) is not None]
    files.sort(key=lambda p: parse_srt_number(p.name) or 0)
    return files


def next_scene_number(png_dir: Path) -> int:
    nums: list[int] = []
    for p in list_srt_pngs(png_dir):
        n = parse_srt_number(p.name)
        if n is not None:
            nums.append(n)
    return (max(nums) + 1) if nums else 0


def next_missing_cue_number(cue_ids: list[int], png_dir: Path) -> int:
    """대본 번호 중 아직 PNG 가 없는 첫 번호."""
    for n in sorted(set(cue_ids)):
        if not (png_dir / format_srt_filename(n)).is_file():
            return n
    return next_scene_number(png_dir)


def normalize_png_name(name: str) -> str | None:
    """``SRT_XXX.png`` 형식으로 정규화. 실패 시 ``None``."""
    raw = (name or "").strip()
    if not raw:
        return None
    if not raw.lower().endswith(".png"):
        raw = f"{raw}.png"
    n = parse_srt_number(raw)
    if n is None:
        return None
    return format_srt_filename(n)


def png_index(png_dir: Path) -> dict[int, Path]:
    """``대본번호 → 파일 경로`` (파일명 숫자 기준)."""
    out: dict[int, Path] = {}
    if not png_dir.is_dir():
        return out
    for p in png_dir.iterdir():
        if not p.is_file():
            continue
        n = parse_srt_number(p.name)
        if n is not None:
            out[n] = p
    return out


def is_incomplete_download(path: Path) -> bool:
    low = path.name.lower()
    return any(low.endswith(s) for s in _INCOMPLETE_SUFFIXES)


def is_image_file(path: Path) -> bool:
    return path.is_file() and path.suffix.lower() in IMAGE_EXTS and not is_incomplete_download(path)
