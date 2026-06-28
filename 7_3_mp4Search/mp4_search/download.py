# -*- coding: utf-8 -*-
"""스톡 영상·썸네일 다운로드."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from collections.abc import Callable
from pathlib import Path


_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_active_ffmpeg_proc: subprocess.Popen | None = None
_active_ffmpeg_lock = threading.Lock()


def _win_subprocess_flags() -> dict:
    if sys.platform == "win32" and _WIN_NO_WINDOW:
        return {"creationflags": _WIN_NO_WINDOW}
    return {}


class ComposeStopped(Exception):
    """합성 중지 — ``path`` 가 있으면 해당 시점까지 저장된 MP4."""

    def __init__(self, path: Path | None = None, message: str = "합성이 중지되었습니다.") -> None:
        self.path = path
        super().__init__(message)


def _ffmpeg_exe(name: str) -> Path | None:
    if getattr(sys, "frozen", False):
        bases = [Path(sys.executable).resolve().parent, Path(sys.executable).resolve().parent.parent]
    else:
        bases = [Path(__file__).resolve().parents[2], Path(__file__).resolve().parents[3]]
    exe = f"{name}.exe" if sys.platform == "win32" else name
    for base in bases:
        d = base / "tools" / "ffmpeg" / "bin" / exe
        if d.is_file():
            return d
    w = shutil.which(name)
    return Path(w) if w else None


def _ffmpeg_bin() -> Path | None:
    return _ffmpeg_exe("ffmpeg")


def _set_active_ffmpeg_proc(proc: subprocess.Popen | None) -> None:
    global _active_ffmpeg_proc
    with _active_ffmpeg_lock:
        _active_ffmpeg_proc = proc


def abort_compose_ffmpeg() -> None:
    """합성 중지 — 실행 중 ffmpeg 프로세스 즉시 종료."""
    with _active_ffmpeg_lock:
        proc = _active_ffmpeg_proc
    if proc is not None and proc.poll() is None:
        try:
            proc.kill()
        except OSError:
            pass
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            pass


def _start_cancel_watcher(
    cancel_event: threading.Event | None,
    proc: subprocess.Popen,
) -> threading.Thread | None:
    if not cancel_event:
        return None

    def _watch() -> None:
        cancel_event.wait()
        if proc.poll() is None:
            try:
                proc.kill()
            except OSError:
                pass

    t = threading.Thread(target=_watch, daemon=True)
    t.start()
    return t


def _video_only_encode_args(*, preset: str = "medium") -> list[str]:
    return [
        "-c:v",
        "libx264",
        "-preset",
        preset,
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
    ]


def _compatible_mp4_encode_args() -> list[str]:
    return [
        *_video_only_encode_args(),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]


_COMPOSE_FPS = 30


def _even_dim(n: int) -> int:
    n = max(16, int(n))
    return n - n % 2


def _normalize_video_vf(width: int, height: int, fps: int = _COMPOSE_FPS) -> str:
    """타임라인 합성 — 모든 클립을 동일 해상도·fps 로 맞춤."""
    w = _even_dim(width)
    h = _even_dim(height)
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black,"
        f"setsar=1,fps={fps},format=yuv420p"
    )


def trim_video(
    src: Path,
    dest: Path,
    *,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    force_encode: bool = False,
    loop_to_duration: bool = False,
    normalize_size: tuple[int, int] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """구간 잘라 저장. end_sec 없으면 start 이후 끝까지."""
    src = Path(src)
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    start_sec = max(0.0, float(start_sec))
    clip_dur = (end_sec - start_sec) if end_sec is not None and end_sec > start_sec else None
    ff = _ffmpeg_bin()
    if not ff:
        if start_sec <= 0 and end_sec is None:
            dest.write_bytes(src.read_bytes())
            return dest
        raise RuntimeError("영상 구간 자르기에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    win = _win_subprocess_flags()
    if not force_encode:
        cmd = [str(ff), "-y", "-ss", f"{start_sec:.3f}", "-i", str(src)]
        if clip_dur is not None:
            cmd.extend(["-t", f"{clip_dur:.3f}"])
        cmd.extend(["-c", "copy", str(dest)])
        r = subprocess.run(cmd, capture_output=True, text=True, **win)
        if r.returncode == 0 and dest.is_file() and dest.stat().st_size >= 512:
            return dest
    cmd = [str(ff), "-y", "-progress", "pipe:1", "-nostats", "-ss", f"{start_sec:.3f}"]
    if loop_to_duration and clip_dur is not None:
        cmd.extend(["-stream_loop", "-1"])
    cmd.extend(["-i", str(src)])
    if clip_dur is not None:
        cmd.extend(["-t", f"{clip_dur:.3f}"])
    if normalize_size:
        w, h = normalize_size
        cmd.extend(["-vf", _normalize_video_vf(w, h), "-an", *_video_only_encode_args()])
    else:
        cmd.extend(_compatible_mp4_encode_args())
    cmd.append(str(dest))
    if cancel_event is not None:
        cancelled, err_text = _run_ffmpeg_compose(
            cmd,
            cancel_event=cancel_event,
            duration_sec=clip_dur,
            on_progress=on_progress,
        )
        if dest.is_file() and dest.stat().st_size >= 512:
            if cancelled:
                raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
            return dest
        if cancelled:
            raise ComposeStopped(None, "합성이 중지되었습니다.")
        raise RuntimeError((err_text or "ffmpeg 구간 자르기 실패").strip()[:400])
    r2 = subprocess.run(cmd, capture_output=True, text=True, **win)
    if r2.returncode != 0 or not dest.is_file():
        raise RuntimeError((r2.stderr or "ffmpeg 구간 자르기 실패").strip()[:400])
    return dest


def _ensure_clip_duration(
    path: Path,
    target_sec: float,
    *,
    cancel_event: threading.Event | None = None,
) -> None:
    """렌더된 클립이 목표 길이보다 길면 재자르기 (타임라인 누적 오차 방지)."""
    path = Path(path)
    target = max(0.1, float(target_sec))
    probe = _probe_media_duration(path)
    if probe is None or probe <= target + 0.12:
        return
    tmp = path.with_suffix(".durfix.tmp.mp4")
    trim_video(
        path,
        tmp,
        start_sec=0.0,
        end_sec=target,
        force_encode=True,
        cancel_event=cancel_event,
    )
    if tmp.is_file() and tmp.stat().st_size >= 512:
        path.unlink(missing_ok=True)
        tmp.replace(path)


def _ffmpeg_bin_legacy() -> Path | None:
    return _ffmpeg_exe("ffplay")


def download_url(url: str, dest: Path, *, timeout: float = 120) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    dest.write_bytes(data)
    return dest


def download_thumbnail(url: str, dest: Path) -> Path | None:
    if not url:
        return None
    try:
        return download_url(url, dest, timeout=30)
    except (OSError, urllib.error.URLError, TimeoutError):
        return None


_VIDEO_EXTS = (".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi")
_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")
_DOWNLOAD_ASSET_EXTS = _VIDEO_EXTS + _IMAGE_EXTS


def _is_video_file(path: Path) -> bool:
    return path.suffix.lower() in _VIDEO_EXTS


def _is_image_file(path: Path) -> bool:
    return path.suffix.lower() in _IMAGE_EXTS


def find_download_video(download_dir: Path, name: str) -> Path | None:
    """다운로드 폴더에서 영상 파일 찾기 (확장자 생략 가능)."""
    found = find_download_asset(download_dir, name)
    if found and _is_video_file(found):
        return found
    return None


def find_download_asset(download_dir: Path, name: str) -> Path | None:
    """다운로드 폴더에서 영상·이미지 파일 찾기 (확장자 생략 가능)."""
    dl = Path(download_dir)
    if not dl.is_dir():
        return None
    raw = (name or "").strip()
    if not raw:
        return None
    direct = dl / raw
    if direct.is_file() and direct.suffix.lower() in _DOWNLOAD_ASSET_EXTS:
        return direct
    stem = Path(raw).stem
    if stem and stem != raw:
        for ext in _DOWNLOAD_ASSET_EXTS:
            cand = dl / f"{stem}{ext}"
            if cand.is_file():
                return cand
    if not Path(raw).suffix:
        for ext in _DOWNLOAD_ASSET_EXTS:
            cand = dl / f"{raw}{ext}"
            if cand.is_file():
                return cand
    low = raw.lower()
    try:
        for child in dl.iterdir():
            if child.is_file() and child.name.lower() == low and child.suffix.lower() in _DOWNLOAD_ASSET_EXTS:
                return child
    except OSError:
        return None
    return None


def copy_local_video(src: Path, dest: Path) -> Path:
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        dest.unlink()
    shutil.copy2(src, dest)
    return dest


_COMPOSE_MAX_W = 1920
_COMPOSE_MAX_H = 1080
_COMPOSE_MIN_W = 640
_COMPOSE_MIN_H = 360
_JPG_QUALITY = 90


def resolve_compose_canvas_size(
    *mp4_paths: Path,
    folder: Path | None = None,
) -> tuple[int, int]:
    """합성 캔버스 크기 — MP4 최대 해상도(상한 1920×1080, 하한 640×360)."""
    from mp4_search.naming import scan_srt_assets

    max_w, max_h = _COMPOSE_MIN_W, _COMPOSE_MIN_H
    paths: list[Path] = []
    for p in mp4_paths:
        if p:
            paths.append(Path(p))
    if folder:
        mp4_map, _ = scan_srt_assets(Path(folder))
        paths.extend(mp4_map.values())
    found = False
    for video in paths:
        if not video.is_file():
            continue
        size = _probe_video_size(video)
        if not size:
            continue
        found = True
        w, h = size
        max_w = max(max_w, min(int(w), _COMPOSE_MAX_W))
        max_h = max(max_h, min(int(h), _COMPOSE_MAX_H))
    if not found:
        max_w, max_h = _COMPOSE_MAX_W, _COMPOSE_MAX_H
    return _even_dim(max_w), _even_dim(max_h)


def _resize_contain_rgb(im, width: int, height: int, *, fill=(0, 0, 0)):
    """캔버스 안에 이미지 전체가 들어가도록 (레터박스)."""
    from PIL import Image

    im = im.convert("RGB")
    width = max(16, int(width))
    height = max(16, int(height))
    iw, ih = im.size
    if iw <= 0 or ih <= 0:
        canvas = Image.new("RGB", (width, height), fill)
        return canvas
    scale = min(width / iw, height / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (width, height), fill)
    canvas.paste(im, ((width - nw) // 2, (height - nh) // 2))
    return canvas


def _resize_cover_rgb(im, width: int, height: int):
    from PIL import Image

    im = im.convert("RGB")
    width = max(16, int(width))
    height = max(16, int(height))
    iw, ih = im.size
    if iw <= 0 or ih <= 0:
        return im.resize((width, height), Image.Resampling.LANCZOS)
    scale = max(width / iw, height / ih)
    nw = max(1, int(round(iw * scale)))
    nh = max(1, int(round(ih * scale)))
    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
    left = max(0, (nw - width) // 2)
    top = max(0, (nh - height) // 2)
    return im.crop((left, top, left + width, top + height))


def _remove_legacy_image_siblings(dest: Path) -> None:
    """같은 ``SRT_NNN`` PNG 등 이전 확장자 제거."""
    dest = Path(dest)
    for ext in (".png", ".PNG", ".webp", ".WEBP"):
        old = dest.with_suffix(ext)
        if old.is_file():
            try:
                if old.resolve() != dest.resolve():
                    old.unlink()
            except OSError:
                pass


def save_srt_image_jpg(
    src: Path,
    dest: Path,
    *,
    width: int | None = None,
    height: int | None = None,
    canvas_folder: Path | None = None,
    reference_mp4: Path | None = None,
) -> Path:
    """이미지 → ``SRT_NNN.jpg`` (합성 해상도 contain · 전체 표시)."""
    from PIL import Image

    src = Path(src)
    dest = Path(dest)
    if dest.suffix.lower() not in (".jpg", ".jpeg"):
        dest = dest.with_suffix(".jpg")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        dest.unlink()
    if width is None or height is None:
        ref_args = (
            (reference_mp4,)
            if reference_mp4 and Path(reference_mp4).is_file()
            else ()
        )
        w, h = resolve_compose_canvas_size(
            *ref_args,
            folder=canvas_folder or dest.parent,
        )
        width = w if width is None else width
        height = h if height is None else height
    im = Image.open(src)
    out = _resize_contain_rgb(im, width, height)
    out.save(dest, "JPEG", quality=_JPG_QUALITY, optimize=True)
    _remove_legacy_image_siblings(dest)
    return dest


def optimize_srt_images_in_folder(folder: Path) -> list[tuple[Path, Path]]:
    """폴더 내 ``SRT_NNN.png`` → JPG 변환 + 합성 해상도 cover 리사이즈."""
    from mp4_search.naming import scan_srt_assets, srt_jpg_name

    folder = Path(folder)
    _, img_map = scan_srt_assets(folder)
    width, height = resolve_compose_canvas_size(folder=folder)
    done: list[tuple[Path, Path]] = []
    for key in sorted(img_map):
        src = img_map[key]
        if src.suffix.lower() != ".png":
            continue
        dest = folder / srt_jpg_name(key)
        save_srt_image_jpg(src, dest, width=width, height=height)
        done.append((src, dest))
    return done


def copy_local_image_as_png(src: Path, dest: Path) -> Path:
    """이미지를 ``SRT_NNN.png`` 로 저장 (jpg/webp 등은 PNG 변환, 리사이즈 없음)."""
    src = Path(src)
    dest = Path(dest)
    if dest.suffix.lower() != ".png":
        dest = dest.with_suffix(".png")
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.is_file():
        dest.unlink()
    if src.suffix.lower() == ".png":
        shutil.copy2(src, dest)
        return dest
    from PIL import Image

    im = Image.open(src).convert("RGB")
    im.save(dest, "PNG")
    return dest


def _ffprobe_bin() -> Path | None:
    return _ffmpeg_exe("ffprobe")


def _probe_video_size(path: Path) -> tuple[int, int] | None:
    fp = _ffprobe_bin()
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


def _probe_video_duration(path: Path) -> float | None:
    fp = _ffprobe_bin()
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


def _probe_media_duration(path: Path) -> float | None:
    """ffprobe 로 미디어 길이(초)."""
    return _probe_video_duration(path)  # format=duration works for audio too


def _probe_has_audio_stream(path: Path) -> bool:
    fp = _ffprobe_bin()
    if not fp:
        return False
    cmd = [
        str(fp),
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=codec_type",
        "-of",
        "csv=p=0",
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
        return False
    return r.returncode == 0 and bool(r.stdout.strip())


def _resolve_compose_size(jobs: list) -> tuple[int, int]:
    """합성 캔버스 — 모든 구간 영상의 최대 크기(상한 1920×1080, 하한 640×360)."""
    paths = [
        Path(job.video)
        for job in jobs
        if getattr(job, "video", None) and Path(job.video).is_file()
    ]
    return resolve_compose_canvas_size(*paths)


def compose_black_pad(
    dest: Path,
    *,
    duration_sec: float,
    width: int = 1920,
    height: int = 1080,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """타임라인 빈 구간 — 검은 화면 클립."""
    ff = _ffmpeg_bin()
    if not ff:
        raise RuntimeError("타임라인 빈 구간 생성에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    w = max(16, int(width))
    h = max(16, int(height))
    cmd = [
        str(ff),
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={w}x{h}:r={_COMPOSE_FPS}",
        *_video_only_encode_args(),
        str(dest),
    ]
    cancelled, err_text = _run_ffmpeg_compose(
        cmd,
        cancel_event=cancel_event,
        duration_sec=duration_sec,
        on_progress=on_progress,
    )
    if dest.is_file() and dest.stat().st_size >= 512:
        if cancelled:
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        return dest
    if cancelled:
        raise ComposeStopped(None, "합성이 중지되었습니다.")
    raise RuntimeError((err_text or "빈 구간 생성 실패").strip()[:400])


def compose_hold_video(
    src: Path,
    dest: Path,
    *,
    duration_sec: float,
    normalize_size: tuple[int, int] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """이전 영상 마지막 프레임을 ``duration_sec`` 동안 유지."""
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"영상 없음: {src}")
    ff = _ffmpeg_bin()
    if not ff:
        raise RuntimeError("정지 화면 생성에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    dur = max(0.1, float(duration_sec))
    src_dur = _probe_media_duration(src) or dur
    ss = max(0.0, src_dur - 0.05)
    pad_extra = max(0.0, dur - 0.05)
    hold_vf = f"tpad=stop_mode=clone:stop_duration={pad_extra:.3f}" if pad_extra > 0.01 else "null"
    if normalize_size:
        norm = _normalize_video_vf(*normalize_size)
        vf = f"{hold_vf},{norm}" if hold_vf != "null" else norm
    else:
        vf = hold_vf
    cmd = [
        str(ff),
        "-y",
        "-progress",
        "pipe:1",
        "-nostats",
        "-ss",
        f"{ss:.3f}",
        "-i",
        str(src),
        "-vf",
        vf,
        "-an",
        *_video_only_encode_args(),
        str(dest),
    ]
    cancelled, err_text = _run_ffmpeg_compose(
        cmd,
        cancel_event=cancel_event,
        duration_sec=dur,
        on_progress=on_progress,
    )
    if dest.is_file() and dest.stat().st_size >= 512:
        if cancelled:
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        return dest
    if cancelled:
        raise ComposeStopped(None, "합성이 중지되었습니다.")
    raise RuntimeError((err_text or "정지 화면 생성 실패").strip()[:400])


def _image_overlay_filter_candidates(video: Path) -> list[str]:
    size = _probe_video_size(video)
    if size:
        w, h = size
        base = (
            f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1[base];"
        )
        img = (
            f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
            f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[img];"
        )
        return [base + img + "[base][img]overlay=0:0:format=auto,setsar=1[vout]"]
    return [
        "[0:v][1:v]scale2ref=w=iw:h=ih:force_original_aspect_ratio=decrease,"
        "pad=iw:ih:(ow-iw)/2:(oh-ih)/2:color=black@0[ov][base];"
        "[base][ov]overlay=0:0:format=auto[vout]",
    ]


def _run_ffmpeg_compose(
    cmd: list[str],
    *,
    cancel_event: threading.Event | None,
    duration_sec: float | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[bool, str]:
    """ffmpeg 실행. (취소 여부, stderr 텍스트)."""
    if duration_sec and duration_sec > 0:
        out_path = cmd[-1]
        cmd = cmd[:-1] + ["-t", f"{duration_sec:.3f}", out_path]
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
        **_win_subprocess_flags(),
    )
    _set_active_ffmpeg_proc(proc)
    watcher = _start_cancel_watcher(cancel_event, proc)
    cancelled = False
    err_lines: list[str] = []
    out_ms_re = re.compile(r"out_time_ms=(\d+)")
    dur_us = int(max(0.1, float(duration_sec or 0)) * 1_000_000) if duration_sec else 0
    wait_timeout = max(120.0, float(duration_sec or 30) * 4.0)
    run_deadline = time.monotonic() + max(600.0, float(duration_sec or 60) * 15.0)
    try:
        assert proc.stdout is not None
        for line in proc.stdout:
            err_lines.append(line)
            if on_progress and dur_us > 0:
                m = out_ms_re.search(line)
                if m:
                    try:
                        pct = min(100.0, int(m.group(1)) / dur_us * 100.0)
                        on_progress(pct)
                    except (ValueError, ZeroDivisionError):
                        pass
            if cancel_event and cancel_event.is_set() and proc.poll() is None:
                cancelled = True
                try:
                    proc.kill()
                except OSError:
                    pass
                break
            if time.monotonic() > run_deadline and proc.poll() is None:
                err_lines.append("\n[timeout] ffmpeg 응답 시간 초과\n")
                try:
                    proc.kill()
                except OSError:
                    pass
                break
        if proc.poll() is None:
            if proc.stdin and not proc.stdin.closed:
                proc.stdin.close()
            try:
                proc.wait(timeout=wait_timeout)
            except subprocess.TimeoutExpired:
                err_lines.append("\n[timeout] ffmpeg 종료 대기 시간 초과\n")
                proc.kill()
                proc.wait()
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    except Exception:
        if proc.poll() is None:
            proc.kill()
            proc.wait()
        raise
    finally:
        _set_active_ffmpeg_proc(None)
        if proc.stdin and not proc.stdin.closed:
            try:
                proc.stdin.close()
            except OSError:
                pass
        if watcher and watcher.is_alive():
            watcher.join(timeout=0.5)
    err_text = "".join(err_lines[-80:])
    return cancelled, err_text


def compose_video_image(
    video: Path,
    image: Path,
    dest: Path,
    *,
    duration_sec: float | None = None,
    video_start_sec: float = 0.0,
    image_effect: str = "fixed",
    normalize_size: tuple[int, int] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """적용된 MP4 위에 이미지를 캔버스 전체에 맞춰 오버레이하여 합성 저장."""
    from mp4_search.image_effects import (
        image_effect_needs_loop,
        image_overlay_filters,
        normalize_png_effect,
    )

    video = Path(video)
    image = Path(image)
    dest = Path(dest)
    if not video.is_file():
        raise FileNotFoundError(f"MP4 없음: {video}")
    if not image.is_file():
        raise FileNotFoundError(f"PNG 없음: {image}")
    ff = _ffmpeg_bin()
    if not ff:
        raise RuntimeError("영상·이미지 합성에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".compose.tmp.mp4")
    effect = normalize_png_effect(image_effect)
    if normalize_size:
        w, h = normalize_size
    else:
        probed = _probe_video_size(video)
        w, h = probed if probed else (1280, 720)
    clip_dur = duration_sec
    if not clip_dur or clip_dur <= 0:
        clip_dur = _probe_media_duration(video) or 5.0
    filters = image_overlay_filters(w, h, effect=effect, duration_sec=float(clip_dur), fps=30)
    if normalize_size:
        norm = _normalize_video_vf(w, h)
        filters = [fc.replace("[vout]", "[vpre]") + f";[vpre]{norm}[vout]" for fc in filters]
    cancelled = False
    err_text = ""
    start_sec = max(0.0, float(video_start_sec))
    loop_img = image_effect_needs_loop(effect)
    for fc_idx, fc in enumerate(filters):
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        with_audio = fc_idx == 0 and not normalize_size
        cmd = [
            str(ff),
            "-y",
            "-progress",
            "pipe:1",
            "-nostats",
        ]
        if start_sec > 0.01:
            cmd.extend(["-ss", f"{start_sec:.3f}"])
        cmd.extend(["-i", str(video)])
        if loop_img:
            cmd.extend(["-loop", "1"])
        cmd.extend(
            [
                "-i",
                str(image),
                "-filter_complex",
                fc,
                "-map",
                "[vout]",
            ]
        )
        if with_audio:
            cmd.extend(["-map", "0:a?"])
        if normalize_size:
            cmd.extend(["-an", *_video_only_encode_args()])
        else:
            cmd.extend(
                [
                    "-c:v",
                    "libx264",
                    "-preset",
                    "medium",
                    "-crf",
                    "20",
                    "-pix_fmt",
                    "yuv420p",
                ]
            )
            if with_audio:
                cmd.extend(["-c:a", "aac", "-b:a", "192k"])
        cmd.extend(["-movflags", "+faststart", str(tmp)])
        cancelled, err_text = _run_ffmpeg_compose(
            cmd,
            cancel_event=cancel_event,
            duration_sec=duration_sec,
            on_progress=on_progress,
        )
        if cancelled:
            break
        if tmp.is_file() and tmp.stat().st_size >= 512:
            break
    if tmp.is_file() and tmp.stat().st_size >= 512:
        if dest.is_file():
            dest.unlink()
        tmp.replace(dest)
        if cancelled:
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        return dest
    tmp.unlink(missing_ok=True)
    if cancelled:
        raise ComposeStopped(None, "합성이 중지되었습니다.")
    raise RuntimeError((err_text or "ffmpeg 합성 실패").strip()[:400])


def compose_timeline_clip(
    video: Path,
    dest: Path,
    *,
    image: Path | None = None,
    duration_sec: float | None = None,
    video_start_sec: float = 0.0,
    image_effect: str = "fixed",
    is_hold: bool = False,
    normalize_size: tuple[int, int] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> Path:
    """타임라인 구간 — MP4 (+선택 PNG 오버레이) 저장."""
    if is_hold:
        return compose_hold_video(
            video,
            dest,
            duration_sec=duration_sec or 0.1,
            normalize_size=normalize_size,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
    if image and image.is_file():
        return compose_video_image(
            video,
            image,
            dest,
            duration_sec=duration_sec,
            video_start_sec=video_start_sec,
            image_effect=image_effect,
            normalize_size=normalize_size,
            cancel_event=cancel_event,
            on_progress=on_progress,
        )
    dur = duration_sec if duration_sec and duration_sec > 0 else None
    start_sec = max(0.0, float(video_start_sec))
    loop_fill = False
    if dur:
        src_dur = _probe_media_duration(video)
        avail = (src_dur - start_sec) if src_dur else None
        if avail is not None and avail + 0.05 < dur:
            loop_fill = True
    end_sec = (start_sec + dur) if dur else None
    return trim_video(
        video,
        dest,
        start_sec=start_sec,
        end_sec=end_sec,
        force_encode=True,
        loop_to_duration=loop_fill,
        normalize_size=normalize_size,
        cancel_event=cancel_event,
        on_progress=on_progress,
    )


def _copy_video_only(src: Path, dest: Path, *, fast_copy: bool = True) -> Path:
    """영상만 복사·재인코딩 (음성 트랙 제거)."""
    ff = _ffmpeg_bin()
    if not ff:
        if fast_copy:
            shutil.copy2(src, dest)
            return dest
        raise RuntimeError("영상 처리에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    vcodec = ["-c:v", "copy"] if fast_copy else _video_only_encode_args(preset="veryfast")
    cmd = [
        str(ff),
        "-y",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-an",
        *vcodec,
        "-movflags",
        "+faststart",
        str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, **_win_subprocess_flags())
    if r.returncode == 0 and dest.is_file() and dest.stat().st_size >= 512:
        return dest
    if fast_copy:
        return _copy_video_only(src, dest, fast_copy=False)
    raise RuntimeError((r.stderr or "영상-only 복사 실패").strip()[:400])


def concat_videos(
    clips: list[Path],
    dest: Path,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
    fast_copy: bool = False,
    video_only: bool = False,
) -> Path:
    """클립 목록을 이어 붙여 하나의 MP4로 저장."""
    clips = [Path(p) for p in clips if Path(p).is_file()]
    if not clips:
        raise ValueError("연결할 영상 클립이 없습니다.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    if len(clips) == 1:
        if dest.is_file():
            dest.unlink()
        if video_only:
            _copy_video_only(clips[0], dest, fast_copy=fast_copy)
        else:
            shutil.copy2(clips[0], dest)
        if on_progress:
            on_progress(100.0)
        if cancel_event and cancel_event.is_set():
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        return dest
    ff = _ffmpeg_bin()
    if not ff:
        raise RuntimeError("영상 연결에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    list_path = dest.with_suffix(".concat.txt")
    tmp = dest.with_suffix(".concat.tmp.mp4")
    lines = []
    for c in clips:
        s = str(c.resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{s}'")
    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    cancelled = False
    err_text = ""
    if video_only:
        encode_tail = (
            ["-map", "0:v:0", "-c:v", "copy", "-an", "-movflags", "+faststart"]
            if fast_copy
            else [
                "-vf",
                "setpts=PTS-STARTPTS",
                "-map",
                "0:v:0",
                *_video_only_encode_args(preset="veryfast"),
                "-an",
            ]
        )
    else:
        encode_tail = (
            ["-c", "copy"]
            if fast_copy
            else ["-vf", "setpts=PTS-STARTPTS", *_compatible_mp4_encode_args()]
        )
    try:
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
            *encode_tail,
            str(tmp),
        ]
        if not fast_copy:
            cancelled, err_text = _run_ffmpeg_compose(cmd, cancel_event=cancel_event, on_progress=on_progress)
        else:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                **_win_subprocess_flags(),
            )
            _set_active_ffmpeg_proc(proc)
            watcher = _start_cancel_watcher(cancel_event, proc)
            try:
                if proc.stdout:
                    proc.stdout.read()
                cancelled = bool(cancel_event and cancel_event.is_set())
                try:
                    proc.wait(timeout=300)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait()
                    cancelled = True
            finally:
                _set_active_ffmpeg_proc(None)
                if watcher and watcher.is_alive():
                    watcher.join(timeout=0.5)
            if on_progress:
                on_progress(100.0)
    finally:
        list_path.unlink(missing_ok=True)
    if tmp.is_file() and tmp.stat().st_size >= 512:
        if dest.is_file():
            dest.unlink()
        tmp.replace(dest)
        if cancelled:
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        return dest
    tmp.unlink(missing_ok=True)
    if cancelled:
        raise ComposeStopped(None, "합성이 중지되었습니다.")
    if fast_copy:
        return concat_videos(
            clips,
            dest,
            cancel_event=None,
            on_progress=on_progress,
            fast_copy=False,
            video_only=video_only,
        )
    raise RuntimeError((err_text or "ffmpeg 연결 실패").strip()[:400])


def mux_mp3_to_video(
    video: Path,
    audio: Path,
    dest: Path,
    *,
    cancel_event: threading.Event | None = None,
    on_progress: Callable[[float], None] | None = None,
    fast_copy: bool = False,
) -> Path:
    """영상에 MP3 음성을 입혀 저장 (영상 길이 유지, 음성은 무음 패드)."""
    video = Path(video)
    audio = Path(audio)
    dest = Path(dest)
    if not video.is_file():
        raise FileNotFoundError(f"영상 없음: {video}")
    if not audio.is_file():
        raise FileNotFoundError(f"MP3 없음: {audio}")
    ff = _ffmpeg_bin()
    if not ff:
        raise RuntimeError("음성 합성에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(".audio.tmp.mp4")
    vid_dur = _probe_media_duration(video)
    vcopy = ["-c:v", "copy"] if fast_copy else _video_only_encode_args(preset="veryfast")
    vencode = _video_only_encode_args(preset="veryfast")
    audio_tail = ["-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]

    attempts: list[tuple[list[str], str | None]] = []
    if vid_dur and vid_dur > 0.05:
        attempts.append(
            (
                [
                    "-filter_complex",
                    f"[1:a]apad=whole_dur={vid_dur:.3f}[aout]",
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    *vcopy,
                    *audio_tail,
                ],
                "apad",
            )
        )
    attempts.extend(
        [
            (
                [
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    *vcopy,
                    *audio_tail,
                ],
                "direct",
            ),
            (
                [
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    *vencode,
                    *audio_tail,
                ],
                "reencode",
            ),
        ]
    )

    cancelled = False
    err_text = ""
    for idx, (tail, _tag) in enumerate(attempts):
        if tmp.is_file():
            tmp.unlink(missing_ok=True)
        cmd = [
            str(ff),
            "-y",
            "-progress",
            "pipe:1",
            "-nostats",
            "-i",
            str(video),
            "-i",
            str(audio),
            *tail,
            str(tmp),
        ]
        cancelled, err_text = _run_ffmpeg_compose(cmd, cancel_event=cancel_event, on_progress=on_progress)
        if tmp.is_file() and tmp.stat().st_size >= 512 and _probe_has_audio_stream(tmp):
            break
        if cancelled:
            break
        if idx + 1 >= len(attempts):
            break

    if tmp.is_file() and tmp.stat().st_size >= 512 and _probe_has_audio_stream(tmp):
        if dest.is_file():
            dest.unlink()
        tmp.replace(dest)
        if cancelled:
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        return dest
    tmp.unlink(missing_ok=True)
    if cancelled:
        raise ComposeStopped(None, "합성이 중지되었습니다.")
    raise RuntimeError((err_text or "MP3 음성 합성 실패 — ffmpeg·MP3 파일을 확인하세요.").strip()[:400])


ComposeProgressFn = Callable[[float, float | None, int, int], None]


def compose_timeline_to_all_mp4(
    jobs: list,
    dest: Path,
    work_dir: Path,
    *,
    audio_mp3: Path | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ComposeProgressFn | None = None,
) -> Path:
    """타임라인 구간 클립을 렌더한 뒤 ``all.mp4`` 로 연결."""
    from mp4_search.timeline_compose import TimelineComposeJob

    if not jobs:
        raise ValueError("합성할 구간이 없습니다.")
    dest = Path(dest)
    work_dir = Path(work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)
    total = len(jobs)
    segment_weight = 0.82 if audio_mp3 and Path(audio_mp3).is_file() else 0.88
    audio_weight = 0.06 if audio_mp3 and Path(audio_mp3).is_file() else 0.0
    concat_weight = 1.0 - segment_weight - audio_weight
    clips: list[Path] = []
    stopped = False
    pad_w, pad_h = _resolve_compose_size(jobs)
    norm_size = (pad_w, pad_h)

    def report(overall: float, mark_sec: float | None, idx: int) -> None:
        if on_progress:
            on_progress(min(99.9, overall), mark_sec, idx, total)

    def seg_progress(job_idx: int, job_mark: float, clip_pct: float) -> None:
        base = (job_idx - 1) / total * segment_weight * 100.0
        overall = min(99.0, base + clip_pct / total * segment_weight)
        report(overall, job_mark, job_idx)

    for idx, job in enumerate(jobs, 1):
        if cancel_event and cancel_event.is_set():
            stopped = True
            break
        if not isinstance(job, TimelineComposeJob):
            raise TypeError("TimelineComposeJob 목록이 필요합니다.")
        clip_path = work_dir / f"seg_{idx:04d}.mp4"
        try:
            if job.is_gap or not job.video:
                compose_black_pad(
                    clip_path,
                    duration_sec=job.duration_sec,
                    width=pad_w,
                    height=pad_h,
                    cancel_event=cancel_event,
                    on_progress=lambda p, j=idx, m=job.mark_sec: seg_progress(j, m, p),
                )
            else:
                compose_timeline_clip(
                    job.video,
                    clip_path,
                    image=job.image,
                    duration_sec=job.duration_sec,
                    video_start_sec=getattr(job, "video_start_sec", 0.0),
                    image_effect=getattr(job, "image_effect", "fixed"),
                    is_hold=getattr(job, "is_hold", False),
                    normalize_size=norm_size,
                    cancel_event=cancel_event,
                    on_progress=lambda p, j=idx, m=job.mark_sec: seg_progress(j, m, p),
                )
            _ensure_clip_duration(
                clip_path,
                job.duration_sec,
                cancel_event=cancel_event,
            )
            clips.append(clip_path)
        except ComposeStopped as e:
            stopped = True
            if e.path and e.path.is_file() and e.path.stat().st_size >= 512 and not clips:
                clips.append(e.path)
            break
    if not clips:
        raise RuntimeError("합성된 구간 클립이 없습니다.")
    report(segment_weight * 100.0, None, 0)

    mp3_path = Path(audio_mp3) if audio_mp3 else None
    mux_mp3 = bool(mp3_path and mp3_path.is_file())
    video_dest = work_dir / "_concat_video.mp4" if mux_mp3 else dest
    finish_cancel = None if stopped else cancel_event

    def concat_progress(pct: float) -> None:
        overall = segment_weight * 100.0 + pct * concat_weight
        report(overall, None, 0)

    try:
        concat_videos(
            clips,
            video_dest,
            cancel_event=finish_cancel,
            on_progress=concat_progress,
            fast_copy=not stopped,
            video_only=mux_mp3,
        )
    except ComposeStopped:
        stopped = True
        if not video_dest.is_file():
            raise

    if mux_mp3:
        report((segment_weight + concat_weight) * 100.0, None, -1)

        def audio_progress(pct: float) -> None:
            overall = (segment_weight + concat_weight) * 100.0 + pct * audio_weight
            report(overall, None, -1)

        try:
            mux_mp3_to_video(
                video_dest,
                mp3_path,
                dest,
                cancel_event=finish_cancel,
                on_progress=audio_progress,
                fast_copy=stopped,
            )
        except ComposeStopped:
            stopped = True
            if not dest.is_file():
                raise
        if video_dest != dest and video_dest.is_file():
            video_dest.unlink(missing_ok=True)
    elif video_dest != dest:
        if dest.is_file():
            dest.unlink()
        video_dest.replace(dest)

    if stopped:
        if dest.is_file():
            raise ComposeStopped(dest, f"합성 중지 — {dest.name}")
        raise ComposeStopped(None, "합성이 중지되었습니다.")

    if on_progress:
        on_progress(100.0, None, total, total)
    return dest


def play_video(path: Path) -> None:
    """ffplay(우선) 또는 OS 기본 플레이어로 재생."""
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(str(path))
    ff = _ffmpeg_exe("ffplay")
    if ff:
        subprocess.Popen(
            [str(ff), "-autoexit", "-window_title", "7_3 mp4Search", str(path)],
            **_win_subprocess_flags(),
        )
        return
    if sys.platform == "win32":
        os.startfile(str(path))  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], **_win_subprocess_flags())
    else:
        subprocess.Popen(["xdg-open", str(path)], **_win_subprocess_flags())


def temp_preview_path(suffix: str = ".mp4", *, tag: str = "") -> Path:
    safe = re.sub(r"[^\w.-]+", "_", tag).strip("_")[:96]
    stem = f"wisdom_mp4search_{os.getpid()}"
    if safe:
        stem = f"{stem}_{safe}"
    return Path(tempfile.gettempdir()) / f"{stem}{suffix}"
