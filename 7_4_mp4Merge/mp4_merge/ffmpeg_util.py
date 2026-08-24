# -*- coding: utf-8 -*-
"""ffmpeg/ffprobe — 고속 concat(copy) · 음소거 패드."""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import threading
from pathlib import Path
from typing import Callable

_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_DEFAULT_AUDIO_RATE = 48000
_DEFAULT_AUDIO_CH = 2


def _win_flags() -> dict:
    if sys.platform == "win32" and _WIN_NO_WINDOW:
        return {"creationflags": _WIN_NO_WINDOW}
    return {}


def _tool_bases() -> list[Path]:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return [exe.parent, exe.parent.parent, exe.parent.parent.parent]
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
            **_win_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0:
        return None
    try:
        dur = float((r.stdout or "").strip())
        return dur if dur > 0 else None
    except ValueError:
        return None


def probe_video(path: Path) -> tuple[int, int, str, str] | None:
    """(width, height, avg_frame_rate, codec_name)."""
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
        "stream=width,height,avg_frame_rate,r_frame_rate,codec_name",
        "-of",
        "json",
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
            **_win_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    try:
        data = json.loads(r.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        w = int(s.get("width") or 0)
        h = int(s.get("height") or 0)
        rate = str(s.get("avg_frame_rate") or s.get("r_frame_rate") or "").strip()
        codec = str(s.get("codec_name") or "").strip()
        if w <= 0 or h <= 0:
            return None
        return (w, h, rate or "0/0", codec)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def probe_audio(path: Path) -> tuple[int, int, str] | None:
    """(sample_rate, channels, codec_name) — 없으면 None."""
    fp = ffprobe_bin()
    if not fp:
        return None
    cmd = [
        str(fp),
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=sample_rate,channels,codec_name",
        "-of",
        "json",
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
            **_win_flags(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if r.returncode != 0 or not (r.stdout or "").strip():
        return None
    try:
        data = json.loads(r.stdout)
        streams = data.get("streams") or []
        if not streams:
            return None
        s = streams[0]
        rate = int(s.get("sample_rate") or 0)
        ch = int(s.get("channels") or 0)
        codec = str(s.get("codec_name") or "").strip()
        if rate <= 0 or ch <= 0:
            return None
        return (rate, ch, codec)
    except (TypeError, ValueError, json.JSONDecodeError):
        return None


def is_playable_mp4(path: Path) -> bool:
    """moov 등 재생 정보가 있는지 (format duration 조회)."""
    if not path.is_file() or path.stat().st_size < 512:
        return False
    return probe_duration(path) is not None


def silent_audio_pad(
    src: Path,
    dest: Path,
    *,
    sample_rate: int = _DEFAULT_AUDIO_RATE,
    channels: int = _DEFAULT_AUDIO_CH,
) -> Path:
    """영상 copy + 무음 AAC (음소거 클립용)."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        dest.unlink()
    dur = probe_duration(src) or 1.0
    layout = "stereo" if channels >= 2 else "mono"
    cmd = [
        str(ff),
        "-y",
        "-i",
        str(src),
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=channel_layout={layout}:sample_rate={sample_rate}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-t",
        f"{dur:.3f}",
        "-shortest",
        "-movflags",
        "+faststart",
        str(dest),
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_win_flags(),
    )
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        raise RuntimeError((r.stderr or "음소거 패드 실패").strip()[:500])
    return dest


def remux_audio_match(
    src: Path,
    dest: Path,
    *,
    sample_rate: int,
    channels: int,
) -> Path:
    """영상 copy, 음성만 지정 규격 AAC로 맞춤 (전체 재인코딩 없음)."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        dest.unlink()
    if probe_audio(src) is None:
        return silent_audio_pad(src, dest, sample_rate=sample_rate, channels=channels)
    cmd = [
        str(ff),
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-ar",
        str(sample_rate),
        "-ac",
        str(channels),
        "-movflags",
        "+faststart",
        str(dest),
    ]
    r = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        **_win_flags(),
    )
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        raise RuntimeError((r.stderr or "음성 remux 실패").strip()[:500])
    return dest


def concat_copy(
    clips: list[Path],
    dest: Path,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> Path:
    """ffmpeg concat demuxer + ``-c copy`` 만 사용 (영상 재인코딩 없음)."""
    clips = [Path(p) for p in clips if Path(p).is_file()]
    if not clips:
        raise ValueError("연결할 MP4가 없습니다.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        if dest.is_file():
            dest.unlink()
        shutil.copy2(clips[0], dest)
        if on_progress:
            on_progress(100.0)
        return dest

    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg 가 필요합니다 (tools/ffmpeg).")

    list_path = dest.with_suffix(".concat.txt")
    tmp = dest.with_suffix(".concat.tmp.mp4")
    lines = []
    for c in clips:
        s = str(c.resolve()).replace("\\", "/").replace("'", r"'\''")
        lines.append(f"file '{s}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if on_log:
        on_log(f"concat list → {list_path.name} ({len(clips)}개)")
        on_log("mode: -c copy (영상·음성 재인코딩 없음)")

    total_dur = 0.0
    for c in clips:
        d = probe_duration(c)
        if d:
            total_dur += d

    cmd = [
        str(ff),
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        str(tmp),
    ]
    if on_log:
        on_log("ffmpeg: " + " ".join(cmd))

    err_chunks: list[str] = []
    cancelled = False
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_win_flags(),
        )
        assert proc.stdout is not None
        assert proc.stderr is not None

        def _drain_err() -> None:
            for line in proc.stderr:
                err_chunks.append(line)

        t_err = threading.Thread(target=_drain_err, daemon=True)
        t_err.start()
        for line in proc.stdout:
            if cancel_event and cancel_event.is_set():
                cancelled = True
                try:
                    proc.terminate()
                except OSError:
                    pass
                break
            line = (line or "").strip()
            if line.startswith("out_time_ms=") and total_dur > 0.5 and on_progress:
                try:
                    ms = int(line.split("=", 1)[1])
                    pct = min(99.0, (ms / 1_000_000.0) / total_dur * 100.0)
                    on_progress(pct)
                except ValueError:
                    pass
            elif line.startswith("progress=end") and on_progress:
                on_progress(99.5)
        proc.wait(timeout=30)
        t_err.join(timeout=5)
    except Exception as e:
        list_path.unlink(missing_ok=True)
        raise RuntimeError(f"ffmpeg concat 실행 실패: {e}") from e
    finally:
        list_path.unlink(missing_ok=True)

    err_text = "".join(err_chunks).strip()
    if cancelled:
        tmp.unlink(missing_ok=True)
        raise RuntimeError("병합이 중지되었습니다.")

    if tmp.is_file() and tmp.stat().st_size >= 512 and is_playable_mp4(tmp):
        if dest.is_file():
            dest.unlink()
        tmp.replace(dest)
        if on_progress:
            on_progress(100.0)
        return dest

    detail = (err_text or "concat copy 실패 — 클립 코덱·해상도·fps가 다르면 stream copy가 불가합니다.")[
        :800
    ]
    tmp.unlink(missing_ok=True)
    raise RuntimeError(detail)
