# -*- coding: utf-8 -*-
"""YouTube URL 판별·메타·구간 다운로드."""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mp4_edit.ffmpeg_util import ffmpeg_bin, trim_stream_to_file
from mp4_edit.log_util import mp4_edit_log, mp4_edit_log_exc
from mp4_edit.paths import default_output_dir

_YT_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtube\.com/(?:watch\?(?:[^&\s]+&)*v=|shorts/|embed/)|youtu\.be/)([\w-]{11})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class YoutubeMeta:
    video_id: str
    title: str
    duration: float
    width: int
    height: int


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


def _require_ytdlp():
    try:
        import yt_dlp
    except ImportError as e:
        raise RuntimeError("YouTube 다운로드에 yt-dlp 가 필요합니다.") from e
    return yt_dlp


def _base_opts(*, quiet: bool = True) -> dict:
    ff = ffmpeg_bin()
    opts: dict = {
        "format": "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
        "merge_output_format": "mp4",
        "quiet": quiet,
        "no_warnings": quiet,
        "socket_timeout": 20,
        "retries": 2,
        "fragment_retries": 2,
        "extractor_retries": 2,
        # 회사 프록시·자체서명 인증서 환경에서 SSL 실패 방지
        "nocheckcertificate": True,
    }
    if ff:
        opts["ffmpeg_location"] = str(ff.parent)
    return opts


def _meta_from_info(info: dict, *, vid: str) -> YoutubeMeta:
    dur = float(info.get("duration") or 0.0)
    if dur <= 0:
        raise RuntimeError("YouTube 영상 길이를 알 수 없습니다.")
    w = int(info.get("width") or 0)
    h = int(info.get("height") or 0)
    if w <= 0 or h <= 0:
        for fmt in reversed(info.get("formats") or []):
            if fmt.get("vcodec") not in (None, "none"):
                w = int(fmt.get("width") or 0)
                h = int(fmt.get("height") or 0)
                if w > 0 and h > 0:
                    break
    return YoutubeMeta(
        video_id=info.get("id") or vid,
        title=str(info.get("title") or vid),
        duration=dur,
        width=max(0, w),
        height=max(0, h),
    )


def _stream_url_from_info(info: dict) -> str:
    direct = info.get("url")
    if direct:
        return str(direct)
    for fmt in reversed(info.get("formats") or []):
        if fmt.get("url") and fmt.get("vcodec") not in (None, "none"):
            return str(fmt["url"])
    raise RuntimeError("YouTube 스트림 URL 을 찾을 수 없습니다.")


def _extract_youtube_info(url: str, *, format_selector: str | None = None) -> dict:
    yt_dlp = _require_ytdlp()
    url = normalize_youtube_url(url)
    vid = youtube_video_id(url)
    if not vid:
        raise ValueError("YouTube URL 을 인식할 수 없습니다.")
    opts = _base_opts()
    if format_selector:
        opts["format"] = format_selector
    mp4_edit_log(f"yt-dlp extract_info start vid={vid} format={format_selector or '(default)'}")
    t0 = time.monotonic()
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=False)
    except Exception as e:
        mp4_edit_log_exc(f"yt-dlp extract_info FAIL vid={vid} ({time.monotonic() - t0:.1f}s)", e)
        msg = str(e).strip() or "YouTube 정보 조회 실패"
        raise RuntimeError(msg) from e
    elapsed = time.monotonic() - t0
    if not info:
        mp4_edit_log(f"yt-dlp extract_info empty vid={vid} ({elapsed:.1f}s)")
        raise RuntimeError("YouTube 영상 정보를 가져오지 못했습니다.")
    mp4_edit_log(
        f"yt-dlp extract_info ok vid={vid} dur={info.get('duration')} "
        f"title={str(info.get('title') or '')[:60]!r} ({elapsed:.1f}s)"
    )
    return info


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


def fetch_youtube_meta(url: str) -> YoutubeMeta:
    """전체 다운로드 없이 길이·해상도 등 메타만 조회."""
    url = normalize_youtube_url(url)
    vid = youtube_video_id(url)
    if not vid:
        raise ValueError("YouTube URL 을 인식할 수 없습니다.")
    info = _extract_youtube_info(url)
    return _meta_from_info(info, vid=vid)


def get_youtube_stream_url(url: str) -> str:
    """미리보기 프레임 추출용 직접 URL (짧은 수명)."""
    info = _extract_youtube_info(url, format_selector="best[ext=mp4]/best")
    return _stream_url_from_info(info)


def download_youtube(
    url: str,
    *,
    dest_dir: Path | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Path:
    """YouTube 영상 전체를 mp4 로 받아 로컬 경로를 반환."""
    return download_youtube_section(
        url,
        start_sec=0.0,
        end_sec=None,
        dest_dir=dest_dir,
        on_status=on_status,
    )


def download_youtube_section(
    url: str,
    *,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    dest: Path | None = None,
    dest_dir: Path | None = None,
    on_status: Callable[[str], None] | None = None,
) -> Path:
    """YouTube 영상의 지정 구간만 mp4 로 저장."""
    yt_dlp = _require_ytdlp()
    url = normalize_youtube_url(url)
    vid = youtube_video_id(url)
    if not vid:
        raise ValueError("YouTube URL 을 인식할 수 없습니다.")

    start_sec = max(0.0, float(start_sec))
    mp4_edit_log(
        f"download_youtube_section start vid={vid} start={start_sec} end={end_sec} dest={dest}"
    )
    if on_status:
        on_status("YouTube 정보 조회 중…")
    info = _extract_youtube_info(url, format_selector="best[ext=mp4]/best")
    meta = _meta_from_info(info, vid=vid)
    clip_end = float(end_sec) if end_sec is not None else meta.duration
    mp4_edit_log(f"download_youtube_section meta ok clip_end={clip_end}")
    if clip_end <= start_sec:
        raise ValueError("종료 시점은 시작 시점보다 뒤여야 합니다.")

    full_video = start_sec <= 0.0 and end_sec is None
    if full_video:
        cached = cached_download_path(url)
        if cached is not None:
            if on_status:
                on_status(f"캐시 사용: {cached.name}")
            if dest and dest != cached:
                import shutil

                dest.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(cached, dest)
                return dest
            return cached

        out_dir = Path(dest_dir) if dest_dir else default_output_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        if dest is not None:
            out_path = Path(dest)
            out_tpl = str(out_path.with_suffix("")) + ".%(ext)s"
            final_name = out_path.name if out_path.suffix else f"{out_path.name}.mp4"
        else:
            out_tpl = str(out_dir / f"{vid}.%(ext)s")
            final_name = f"{vid}.mp4"

        def _hook(d: dict) -> None:
            if not on_status:
                return
            status = d.get("status")
            if status == "downloading":
                pct = d.get("_percent_str", "").strip()
                spd = d.get("_speed_str", "").strip()
                on_status(f"다운로드… {pct} {spd}".strip())
            elif status == "finished":
                on_status("병합·저장 중…")

        opts = _base_opts(quiet=True)
        opts["outtmpl"] = out_tpl
        opts["progress_hooks"] = [_hook]

        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)

        if info is None:
            raise RuntimeError("YouTube 다운로드에 실패했습니다.")

        req_id = info.get("id") or vid
        if dest is not None:
            candidates = [out_path]
            if not out_path.suffix:
                candidates.append(out_path.with_suffix(".mp4"))
        else:
            candidates = [out_dir / final_name]
        for ext in ("", ".mp4", ".webm", ".mkv", ".m4v"):
            for base in candidates:
                p = base if ext == "" else base.with_suffix(ext)
                if p.is_file() and p.stat().st_size >= 512:
                    return p
            p = out_dir / f"{req_id}{ext or '.mp4'}"
            if p.is_file() and p.stat().st_size >= 512:
                return p

        raise RuntimeError("YouTube 다운로드 파일을 찾을 수 없습니다.")

    out_dir = Path(dest_dir) if dest_dir else default_output_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    if dest is not None:
        out_path = Path(dest)
        if not out_path.suffix:
            out_path = out_path.with_suffix(".mp4")
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        tag = f"{vid}_{int(start_sec)}_{int(clip_end)}"
        out_path = out_dir / f"{tag}.mp4"

    # yt-dlp download_ranges 는 일부 영상에서 무한 대기 → ffmpeg 스트림 구간 추출
    if on_status:
        on_status("YouTube 스트림 연결 중…")
    stream = _stream_url_from_info(info)
    mp4_edit_log(f"download_youtube_section stream url len={len(stream)} host={stream[:80]!r}…")
    if on_status:
        on_status("구간 추출·저장 중…")
    t0 = time.monotonic()
    try:
        out = trim_stream_to_file(
            stream,
            out_path,
            start_sec=start_sec,
            end_sec=clip_end,
            timeout=180,
        )
    except Exception as e:
        mp4_edit_log_exc(
            f"trim_stream_to_file FAIL dest={out_path} ({time.monotonic() - t0:.1f}s)",
            e,
        )
        raise
    mp4_edit_log(
        f"download_youtube_section done dest={out} size={out.stat().st_size} ({time.monotonic() - t0:.1f}s)"
    )
    return out
