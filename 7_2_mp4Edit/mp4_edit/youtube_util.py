# -*- coding: utf-8 -*-
"""YouTube URL 판별·다운로드."""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path

from mp4_edit.ffmpeg_util import ffmpeg_bin
from mp4_edit.paths import default_output_dir

_YT_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^&\s]+&)*v=|shorts/|embed/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)


def is_youtube_url(text: str) -> bool:
    return bool(_YT_RE.search((text or "").strip()))


def youtube_video_id(text: str) -> str | None:
    m = _YT_RE.search((text or "").strip())
    return m.group(1) if m else None


def normalize_youtube_url(text: str) -> str:
    vid = youtube_video_id(text)
    if not vid:
        return text.strip()
    return f"https://www.youtube.com/watch?v={vid}"


def cached_download_path(url: str) -> Path | None:
    vid = youtube_video_id(url)
    if not vid:
        return None
    dest_dir = default_output_dir()
    for ext in (".mp4", ".webm", ".mkv", ".m4v"):
        p = dest_dir / f"{vid}{ext}"
        if p.is_file() and p.stat().st_size >= 512:
            return p
    return None


def download_youtube(
    url: str,
    *,
    dest_dir: Path | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Path:
    """YouTube 영상을 mp4 로 받아 로컬 경로를 반환."""
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("YouTube 다운로드에 yt-dlp 가 필요합니다.") from e

    url = normalize_youtube_url(url)
    vid = youtube_video_id(url)
    if not vid:
        raise ValueError("YouTube URL 을 인식할 수 없습니다.")

    cached = cached_download_path(url)
    if cached is not None:
        if on_status:
            on_status(f"캐시 사용: {cached.name}")
        return cached

    out = dest_dir or default_output_dir()
    out.mkdir(parents=True, exist_ok=True)
    out_tpl = str(out / f"{vid}.%(ext)s")

    def _hook(d: dict) -> None:
        if not on_status:
            return
        status = d.get("status")
        if status == "downloading":
            pct = d.get("_percent_str", "").strip()
            spd = d.get("_speed_str", "").strip()
            on_status(f"다운로드 중… {pct} {spd}".strip())
        elif status == "finished":
            on_status("병합·저장 중…")

    ff = ffmpeg_bin()
    opts: dict = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "outtmpl": out_tpl,
        "quiet": True,
        "no_warnings": True,
        "progress_hooks": [_hook],
    }
    if ff:
        opts["ffmpeg_location"] = str(ff.parent)

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)

    if info is None:
        raise RuntimeError("YouTube 영상 정보를 가져오지 못했습니다.")

    req_id = info.get("id") or vid
    for ext in (".mp4", ".webm", ".mkv", ".m4v"):
        p = out / f"{req_id}{ext}"
        if p.is_file() and p.stat().st_size >= 512:
            return p

    raise RuntimeError("YouTube 다운로드 파일을 찾을 수 없습니다.")
