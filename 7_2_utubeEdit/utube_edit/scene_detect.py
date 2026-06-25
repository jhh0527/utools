"""ffmpeg 장면 전환 감지."""

from __future__ import annotations

import json
import re
from pathlib import Path

from utube_edit.media_paths import ffmpeg_executable, ffprobe_executable
from utube_edit.models import SceneSegment
from utube_edit.subprocess_util import subprocess_run_no_window

_MIN_SEGMENT_SEC = 0.8


class SceneDetectError(RuntimeError):
    pass


def video_duration_sec(path: Path) -> float:
    fp = ffprobe_executable()
    if not fp:
        raise SceneDetectError("ffprobe 를 찾을 수 없습니다. wisdom/tools/ffmpeg/bin 또는 PATH를 확인하세요.")
    cmd = [
        fp,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(path),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    if r.returncode != 0:
        raise SceneDetectError(f"ffprobe 실패: {r.stderr or r.stdout}")
    try:
        data = json.loads(r.stdout or "{}")
        dur = float((data.get("format") or {}).get("duration") or 0)
    except (json.JSONDecodeError, TypeError, ValueError) as e:
        raise SceneDetectError(f"재생 시간 파싱 실패: {r.stdout!r}") from e
    if dur <= 0:
        raise SceneDetectError("영상 재생 시간을 알 수 없습니다.")
    return dur


def detect_scene_cuts(path: Path, *, threshold: float = 0.35) -> list[float]:
    ff = ffmpeg_executable()
    if not ff:
        raise SceneDetectError("ffmpeg 를 찾을 수 없습니다. wisdom/tools/ffmpeg/bin 또는 PATH를 확인하세요.")
    thr = max(0.05, min(0.95, float(threshold)))
    cmd = [
        ff,
        "-hide_banner",
        "-i",
        str(path),
        "-filter:v",
        f"select='gt(scene,{thr})',showinfo",
        "-f",
        "null",
        "-",
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, errors="replace")
    times: list[float] = []
    for line in (r.stderr or "").splitlines():
        if "pts_time:" not in line:
            continue
        m = re.search(r"pts_time:([\d.]+)", line)
        if m:
            times.append(float(m.group(1)))
    return sorted(set(times))


def build_segments(path: Path, *, threshold: float = 0.35) -> list[SceneSegment]:
    dur = video_duration_sec(path)
    cuts = detect_scene_cuts(path, threshold=threshold)
    boundaries = [0.0]
    for t in cuts:
        if t <= 0 or t >= dur:
            continue
        if t - boundaries[-1] >= _MIN_SEGMENT_SEC:
            boundaries.append(t)
    if dur - boundaries[-1] < _MIN_SEGMENT_SEC and len(boundaries) > 1:
        boundaries.pop()
    if boundaries[-1] < dur:
        boundaries.append(dur)

    if len(boundaries) < 2:
        return [SceneSegment(index=1, start_sec=0.0, end_sec=dur)]

    out: list[SceneSegment] = []
    for i in range(len(boundaries) - 1):
        start, end = boundaries[i], boundaries[i + 1]
        if end - start < 0.2:
            continue
        out.append(SceneSegment(index=len(out) + 1, start_sec=start, end_sec=end))
    if not out:
        return [SceneSegment(index=1, start_sec=0.0, end_sec=dur)]
    return out
