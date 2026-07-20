# -*- coding: utf-8 -*-
"""자동 루프점(프레임 유사도) 탐색 — SSIM 근사 + 일괄 처리용."""

from __future__ import annotations

import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from PIL import Image

from mp4_edit.ffmpeg_util import extract_frame_png, ffmpeg_bin, probe_duration
from mp4_edit.log_util import mp4_edit_log

# 이 점수 미만이면 「실패 → 수동」으로 안내
DEFAULT_MIN_SCORE = 0.70
_GRAY_SIZE = (96, 96)
_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _win_flags() -> dict:
    if sys.platform == "win32" and _WIN_NO_WINDOW:
        return {"creationflags": _WIN_NO_WINDOW}
    return {}


@dataclass(frozen=True)
class LoopFindResult:
    loop_start: float
    loop_end: float
    score: float
    ok: bool
    message: str


def _to_gray_small(im: Image.Image) -> Image.Image:
    return im.convert("L").resize(_GRAY_SIZE, Image.Resampling.BILINEAR)


def frame_similarity(a: Image.Image, b: Image.Image) -> float:
    """0~1 유사도. 간단 SSIM(휘도) + MSE 보조."""
    ga = _to_gray_small(a)
    gb = _to_gray_small(b)
    pa = list(ga.getdata())
    pb = list(gb.getdata())
    n = len(pa)
    if n == 0:
        return 0.0
    ma = sum(pa) / n
    mb = sum(pb) / n
    c1 = (0.01 * 255) ** 2
    l_term = (2 * ma * mb + c1) / (ma * ma + mb * mb + c1)
    var_a = sum((x - ma) ** 2 for x in pa) / n
    var_b = sum((x - mb) ** 2 for x in pb) / n
    cov = sum((pa[i] - ma) * (pb[i] - mb) for i in range(n)) / n
    c2 = (0.03 * 255) ** 2
    s_term = (2 * cov + c2) / (var_a + var_b + c2)
    ssim = max(0.0, min(1.0, l_term * s_term))
    mse = sum((pa[i] - pb[i]) ** 2 for i in range(n)) / n
    mse_sim = max(0.0, 1.0 - mse / (255.0 * 255.0))
    return 0.65 * ssim + 0.35 * mse_sim


def _load_frame(src: Path, time_sec: float, dest: Path) -> Image.Image:
    extract_frame_png(src, time_sec, dest)
    with Image.open(dest) as im:
        return im.convert("RGB").copy()


def _sample_frames_dir(
    src: Path,
    *,
    start: float,
    duration: float,
    fps: float,
    out_dir: Path,
) -> list[tuple[float, Path]]:
    """start 부터 duration 동안 fps 샘플 PNG 생성."""
    ff = ffmpeg_bin()
    if not ff:
        raise RuntimeError("프레임 샘플에 ffmpeg 가 필요합니다.")
    out_dir.mkdir(parents=True, exist_ok=True)
    pattern = out_dir / "f%04d.png"
    cmd = [
        str(ff),
        "-y",
        "-ss",
        f"{max(0.0, start):.6f}",
        "-i",
        str(src),
        "-t",
        f"{max(0.05, duration):.6f}",
        "-vf",
        f"fps={fps:.4g}",
        "-q:v",
        "3",
        str(pattern),
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=600, **_win_flags())
    files = sorted(out_dir.glob("f*.png"))
    if r.returncode != 0 or not files:
        err = (r.stderr or r.stdout or "샘플 실패").strip()[:400]
        raise RuntimeError(err)
    return [(start + i / max(fps, 0.01), p) for i, p in enumerate(files)]


def find_loop_points(
    src: Path,
    *,
    loop_start: float = 0.0,
    min_duration: float = 0.4,
    max_duration: float | None = None,
    sample_fps: float = 10.0,
    min_score: float = DEFAULT_MIN_SCORE,
    on_progress: Callable[[str], None] | None = None,
) -> LoopFindResult:
    """시작 프레임과 가장 비슷한 종료 시각을 찾는다.

    ``ok=False`` 이면 점수가 낮아 수동 시작·종료를 권장.
    """
    src = Path(src)
    if not src.is_file():
        raise FileNotFoundError(f"영상 없음: {src}")
    total = probe_duration(src) or 0.0
    if total <= 0:
        raise RuntimeError("영상 길이를 읽을 수 없습니다.")
    loop_start = max(0.0, min(float(loop_start), max(0.0, total - 0.05)))
    remain = total - loop_start
    min_duration = max(0.2, float(min_duration))
    if remain < min_duration + 0.05:
        return LoopFindResult(
            loop_start,
            total,
            0.0,
            False,
            "영상이 너무 짧아 자동 루프점을 찾을 수 없습니다. 시작·종료를 수동으로 지정하세요.",
        )
    max_d = float(max_duration) if max_duration and max_duration > 0 else remain
    max_d = min(max_d, remain)
    if max_d < min_duration:
        max_d = remain

    def prog(msg: str) -> None:
        mp4_edit_log(f"find_loop: {msg}")
        if on_progress:
            on_progress(msg)

    prog("기준 프레임 추출 중…")
    with tempfile.TemporaryDirectory(prefix="mp4_edit_loopfind_") as td_raw:
        td = Path(td_raw)
        ref = _load_frame(src, loop_start, td / "ref.png")
        search_start = loop_start + min_duration
        search_dur = max_d - min_duration
        prog(f"유사도 검색 중… ({search_dur:.1f}초)")
        samples = _sample_frames_dir(
            src,
            start=search_start,
            duration=search_dur,
            fps=sample_fps,
            out_dir=td / "samp",
        )
        if not samples:
            return LoopFindResult(
                loop_start,
                min(total, loop_start + min_duration),
                0.0,
                False,
                "샘플 프레임이 없습니다. 시작·종료를 수동으로 지정하세요.",
            )
        best_t = samples[0][0]
        best_s = -1.0
        for t, png in samples:
            with Image.open(png) as im:
                score = frame_similarity(ref, im.convert("RGB"))
            if score > best_s:
                best_s = score
                best_t = t
        ok = best_s >= float(min_score)
        if ok:
            msg = (
                f"자동 루프점 찾음: {_fmt(loop_start)} ~ {_fmt(best_t)} "
                f"(유사도 {best_s:.0%})"
            )
        else:
            msg = (
                f"유사도가 낮습니다({best_s:.0%} < {min_score:.0%}). "
                f"후보 {_fmt(loop_start)}~{_fmt(best_t)} — 수동으로 시작·종료를 조정하세요."
            )
        prog(msg)
        return LoopFindResult(loop_start, best_t, best_s, ok, msg)


def _fmt(sec: float) -> str:
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m}:{s:05.2f}"


def list_mp4_files(folder: Path) -> list[Path]:
    folder = Path(folder)
    if not folder.is_dir():
        return []
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() == ".mp4"]
    return sorted(files, key=lambda p: p.name.lower())
