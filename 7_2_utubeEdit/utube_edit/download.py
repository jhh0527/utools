"""YouTube 영상 다운로드 (yt-dlp)."""

from __future__ import annotations

import re
from pathlib import Path

import yt_dlp

_YT_ID_RE = re.compile(
    r"(?:youtube\.com/watch\?v=|youtu\.be/|youtube\.com/shorts/|youtube\.com/embed/)([A-Za-z0-9_-]{11})"
)

_VIDEO_EXTS = frozenset({".mp4", ".mkv", ".webm", ".mov"})


class DownloadError(RuntimeError):
    pass


def extract_video_id(url: str) -> str | None:
    m = _YT_ID_RE.search((url or "").strip())
    return m.group(1) if m else None


def _is_ssl_cert_error(message: str) -> bool:
    msg = (message or "").casefold()
    return "certificate_verify_failed" in msg or "certificate verify failed" in msg


def _ydl_opts(work: Path | None, *, verify_ssl: bool, download: bool) -> dict:
    opts: dict = {
        "quiet": True,
        "no_warnings": True,
        "noplaylist": True,
    }
    if not verify_ssl:
        opts["nocheckcertificate"] = True
    if download and work is not None:
        opts.update(
            {
                "format": "mp4/bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
                "outtmpl": str(work / "source.%(ext)s"),
                "merge_output_format": "mp4",
            }
        )
    return opts


def _extract_info(url: str, work: Path | None, *, verify_ssl: bool, download: bool) -> dict:
    opts = _ydl_opts(work, verify_ssl=verify_ssl, download=download)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=download)
    except yt_dlp.utils.DownloadError as e:
        raise DownloadError(str(e)) from e
    except Exception as e:
        raise DownloadError(f"다운로드 실패: {e}") from e
    if not isinstance(info, dict):
        raise DownloadError("YouTube 정보를 가져오지 못했습니다.")
    return info


def _extract_info_with_ssl_fallback(
    url: str,
    work: Path | None,
    *,
    download: bool,
) -> dict:
    try:
        return _extract_info(url, work, verify_ssl=True, download=download)
    except DownloadError as e:
        if not _is_ssl_cert_error(str(e)):
            raise
        return _extract_info(url, work, verify_ssl=False, download=download)


def _find_downloaded_video(work: Path) -> Path | None:
    for p in sorted(work.glob("source.*")):
        if p.is_file() and p.suffix.lower() in _VIDEO_EXTS:
            return p
    for p in sorted(work.iterdir()):
        if p.is_file() and p.suffix.lower() in _VIDEO_EXTS and p.name != "segment.mp4":
            return p
    return None


def download_youtube(url: str, out_root: Path) -> tuple[Path, str, str]:
    """영상을 ``out_root/{video_id}/`` 에 저장하고 (mp4 경로, 제목, video_id) 를 반환."""
    url = (url or "").strip()
    video_id = extract_video_id(url)
    if not video_id:
        raise DownloadError("유효한 YouTube 주소가 아닙니다. (watch, youtu.be, shorts)")

    work = out_root / video_id
    work.mkdir(parents=True, exist_ok=True)
    target_mp4 = work / "source.mp4"
    if target_mp4.is_file():
        title = _probe_title(url) or video_id
        return target_mp4, title, video_id

    info = _extract_info_with_ssl_fallback(url, work, download=True)
    title = str(info.get("title") or video_id).strip() or video_id
    downloaded = _find_downloaded_video(work)
    if downloaded is None:
        raise DownloadError("다운로드한 영상 파일을 찾을 수 없습니다.")

    if downloaded.suffix.lower() != ".mp4" or downloaded != target_mp4:
        from utube_edit.video_edit import ensure_mp4

        ensure_mp4(downloaded, target_mp4)
        if downloaded != target_mp4 and downloaded.is_file():
            try:
                downloaded.unlink()
            except OSError:
                pass
        downloaded = target_mp4

    if not downloaded.is_file():
        raise DownloadError("MP4 변환에 실패했습니다.")
    return downloaded, title, video_id


def _probe_title(url: str) -> str | None:
    try:
        info = _extract_info_with_ssl_fallback(url, None, download=False)
    except DownloadError:
        return None
    t = str(info.get("title") or "").strip()
    return t or None
