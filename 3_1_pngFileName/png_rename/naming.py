# -*- coding: utf-8 -*-
"""``SRT_XXX.png`` / ``SRT_XXX.jpg`` 출력 파일명."""

from __future__ import annotations

import re
from pathlib import Path

_SRT_STEM = re.compile(r"^srt[-_]?0*(\d+)\.(?:png|jpe?g)$", re.IGNORECASE)
_SRT_JUNK_STEM = re.compile(r"^srt[-_]?0*(\d+)_.+\.(?:png|jpe?g)$", re.IGNORECASE)

SRT_ASSET_EXTS = frozenset({".png", ".jpg", ".jpeg"})


def normalize_srt_ext(ext: str) -> str:
    e = (ext or "").lower()
    if e == ".jpeg":
        return ".jpg"
    if e in SRT_ASSET_EXTS:
        return e
    return ".png"


def srt_asset_name(number: int, *, ext: str = ".png", pad: int = 3) -> str:
    if number < 0:
        raise ValueError(f"SRT 번호는 0 이상이어야 합니다: {number}")
    return f"SRT_{number:0{pad}d}{normalize_srt_ext(ext)}"


def srt_asset_name_for_path(number: int, path: Path, *, pad: int = 3) -> str:
    ext = path.suffix if path.suffix else ".png"
    return srt_asset_name(number, ext=ext, pad=pad)


def srt_png_name(number: int, *, pad: int = 3) -> str:
    return srt_asset_name(number, ext=".png", pad=pad)


def is_clean_srt_asset_name(name: str) -> bool:
    """``SRT_XXX.png`` / ``SRT_XXX.jpg`` 형식(접미사 없음)이면 True."""
    return _SRT_STEM.match(name or "") is not None


def is_clean_srt_png_name(name: str) -> bool:
    return is_clean_srt_asset_name(name)


def parse_srt_number_from_filename(name: str) -> int | None:
    """``SRT_XXX.png`` / ``SRT_XXX.jpg`` 또는 ``SRT_XXX_쓰레기.*`` 에서 번호 추출."""
    m = _SRT_STEM.match(name or "")
    if m:
        return int(m.group(1))
    m = _SRT_JUNK_STEM.match(name or "")
    if m:
        return int(m.group(1))
    return None


def normalized_srt_asset_name(name: str, *, pad: int = 3) -> str | None:
    """``SRT_XXX_접미사.png`` → ``SRT_XXX.png``. 이미 정규 형식이면 ``None``."""
    if is_clean_srt_asset_name(name):
        return None
    m = _SRT_JUNK_STEM.match(name or "")
    if not m:
        return None
    ext = Path(name).suffix or ".png"
    return srt_asset_name(int(m.group(1)), ext=ext, pad=pad)


def normalized_srt_png_name(name: str, *, pad: int = 3) -> str | None:
    return normalized_srt_asset_name(name, pad=pad)


def find_srt_asset_in_dir(folder: Path, number: int) -> Path | None:
    """폴더에서 ``SRT_NNN.png`` / ``SRT_NNN.jpg`` 파일 탐색."""
    folder = Path(folder)
    for ext in (".png", ".jpg", ".jpeg"):
        p = folder / srt_asset_name(number, ext=ext)
        if p.is_file():
            return p
    return None
