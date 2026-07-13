# -*- coding: utf-8 -*-
"""이미지 URL → png/SRT_XXX.png 저장."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import unquote, urlparse

from img_down.srt_chunks import srt_png_name
from img_down.url_filter import is_image_bytes, is_tracking_url, looks_like_image_url

_SRT_IN_URL = re.compile(r"SRT[_\-/]?(\d{1,6})", re.IGNORECASE)
_BAD_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|avif)$", re.IGNORECASE)


def guess_srt_sec_from_url(url: str) -> int | None:
    m = _SRT_IN_URL.search(url or "")
    return int(m.group(1)) if m else None


def sanitize_filename(name: str, *, fallback: str) -> str:
    stem = unquote((name or "").strip()).replace("\r", " ").replace("\n", " ")
    stem = _BAD_FILENAME_CHARS.sub("_", stem).strip(" ._")
    if not stem:
        stem = fallback
    if not _IMAGE_EXT_RE.search(stem):
        stem += ".png"
    return stem


def filename_from_url(url: str, *, fallback: str) -> str:
    try:
        parsed = urlparse(url)
        name = Path(unquote(parsed.path or "")).name
    except ValueError:
        name = ""
    return sanitize_filename(name, fallback=fallback)


def download_url(url: str, dest: Path, *, timeout: float = 120) -> Path:
    url = (url or "").strip()
    if is_tracking_url(url):
        raise RuntimeError(f"추적 URL은 이미지가 아닙니다: {url[:80]}…")
    if not looks_like_image_url(url):
        raise RuntimeError(f"이미지 URL이 아닙니다: {url[:80]}…")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.genspark.ai/",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError(f"빈 응답: {url[:120]}…")
    if not is_image_bytes(data):
        raise RuntimeError(f"이미지 파일이 아닙니다: {url[:120]}…")
    dest.write_bytes(data)
    return dest


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    parent = path.parent
    i = 2
    while True:
        cand = parent / f"{stem}_{i}{suffix}"
        if not cand.exists():
            return cand
        i += 1


def assign_srt_secs(
    items: list[tuple[int | None, str]],
    *,
    fallback_secs: list[int] | None = None,
    default_start_sec: int | None = None,
) -> list[tuple[int, str]]:
    """각 URL에 저장할 SRT 시작초(파일명)를 확정."""
    fb = list(fallback_secs or [])
    fb_i = 0
    auto_i = default_start_sec if default_start_sec is not None else 0
    used: set[int] = set()
    out: list[tuple[int, str]] = []
    for sec, url in items:
        url = (url or "").strip()
        if not url:
            continue
        n = sec
        if n is None:
            n = guess_srt_sec_from_url(url)
        if n is None and fb_i < len(fb):
            n = fb[fb_i]
            fb_i += 1
        if n is None:
            while auto_i in used:
                auto_i += 1
            n = auto_i
            auto_i += 1
        while n in used:
            n += 1
        used.add(int(n))
        out.append((int(n), url))
    return out


def save_images(
    items: list[tuple[int | None, str]],
    png_dir: Path,
    *,
    fallback_secs: list[int] | None = None,
    default_start_sec: int | None = None,
) -> list[Path]:
    """(srt_sec|None, url) 목록을 png_dir에 저장.

    srt_sec가 없으면 fallback_secs 순번을 사용.
    fallback도 없으면 default_start_sec부터 순번 증가 (0부터가 아닐 수 있음).
    """
    png_dir = Path(png_dir)
    png_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for n, url in assign_srt_secs(
        items,
        fallback_secs=fallback_secs,
        default_start_sec=default_start_sec,
    ):
        dest = png_dir / srt_png_name(n)
        try:
            download_url(url, dest)
            saved.append(dest)
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError) as e:
            raise RuntimeError(f"{dest.name} 저장 실패: {e}") from e
    return saved


def save_named_images(
    items: list[tuple[str, str | None]],
    png_dir: Path,
) -> list[Path]:
    """(url, filename_hint) 목록을 filename_hint/URL 파일명 기준으로 저장."""
    png_dir = Path(png_dir)
    png_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    for i, (url, hint) in enumerate(items, start=1):
        url = (url or "").strip()
        if not url:
            continue
        name = sanitize_filename(hint or "", fallback=f"image_{i:03d}.png")
        if name == f"image_{i:03d}.png":
            name = filename_from_url(url, fallback=name)
        dest = unique_path(png_dir / name)
        try:
            download_url(url, dest)
            saved.append(dest)
        except (OSError, urllib.error.URLError, TimeoutError, RuntimeError) as e:
            raise RuntimeError(f"{dest.name} 저장 실패: {e}") from e
    return saved
