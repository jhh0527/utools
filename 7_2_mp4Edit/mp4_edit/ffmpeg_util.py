# -*- coding: utf-8 -*-
"""ffmpeg/ffprobe — 미리보기 프레임·구간·영역 자르기."""

from __future__ import annotations

import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from mp4_edit.log_util import mp4_edit_log, mp4_edit_log_exc


_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _win_subprocess_flags() -> dict:
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


def probe_has_audio(path: Path | str) -> bool:
    """로컬 파일에 오디오 스트림이 있는지. URL 이면 True 로 가정."""
    src = str(path)
    if src.startswith(("http://", "https://")):
        return True
    fp = ffprobe_bin()
    if not fp:
        return True
    cmd = [
        str(fp),
        "-v",
        "error",
        "-select_streams",
        "a",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        src,
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
        return True
    return r.returncode == 0 and bool(r.stdout.strip())


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


def extract_frame_png_from_url(url: str, time_sec: float, dest: Path) -> Path:
    """HTTP(S) 스트림 URL 에서 단일 프레임 추출."""
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
        url,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        str(dest),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120, **_win_subprocess_flags())
    if r.returncode != 0 or not dest.is_file():
        err = (r.stderr or r.stdout or "스트림 프레임 추출 실패").strip()[:400]
        raise RuntimeError(err)
    return dest


def resolve_edit_dest(
    src: Path,
    *,
    output_dir: Path | None = None,
    output_name: str | None = None,
    default_stem: str | None = None,
) -> Path:
    """저장 디렉터리·파일명을 반영한 출력 경로."""
    src = Path(src)
    base = Path(output_dir) if output_dir else src.parent
    stem = (default_stem or src.stem).strip() or "output"
    suffix = src.suffix or ".mp4"
    name = (output_name or "").strip()
    if name:
        p = Path(name)
        if p.suffix:
            return base / name
        return base / f"{name}{suffix}"
    return base / f"{stem}_edit{suffix}"


def edit_output_path(src: Path, *, output_dir: Path | None = None) -> Path:
    src = Path(src)
    base = Path(output_dir) if output_dir else src.parent
    return base / f"{src.stem}_edit{src.suffix}"


# UI 키 → 재생 배속 (0.33 은 3초→9초가 되도록 정확히 1/3)
SPEED_CHOICES: tuple[tuple[str, float, str], ...] = (
    ("1", 1.0, "원본"),
    ("0.5", 0.5, "2배 느리게"),
    ("0.33", 1.0 / 3.0, "3배 느리게"),
    ("0.25", 0.25, "4배 느리게"),
)
SPEED_BY_KEY: dict[str, float] = {k: v for k, v, _ in SPEED_CHOICES}


def normalize_speed(speed: float | str | None) -> float:
    """재생 배속 (1=원본, 0.5=절반 속도 → 길이 2배)."""
    if speed is None:
        return 1.0
    if isinstance(speed, str):
        key = speed.strip()
        if key in SPEED_BY_KEY:
            return SPEED_BY_KEY[key]
        try:
            speed = float(key)
        except ValueError:
            return 1.0
    s = float(speed)
    if s <= 0:
        return 1.0
    return s


def speed_stem_suffix(speed: float | str | None) -> str:
    """파일명용 접미사. 원본이면 빈 문자열."""
    s = normalize_speed(speed)
    if abs(s - 1.0) < 1e-9:
        return ""
    for key, val, _ in SPEED_CHOICES:
        if abs(s - val) < 1e-9:
            return f"_{key.replace('.', 'p')}x"
    return f"_{s:g}x"


def _atempo_chain(speed: float) -> str:
    """atempo 는 0.5~2.0 만 허용 → 느리게 할 때 체인으로 분할."""
    factors: list[float] = []
    remaining = float(speed)
    while remaining < 0.5 - 1e-9:
        factors.append(0.5)
        remaining /= 0.5
    if abs(remaining - 1.0) > 1e-6:
        factors.append(remaining)
    if not factors:
        return ""
    return ",".join(f"atempo={f:.10g}" for f in factors)


def _trim_encode_cmd(
    src: Path | str,
    dest: Path,
    *,
    start_sec: float,
    clip_dur: float | None,
    crop_rect: tuple[int, int, int, int] | None,
    speed: float = 1.0,
) -> list[str]:
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("자르기에 ffmpeg 가 필요합니다 (tools/ffmpeg).")

    speed = normalize_speed(speed)
    slow = abs(speed - 1.0) > 1e-9

    vf_parts: list[str] = []
    if crop_rect is not None:
        x, y, w, h = crop_rect
        w, h = _even(w), _even(h)
        x, y = max(0, int(x)), max(0, int(y))
        if w < 2 or h < 2:
            raise ValueError("자를 영역이 너무 작습니다.")
        vf_parts.append(f"crop={w}:{h}:{x}:{y}")
    if slow:
        # 재생 배속 s → PTS 를 1/s 배로 늘려 길이를 늘림
        vf_parts.append(f"setpts={1.0 / speed:.10g}*PTS")

    cmd = [str(ff), "-y", "-ss", f"{start_sec:.3f}", "-i", str(src)]
    if clip_dur is not None:
        cmd.extend(["-t", f"{clip_dur:.3f}"])
    if not vf_parts and not slow:
        cmd.extend(["-c", "copy", "-avoid_negative_ts", "make_zero", str(dest)])
        return cmd

    if vf_parts:
        cmd.extend(["-vf", ",".join(vf_parts)])
    cmd.extend(["-c:v", "libx264", "-preset", "medium", "-crf", "18"])
    af = _atempo_chain(speed) if slow else ""
    if af and probe_has_audio(src):
        cmd.extend(["-af", af, "-c:a", "aac", "-b:a", "192k"])
    elif slow:
        cmd.append("-an")
    elif crop_rect is not None:
        # 영역만 자를 때 오디오는 재인코딩(스트림 복사와 길이 맞춤)
        cmd.extend(["-c:a", "aac", "-b:a", "192k"])
    cmd.extend(["-movflags", "+faststart", str(dest)])
    return cmd


def _clip_duration(start_sec: float, end_sec: float | None) -> float | None:
    start_sec = max(0.0, float(start_sec))
    if end_sec is None:
        return None
    end_sec = float(end_sec)
    if end_sec <= start_sec:
        raise ValueError("종료 시점은 시작 시점보다 뒤여야 합니다.")
    return end_sec - start_sec


def trim_stream_to_file(
    url: str,
    dest: Path,
    *,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
    speed: float = 1.0,
    timeout: int = 600,
) -> Path:
    """HTTP(S) 스트림 URL 에서 구간·영역을 잘라 ``dest`` 에 저장."""
    dest = Path(dest)
    clip_dur = _clip_duration(start_sec, end_sec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    speed = normalize_speed(speed)
    cmd = _trim_encode_cmd(
        url, dest, start_sec=start_sec, clip_dur=clip_dur, crop_rect=crop_rect, speed=speed
    )
    mp4_edit_log(
        f"trim_stream_to_file start dest={dest} start={start_sec} end={end_sec} "
        f"speed={speed} timeout={timeout}s cmd={' '.join(cmd[:8])}…"
    )
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            **_win_subprocess_flags(),
        )
    except subprocess.TimeoutExpired as e:
        mp4_edit_log(f"trim_stream_to_file TIMEOUT ({timeout}s) dest={dest}")
        raise RuntimeError(f"구간 저장 시간 초과 ({timeout}초).") from e
    elapsed = time.monotonic() - t0
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        err = (r.stderr or r.stdout or "구간 저장 실패").strip()[:500]
        mp4_edit_log(f"trim_stream_to_file FAIL rc={r.returncode} ({elapsed:.1f}s) err={err[:200]!r}")
        raise RuntimeError(err)
    mp4_edit_log(f"trim_stream_to_file ok dest={dest} size={dest.stat().st_size} ({elapsed:.1f}s)")
    return dest


def crop_and_trim(
    src: Path,
    dest: Path,
    *,
    start_sec: float = 0.0,
    end_sec: float | None = None,
    crop_rect: tuple[int, int, int, int] | None = None,
    speed: float = 1.0,
    timeout: int = 3600,
) -> Path:
    """타임라인 구간·사각형 영역을 잘라 dest 에 저장. speed 가 1 미만이면 길이를 늘림."""
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"영상 없음: {src}")
    clip_dur = _clip_duration(start_sec, end_sec)
    dest.parent.mkdir(parents=True, exist_ok=True)
    speed = normalize_speed(speed)
    cmd = _trim_encode_cmd(
        src, dest, start_sec=start_sec, clip_dur=clip_dur, crop_rect=crop_rect, speed=speed
    )
    mp4_edit_log(
        f"crop_and_trim start src={src} dest={dest} start={start_sec} end={end_sec} "
        f"crop={crop_rect} speed={speed} timeout={timeout}s"
    )
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            **_win_subprocess_flags(),
        )
    except subprocess.TimeoutExpired as e:
        mp4_edit_log(f"crop_and_trim TIMEOUT ({timeout}s) dest={dest}")
        raise RuntimeError(f"자르기 시간 초과 ({timeout}초).") from e
    elapsed = time.monotonic() - t0
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        err = (r.stderr or r.stdout or "자르기 실패").strip()[:500]
        mp4_edit_log(f"crop_and_trim FAIL rc={r.returncode} ({elapsed:.1f}s) err={err[:200]!r}")
        raise RuntimeError(err)
    mp4_edit_log(f"crop_and_trim ok dest={dest} size={dest.stat().st_size} ({elapsed:.1f}s)")
    return dest


def _concat_list_path_escape(path: Path) -> str:
    """concat demuxer 용 경로 (슬래시, 작은따옴표 이스케이프)."""
    s = str(path.resolve()).replace("\\", "/")
    return s.replace("'", r"'\''")


def _concat_mp4_files(files: list[Path], dest: Path, *, timeout: int = 3600) -> Path:
    """동일 코덱 클립들을 concat. copy 실패 시 재인코딩."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("이어붙이기에 ffmpeg 가 필요합니다 (tools/ffmpeg).")
    if not files:
        raise ValueError("이어붙일 파일이 없습니다.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    list_path = dest.with_suffix(dest.suffix + ".concat.txt")
    list_path.write_text(
        "".join(f"file '{_concat_list_path_escape(p)}'\n" for p in files),
        encoding="utf-8",
    )
    base = [
        str(ff),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
    ]
    cmd_copy = base + ["-c", "copy", "-movflags", "+faststart", str(dest)]
    mp4_edit_log(f"concat start n={len(files)} dest={dest}")
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            cmd_copy,
            capture_output=True,
            text=True,
            timeout=timeout,
            **_win_subprocess_flags(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"이어붙이기 시간 초과 ({timeout}초).") from e
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        cmd_enc = base + [
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-c:a",
            "aac",
            "-b:a",
            "160k",
            "-movflags",
            "+faststart",
            str(dest),
        ]
        try:
            r2 = subprocess.run(
                cmd_enc,
                capture_output=True,
                text=True,
                timeout=timeout,
                **_win_subprocess_flags(),
            )
        except subprocess.TimeoutExpired as e:
            raise RuntimeError(f"이어붙이기 시간 초과 ({timeout}초).") from e
        if r2.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
            err = (r2.stderr or r.stderr or r2.stdout or "이어붙이기 실패").strip()[:500]
            mp4_edit_log(f"concat FAIL err={err[:200]!r}")
            raise RuntimeError(err)
    try:
        list_path.unlink(missing_ok=True)
    except OSError:
        pass
    mp4_edit_log(f"concat ok dest={dest} size={dest.stat().st_size} ({time.monotonic() - t0:.1f}s)")
    return dest


def resolve_loop_plan(
    *,
    loop_start: float,
    loop_end: float,
    total_dur: float,
    repeat_count: int | None = None,
    target_loop_sec: float | None = None,
) -> tuple[int, float, float]:
    """(반복횟수, 반복구간 출력길이, 전체 예상길이) 계산."""
    loop_start = max(0.0, float(loop_start))
    loop_end = float(loop_end)
    total_dur = max(0.0, float(total_dur))
    if total_dur > 0:
        loop_end = min(loop_end, total_dur)
    if loop_end <= loop_start:
        raise ValueError("반복 구간의 종료는 시작보다 뒤여야 합니다.")
    seg = loop_end - loop_start
    if target_loop_sec is not None and float(target_loop_sec) > 0:
        target = float(target_loop_sec)
        n = max(1, int(math.ceil(target / seg - 1e-9)))
        loop_out = target
    else:
        n = max(1, int(repeat_count or 2))
        loop_out = n * seg
    before = loop_start
    after = max(0.0, total_dur - loop_end) if total_dur > 0 else 0.0
    return n, loop_out, before + loop_out + after


def _run_ffmpeg(cmd: list[str], *, timeout: int, label: str) -> None:
    t0 = time.monotonic()
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            **_win_subprocess_flags(),
        )
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"{label} 시간 초과 ({timeout}초).") from e
    dest = Path(cmd[-1])
    if r.returncode != 0 or not dest.is_file() or dest.stat().st_size < 512:
        err = (r.stderr or r.stdout or f"{label} 실패").strip()[:600]
        mp4_edit_log(f"{label} FAIL rc={r.returncode} err={err[:250]!r}")
        raise RuntimeError(err)
    mp4_edit_log(f"{label} ok dest={dest} ({time.monotonic() - t0:.1f}s)")


def _cut_clip_fast(
    src: Path,
    dest: Path,
    *,
    start: float,
    end: float | None,
    timeout: int,
) -> Path:
    """짧은 구간만 ultrafast 재인코딩. 입력 seek + trim 으로 빠르게·정확히."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg 가 필요합니다.")
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    start = max(0.0, float(start))
    has_a = probe_has_audio(src)
    # 키프레임 근처로 빠르게 점프한 뒤, trim 으로 정확한 시작·길이
    pad = min(3.0, start)
    seek = start - pad
    off = pad
    vf = f"trim=start={off:.6f},setpts=PTS-STARTPTS"
    af = f"atrim=start={off:.6f},asetpts=PTS-STARTPTS"
    if end is not None:
        dur = float(end) - start
        if dur <= 0:
            raise ValueError("종료는 시작보다 뒤여야 합니다.")
        vf = f"trim=start={off:.6f}:duration={dur:.6f},setpts=PTS-STARTPTS"
        af = f"atrim=start={off:.6f}:duration={dur:.6f},asetpts=PTS-STARTPTS"
    cmd = [
        str(ff),
        "-y",
        "-ss",
        f"{seek:.6f}",
        "-i",
        str(src),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-crf",
        "20",
        "-pix_fmt",
        "yuv420p",
    ]
    if has_a:
        cmd.extend(["-af", af, "-c:a", "aac", "-b:a", "160k"])
    else:
        cmd.append("-an")
    cmd.extend(["-movflags", "+faststart", str(dest)])
    _run_ffmpeg(cmd, timeout=timeout, label="cut_clip_fast")
    return dest


def _xfade_n_copies(
    mid: Path,
    n: int,
    dest: Path,
    *,
    seg_dur: float,
    fade: float,
    timeout: int,
) -> Path:
    """동일 클립 n개를 크로스페이드로 이어붙임."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("ffmpeg 가 필요합니다.")
    n = max(1, int(n))
    dest = Path(dest)
    if n == 1 or fade <= 1e-3:
        if n == 1:
            shutil.copy2(mid, dest)
            return dest
        return _concat_mp4_files([mid] * n, dest, timeout=timeout)
    fade = min(float(fade), max(0.05, seg_dur * 0.4))
    has_a = probe_has_audio(mid)
    cmd: list[str] = [str(ff), "-y"]
    for _ in range(n):
        cmd.extend(["-i", str(mid)])
    fc: list[str] = []
    # video chain
    for i in range(1, n):
        inp_a = "[0:v]" if i == 1 else f"[vx{i - 1}]"
        inp_b = f"[{i}:v]"
        out = "[vout]" if i == n - 1 else f"[vx{i}]"
        off = i * (seg_dur - fade)
        fc.append(
            f"{inp_a}{inp_b}xfade=transition=fade:duration={fade:.4f}:offset={off:.4f}{out}"
        )
    maps = ["-map", "[vout]"]
    if has_a:
        for i in range(1, n):
            inp_a = "[0:a]" if i == 1 else f"[ax{i - 1}]"
            inp_b = f"[{i}:a]"
            out = "[aout]" if i == n - 1 else f"[ax{i}]"
            fc.append(f"{inp_a}{inp_b}acrossfade=d={fade:.4f}{out}")
        maps.extend(["-map", "[aout]"])
        audio_args = ["-c:a", "aac", "-b:a", "160k"]
    else:
        audio_args = ["-an"]
    cmd.extend(
        [
            "-filter_complex",
            ";".join(fc),
            *maps,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "20",
            "-pix_fmt",
            "yuv420p",
            *audio_args,
            "-movflags",
            "+faststart",
            str(dest),
        ]
    )
    _run_ffmpeg(cmd, timeout=timeout, label="xfade_loop")
    return dest


def loop_segment_in_video(
    src: Path,
    dest: Path,
    *,
    loop_start: float,
    loop_end: float,
    repeat_count: int | None = None,
    target_loop_sec: float | None = None,
    crossfade_sec: float = 0.0,
    timeout: int = 3600,
) -> Path:
    """선택 구간만 잘라 반복(짧게 인코딩)하고 앞·뒤와 이어붙임.

    ``crossfade_sec`` > 0 이면 반복 이음새에 짧은 크로스페이드를 넣는다.
    """
    src = Path(src)
    dest = Path(dest)
    if not src.is_file():
        raise FileNotFoundError(f"영상 없음: {src}")
    total = probe_duration(src) or 0.0
    n, loop_out, _est = resolve_loop_plan(
        loop_start=loop_start,
        loop_end=loop_end,
        total_dur=total,
        repeat_count=repeat_count,
        target_loop_sec=target_loop_sec,
    )
    loop_start = max(0.0, float(loop_start))
    loop_end = float(loop_end)
    if total > 0:
        loop_end = min(loop_end, total)
    seg = loop_end - loop_start
    if seg <= 0:
        raise ValueError("반복 구간의 종료는 시작보다 뒤여야 합니다.")
    fade = max(0.0, float(crossfade_sec or 0.0))
    if fade > 0:
        fade = min(fade, seg * 0.4)
    dest.parent.mkdir(parents=True, exist_ok=True)
    mp4_edit_log(
        f"loop_segment fast src={src} dest={dest} loop={loop_start:.3f}-{loop_end:.3f} "
        f"n={n} loop_out={loop_out:.3f} fade={fade:.3f} total={total:.3f}"
    )
    t0 = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="mp4_edit_loop_") as td_raw:
        td = Path(td_raw)
        pieces: list[Path] = []
        if loop_start > 1e-3:
            before = td / "before.mp4"
            _cut_clip_fast(src, before, start=0.0, end=loop_start, timeout=timeout)
            pieces.append(before)
        mid = td / "mid.mp4"
        _cut_clip_fast(src, mid, start=loop_start, end=loop_end, timeout=timeout)
        # 페이드 시 출력 길이 ≈ n*seg - (n-1)*fade
        faded_len = n * seg - max(0, n - 1) * fade if fade > 0 and n > 1 else n * seg
        need_trim_loop = abs(faded_len - loop_out) > 0.08
        if fade > 0 and n > 1:
            loop_body = td / "loop_fade.mp4"
            _xfade_n_copies(mid, n, loop_body, seg_dur=seg, fade=fade, timeout=timeout)
            if need_trim_loop and loop_out < faded_len - 0.05:
                loop_clip = td / "loop.mp4"
                _cut_clip_fast(loop_body, loop_clip, start=0.0, end=loop_out, timeout=timeout)
                pieces.append(loop_clip)
            else:
                pieces.append(loop_body)
        else:
            if need_trim_loop:
                loop_raw = td / "loop_raw.mp4"
                _concat_mp4_files([mid] * n, loop_raw, timeout=timeout)
                loop_clip = td / "loop.mp4"
                _cut_clip_fast(loop_raw, loop_clip, start=0.0, end=loop_out, timeout=timeout)
                pieces.append(loop_clip)
            else:
                pieces.extend([mid] * n)
        if total > 0 and loop_end < total - 1e-3:
            after = td / "after.mp4"
            _cut_clip_fast(src, after, start=loop_end, end=None, timeout=timeout)
            pieces.append(after)
        if len(pieces) == 1:
            shutil.copy2(pieces[0], dest)
        else:
            _concat_mp4_files(pieces, dest, timeout=timeout)
    if not dest.is_file() or dest.stat().st_size < 512:
        raise RuntimeError("구간 반복 저장에 실패했습니다.")
    mp4_edit_log(
        f"loop_segment ok dest={dest} size={dest.stat().st_size} ({time.monotonic() - t0:.1f}s)"
    )
    return dest


def temp_preview_png() -> Path:
    return Path(tempfile.gettempdir()) / f"mp4_edit_preview_{os.getpid()}.png"


def temp_timeline_dir() -> Path:
    d = Path(tempfile.gettempdir()) / f"mp4_edit_tl_{os.getpid()}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def extract_timeline_frame(
    *,
    path: Path | None,
    stream_url: str | None,
    time_sec: float,
    dest: Path,
) -> Path:
    """타임라인 썸네일용 단일 프레임 추출 (로컬 파일 또는 HTTP 스트림)."""
    if path is not None and path.is_file():
        return extract_frame_png(path, time_sec, dest)
    if stream_url:
        return extract_frame_png_from_url(stream_url, time_sec, dest)
    raise RuntimeError("썸네일 추출에 영상 소스가 없습니다.")
