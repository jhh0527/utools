# -*- coding: utf-8 -*-
"""ffmpeg/ffprobe — 미리보기 프레임·구간·영역 자르기."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _win_subprocess_flags() -> dict:
    if sys.platform == "win32" and _WIN_NO_WINDOW:
        return {"creationflags": _WIN_NO_WINDOW}
    return {}


def _tool_bases() -> list[Path]:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return [exe.parent, exe.parent.parent]
    here = Path(__file__).resolve()
    return [here.parents[1], here.parents[2]]


def _ffmpeg_exe(name: str) -> Path | None:
    exe = f"{name}.exe" if sys.platform == "win32" else name
    for base in _tool_bases():
        p = base / "tools" / "ffmpeg" / "bin" / exe
        if p.is_file():
            return p
    w = shutil.which(name)
    return Path(w) if w else None


def ffmpeg_bin() -> Path | None:
    return _ffmpeg_exe("ffmpeg")


def ffprobe_bin() -> Path | None:
    return _ffmpeg_exe("ffprobe")


def probe_duration(path: Path) -> float | None:
    fp = ffprobe_bin()
    if not fp:
        return None
    cmd = [
        str(fp),
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **_win_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        dur = float(r.stdout.strip())
        return dur if dur > 0 else None
    except ValueError:
        return None


def probe_video_size(path: Path) -> tuple[int, int] | None:
    fp = ffprobe_bin()
    if not fp:
        return None
    cmd = [
        str(fp),
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0:s=x",
        str(path),
    ]
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            **_win_subprocess_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    parts = r.stdout.strip().split("x")
    if len(parts) != 2:
        return None
    try:
        w, h = int(parts[0]), int(parts[1])
        return (w, h) if w > 0 and h > 0 else None
    except ValueError:
        return None


def _even(n: int) -> int:
    n = max(2, int(n))
    return n if n % 2 == 0 else n - 1


def extract_frame_png(src: Path, time_sec: float, dest: Path) -> Path:
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("프레임 미리보기에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    t = max(0.0, float(time_sec))
    cmd = [
        str(ff),
        "-y",
        "-ss",
        f"{t:.3f}",
        "-i",
        str(src),
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, **_win_subprocess_flags())
    if r.returncode != 0 or not dest.is_file():
        err = (r.stderr or r.stdout or "프레임 추출 실패").strip()[:400]
        raise RuntimeError(err)
    return dest


def edit_output_path(src: Path, *, output_dir: Path | None = None) -> Path:
    src = Path(src)
    base = Path(output_dir) if output_dir else src.parent
    return base / f"{src.stem}_edit{src.suffix}"


def crop_and_trim(
    src: Path,
    dest: Path,
    *,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
) -> Path:
    """타임라인 구간·사각형 영역을 잘라 ``dest`` 에 저장."""
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"영상 없음: {src}")
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("자르기에 ffmpeg 가 필요합니다 (tools/ffmpeg).")

    start_sec = max(0.0, float(start_sec))
    clip_dur: float | None = None
    if end_sec is not None:
        end_sec = float(end_sec)
        if end_sec <= start_sec:
            raise ValueError("종료 시점은 시작 시점보다 뒤여야 합니다.")
        clip_dur = end_sec - start_sec

    vf_parts: list[str] = []
    if crop_rect is not None:
        x, y, w, h = crop_rect
        w, h = _even(w), _even(h)
        x, y = max(0, int(x)), max(0, int(y))
        if w < 2 or h < 2:
            raise ValueError("자를 영역이 너무 작습니다.")
        vf_parts.append(f"crop={w}:{h}:{x}:{y}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    cmd = [str(ff), "-y", "-ss", f"{start_sec:.3f}", "-i", str(src)]
    if clip_dur is not None:
        cmd.extend(["-t", f"{clip_dur:.3f}"])
    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    r = subprocess.run(cmd, capture_output=True, text=True, **_win_subprocess_flags())
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        err = (r.stderr or r.stdout or "자르기 실패").strip()[:500]
        raise RuntimeError(err)
    return dest


def temp_preview_png() -> Path:
    return Path(tempfile.gettempdir()) / f"mp4_edit_preview_{os.getpid()}.png"
