# -*- coding: utf-8 -*-
"""폴더 MP4 → all.mp4 (고속 concat copy)."""

from __future__ import annotations

import shutil
import threading
from pathlib import Path
from typing import Callable

from mp4_merge.ffmpeg_util import (
    concat_copy,
    ffmpeg_bin,
    probe_audio,
    probe_duration,
    probe_video,
    remux_audio_match,
    silent_audio_pad,
)
from mp4_merge.log_util import MergeSessionLog
from mp4_merge.paths import ALL_MP4_NAME, MERGE_LOG_NAME, WORK_DIR_NAME

ProgressFn = Callable[[float, str], None]


def _pick_audio_target(clips: list[Path]) -> tuple[int, int]:
    """다수 클립의 음성 규격(샘플레이트·채널) — 없으면 48k 스테레오."""
    counts: dict[tuple[int, int], int] = {}
    for c in clips:
        a = probe_audio(c)
        if a is None:
            continue
        key = (a[0], a[1])
        counts[key] = counts.get(key, 0) + 1
    if not counts:
        return (48000, 2)
    return max(counts.items(), key=lambda kv: kv[1])[0]


def _clip_spec_line(path: Path) -> str:
    v = probe_video(path)
    a = probe_audio(path)
    dur = probe_duration(path)
    parts = [path.name]
    if dur:
        parts.append(f"{dur:.1f}s")
    if v:
        parts.append(f"{v[0]}x{v[1]} @{v[2]} {v[3]}")
    else:
        parts.append("video=?")
    if a:
        ch = "stereo" if a[1] >= 2 else "mono"
        parts.append(f"audio={a[0]}Hz {ch} {a[2]}")
    else:
        parts.append("audio=none")
    try:
        parts.append(f"{path.stat().st_size // (1024 * 1024)}MB")
    except OSError:
        pass
    return " | ".join(parts)


def merge_folder_to_all(
    clips: list[Path],
    folder: Path,
    *,
    mute_names: set[str] | None = None,
    cancel_event: threading.Event | None = None,
    on_progress: ProgressFn | None = None,
    on_log: Callable[[str], None] | None = None,
) -> Path:
    """클립을 순서대로 이어 붙여 ``folder/all.mp4``.

    - 영상은 절대 재인코딩하지 않음 (concat ``-c copy``).
    - 음소거 클립만 무음 AAC 패드를 입힘 (영상 copy).
    - 음성 규격이 다르면 해당 클립만 음성 remux (영상 copy).
    """
    folder = Path(folder)
    clips = [Path(p) for p in clips if Path(p).is_file()]
    if not clips:
        raise ValueError("병합할 MP4가 없습니다.")
    if not ffmpeg_bin():
        raise RuntimeError("ffmpeg 가 필요합니다 (tools/ffmpeg).")

    dest = folder / ALL_MP4_NAME
    work = folder / WORK_DIR_NAME
    work.mkdir(parents=True, exist_ok=True)
    session = MergeSessionLog(folder / MERGE_LOG_NAME, on_line=on_log)
    mute_set = {n.strip().lower() for n in (mute_names or set()) if n and str(n).strip()}

    def progress(pct: float, label: str) -> None:
        if on_progress:
            on_progress(min(100.0, max(0.0, pct)), label)

    session.line("=" * 60)
    session.line(f"7_4_mp4Merge 시작 → {dest}")
    session.line(f"클립 {len(clips)}개 · 음소거 {len(mute_set)}개")
    session.line(f"세션 로그: {folder / MERGE_LOG_NAME}")

    # 규격 기록
    videos: list[tuple[int, int, str, str]] = []
    for i, c in enumerate(clips, 1):
        line = _clip_spec_line(c)
        tag = " (음소거)" if c.name.lower() in mute_set else ""
        session.line(f"  #{i:02d}{tag} {line}")
        v = probe_video(c)
        if v:
            videos.append(v)

    if videos:
        base = videos[0]
        mismatched = [
            clips[i].name
            for i, v in enumerate(videos)
            if (v[0], v[1], v[2]) != (base[0], base[1], base[2])
        ]
        if mismatched:
            session.line(
                "⚠ 해상도·fps가 다른 클립이 있습니다. "
                "재인코딩 없이 copy로 시도합니다. 실패 시 동일 규격으로 맞춘 뒤 다시 병합하세요."
            )
            for name in mismatched[:20]:
                session.line(f"    · {name}")

    rate, ch = _pick_audio_target(clips)
    session.line(f"음성 목표: {rate}Hz / {'stereo' if ch >= 2 else 'mono'}")

    prepared: list[Path] = []
    n = len(clips)
    for i, c in enumerate(clips, 1):
        if cancel_event and cancel_event.is_set():
            raise RuntimeError("병합이 중지되었습니다.")
        muted = c.name.lower() in mute_set
        progress(5.0 + 25.0 * (i - 1) / max(1, n), f"준비 {i}/{n}")
        if muted:
            out = work / f"_mute_{i:04d}.mp4"
            session.line(f"음소거 패드: {c.name} → {out.name}")
            silent_audio_pad(c, out, sample_rate=rate, channels=ch)
            prepared.append(out)
            continue
        a = probe_audio(c)
        need_audio = a is None or a[0] != rate or a[1] != ch
        if need_audio:
            out = work / f"_audio_{i:04d}.mp4"
            why = "무음→패드" if a is None else f"{a[0]}Hz/{a[1]}ch → {rate}Hz/{ch}ch"
            session.line(f"음성만 remux: {c.name} ({why})")
            remux_audio_match(c, out, sample_rate=rate, channels=ch)
            prepared.append(out)
        else:
            prepared.append(c)

    progress(35.0, "concat copy…")
    session.line("concat -c copy 시작")

    def concat_prog(pct: float) -> None:
        progress(35.0 + pct * 0.6, f"병합 {pct:.0f}%")

    try:
        concat_copy(
            prepared,
            dest,
            cancel_event=cancel_event,
            on_progress=concat_prog,
            on_log=session.line,
        )
    except Exception as e:
        session.line(f"[실패] {e}")
        session.line(f"로그 확인: {folder / MERGE_LOG_NAME}")
        raise

    # 작업 폴더 정리 (성공 시)
    try:
        if work.is_dir():
            shutil.rmtree(work, ignore_errors=True)
    except OSError:
        pass

    dur = probe_duration(dest)
    session.line(f"[완료] {dest} · {dur:.1f}s" if dur else f"[완료] {dest}")
    progress(100.0, "완료")
    return dest
