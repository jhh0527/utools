# -*- coding: utf-8 -*-
"""로컬 오디오/영상 파일 재생 시간(ffprobe) 조회."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def ffprobe_duration_sec(media_path: Path) -> float:
    exe = shutil.which("ffprobe")
    if exe is None:
        raise RuntimeError(
            "ffprobe 를 찾을 수 없습니다. FFmpeg 설치 후 PATH에 넣거나 "
            "wisdom/tools/ffmpeg/bin 에 ffprobe.exe 를 두세요."
        )
    cmd = [
        exe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(media_path),
    ]
    kw: dict = dict(capture_output=True, text=True, timeout=300)
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    r = subprocess.run(cmd, **kw)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {r.stderr or r.stdout}")
    try:
        return float((r.stdout or "0").strip())
    except ValueError as e:
        raise RuntimeError(f"ffprobe 결과 파싱 실패: {r.stdout!r}") from e
