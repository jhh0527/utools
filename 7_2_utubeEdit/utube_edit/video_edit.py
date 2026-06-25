"""썸네일 추출·구간 MP4 저장."""

from __future__ import annotations

from pathlib import Path

from utube_edit.media_paths import ffmpeg_executable
from utube_edit.models import SceneSegment
from utube_edit.subprocess_util import subprocess_run_no_window


class VideoEditError(RuntimeError):
    pass


def _require_ffmpeg() -> str:
    ff = ffmpeg_executable()
    if not ff:
        raise VideoEditError("ffmpeg 를 찾을 수 없습니다. wisdom/tools/ffmpeg/bin 또는 PATH를 확인하세요.")
    return ff


def ensure_mp4(src: Path, dest: Path) -> None:
    if src.resolve() == dest.resolve() and src.is_file():
        return
    ff = _require_ffmpeg()
    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-c",
        "copy",
        str(dest),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode == 0 and dest.is_file():
        return
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        str(dest),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or not dest.is_file():
        raise VideoEditError(f"MP4 변환 실패: {r.stderr or r.stdout}")


def extract_thumbnail(video: Path, time_sec: float, out_jpg: Path) -> None:
    ff = _require_ffmpeg()
    out_jpg.parent.mkdir(parents=True, exist_ok=True)
    t = max(0.0, float(time_sec))
    cmd = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{t:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(out_jpg),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or not out_jpg.is_file():
        raise VideoEditError(f"썸네일 추출 실패: {r.stderr or r.stdout}")


def build_scene_thumbnails(video: Path, segments: list[SceneSegment], thumb_dir: Path) -> list[SceneSegment]:
    thumb_dir.mkdir(parents=True, exist_ok=True)
    out: list[SceneSegment] = []
    for seg in segments:
        mid = seg.start_sec + seg.duration_sec * 0.35
        thumb = thumb_dir / f"scene_{seg.index:03d}.jpg"
        try:
            extract_thumbnail(video, mid, thumb)
        except VideoEditError:
            thumb = None
        out.append(
            SceneSegment(
                index=seg.index,
                start_sec=seg.start_sec,
                end_sec=seg.end_sec,
                thumb_path=thumb if thumb and thumb.is_file() else None,
            )
        )
    return out


def export_segment(video: Path, segment: SceneSegment, out_mp4: Path) -> None:
    """구간 MP4 저장 (영상만 — 자막·음성 제외)."""
    ff = _require_ffmpeg()
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    duration = max(0.1, segment.duration_sec)
    base = [
        ff,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{segment.start_sec:.3f}",
        "-i",
        str(video),
        "-t",
        f"{duration:.3f}",
        "-map",
        "0:v:0",
        "-sn",
        "-an",
    ]
    cmd = [
        *base,
        "-c",
        "copy",
        "-avoid_negative_ts",
        "make_zero",
        str(out_mp4),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode == 0 and out_mp4.is_file():
        return
    cmd = [
        *base,
        "-c:v",
        "libx264",
        "-preset",
        "fast",
        "-crf",
        "23",
        str(out_mp4),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0 or not out_mp4.is_file():
        raise VideoEditError(f"구간 저장 실패: {r.stderr or r.stdout}")
