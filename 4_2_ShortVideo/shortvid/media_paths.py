"""wisdom 프로젝트 루트의 tools/ffmpeg/bin 을 우선 사용하는 ffmpeg/ffprobe 경로."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _ffmpeg_probe_names() -> tuple[str, str]:
    if sys.platform == "win32":
        return ("ffmpeg.exe", "ffprobe.exe")
    return ("ffmpeg", "ffprobe")


def _local_ffmpeg_bin_dir() -> Path | None:
    ff_n, fp_n = _ffmpeg_probe_names()
    bases: list[Path] = []
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        bases.extend([exe.parent, exe.parent.parent, exe.parent.parent.parent])
        try:
            from shortvid.repo_paths import wisdom_repo_root

            bases.append(wisdom_repo_root())
        except Exception:
            pass
    bases.extend(Path(__file__).resolve().parents)
    for base in bases:
        d = base / "tools" / "ffmpeg" / "bin"
        if (d / ff_n).is_file() and (d / fp_n).is_file():
            return d
    return None


def prepend_local_ffmpeg_bin_to_os_path() -> None:
    d = _local_ffmpeg_bin_dir()
    if d is None:
        return
    ins = str(d.resolve())
    sep = os.pathsep
    cur = os.environ.get("PATH") or (os.environ.get("Path", "") if sys.platform == "win32" else "")
    parts = [p.strip().strip('"') for p in cur.split(sep) if p]
    if ins.lower() not in {p.lower() for p in parts}:
        newp = ins + (sep + cur if cur else "")
        os.environ["PATH"] = newp
        if sys.platform == "win32":
            os.environ["Path"] = newp


def ffmpeg_executable() -> str | None:
    ff_n, _ = _ffmpeg_probe_names()
    d = _local_ffmpeg_bin_dir()
    if d is not None:
        return str(d / ff_n)
    return shutil.which("ffmpeg")


def ffprobe_executable() -> str | None:
    _, fp_n = _ffmpeg_probe_names()
    d = _local_ffmpeg_bin_dir()
    if d is not None:
        return str(d / fp_n)
    return shutil.which("ffprobe")
