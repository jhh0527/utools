# -*- coding: utf-8 -*-
"""``SRT_XXX.mp4`` 출력 파일명."""

from __future__ import annotations

import re
from pathlib import Path

_SRT_STEM = re.compile(r"^srt[-_]?0*(\d+)\.mp4$", re.IGNORECASE)
_SRT_ASSET = re.compile(r"^srt[-_]?0*(\d+)\.(mp4|png|jpe?g|webp)$", re.IGNORECASE)
_IMAGE_EXTS = frozenset({".png", ".jpg", ".jpeg", ".webp"})
ALL_MP4_NAME = "all.mp4"


def timeline_asset_number(start_sec: float) -> int:
    """SRT 타임스탬프(초) → ``SRT_NNN`` 파일 번호 (정수 초, 내림). 4_1_video·SRT 파서와 동일."""
    return max(0, int(start_sec))


def srt_mp4_name(number: int, *, pad: int = 3) -> str:
    if number < 0:
        raise ValueError(f"SRT 번호는 0 이상이어야 합니다: {number}")
    return f"SRT_{number:0{pad}d}.mp4"


def srt_jpg_name(number: int, *, pad: int = 3) -> str:
    if number < 0:
        raise ValueError(f"SRT 번호는 0 이상이어야 합니다: {number}")
    return f"SRT_{number:0{pad}d}.jpg"


def srt_png_name(number: int, *, pad: int = 3) -> str:
    if number < 0:
        raise ValueError(f"SRT 번호는 0 이상이어야 합니다: {number}")
    return f"SRT_{number:0{pad}d}.png"


def parse_srt_number_from_filename(name: str) -> int | None:
    m = _SRT_STEM.match(name or "")
    return int(m.group(1)) if m else None


def parse_srt_asset_number(name: str) -> int | None:
    """``SRT_NNN.mp4`` / ``SRT_NNN.png`` 등 자산 파일 번호."""
    m = _SRT_ASSET.match(name or "")
    return int(m.group(1)) if m else None


def scan_srt_assets(folder: Path) -> tuple[dict[int, Path], dict[int, Path]]:
    """MP4 폴더의 ``SRT_NNN`` 영상·이미지 파일을 번호별로 수집."""
    mp4_map: dict[int, Path] = {}
    png_map: dict[int, Path] = {}
    folder = Path(folder)
    if not folder.is_dir():
        return mp4_map, png_map
    try:
        children = list(folder.iterdir())
    except OSError:
        return mp4_map, png_map
    for child in children:
        if not child.is_file():
            continue
        num = parse_srt_asset_number(child.name)
        if num is None:
            continue
        ext = child.suffix.lower()
        if ext == ".mp4":
            mp4_map[num] = child
        elif ext in _IMAGE_EXTS:
            png_map[num] = child
    return mp4_map, png_map


def list_compose_pairs(folder: Path) -> list[tuple[int, Path, Path]]:
    """MP4·이미지가 **같은 번호**인 ``SRT_NNN`` 쌍 (번호 오름차순)."""
    mp4_map, png_map = scan_srt_assets(folder)
    ids = sorted(set(mp4_map) & set(png_map))
    return [(sid, mp4_map[sid], png_map[sid]) for sid in ids]


def list_compose_pairs_sequential(folder: Path) -> list[tuple[int, Path, Path]]:
    """번호가 달라도 MP4·이미지를 각각 번호 순으로 1:1 매칭 (출력명은 MP4 번호)."""
    mp4_map, png_map = scan_srt_assets(folder)
    mp4_items = sorted(mp4_map.items())
    png_items = sorted(png_map.items())
    n = min(len(mp4_items), len(png_items))
    return [(mp4_items[i][0], mp4_items[i][1], png_items[i][1]) for i in range(n)]


def format_compose_status(folder: Path) -> str:
    """합성 불가 시 MP4·이미지 파일별 안내 문구."""
    mp4_map, png_map = scan_srt_assets(folder)
    lines = [f"폴더: {folder}"]
    if not mp4_map and not png_map:
        lines.append("\nSRT_NNN.mp4 / SRT_NNN.png·jpg 형식 파일이 없습니다.")
        return "\n".join(lines)
    matched = sorted(set(mp4_map) & set(png_map))
    only_mp4 = sorted(set(mp4_map) - set(png_map))
    only_png = sorted(set(png_map) - set(mp4_map))
    if matched:
        lines.append(f"\n[번호 일치 — 합성 가능] {len(matched)}쌍")
        for sid in matched[:12]:
            lines.append(f"  · {mp4_map[sid].name} + {png_map[sid].name}")
        if len(matched) > 12:
            lines.append(f"  … 외 {len(matched) - 12}쌍")
    if only_mp4:
        lines.append(f"\n[MP4만 — 같은 번호 PNG 필요] {len(only_mp4)}개")
        for sid in only_mp4[:8]:
            lines.append(f"  · {mp4_map[sid].name}  →  {srt_png_name(sid)}")
        if len(only_mp4) > 8:
            lines.append(f"  … 외 {len(only_mp4) - 8}개")
    if only_png:
        lines.append(f"\n[이미지만 — 같은 번호 MP4 필요] {len(only_png)}개")
        for sid in only_png[:8]:
            lines.append(f"  · {png_map[sid].name}  →  {srt_mp4_name(sid)}")
        if len(only_png) > 8:
            lines.append(f"  … 외 {len(only_png) - 8}개")
    seq = list_compose_pairs_sequential(folder)
    if not matched and seq:
        lines.append("\n[번호 순 1:1 매칭 제안]")
        for sid, mp4, png in seq[:8]:
            lines.append(f"  · {mp4.name} + {png.name}  →  {srt_mp4_name(sid)}")
        if len(seq) > 8:
            lines.append(f"  … 외 {len(seq) - 8}쌍")
    return "\n".join(lines)
