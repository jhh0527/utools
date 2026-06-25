"""구간 미리보기용 ffmpeg MJPEG 프레임."""

from __future__ import annotations

import io
import subprocess
import threading
from pathlib import Path

from PIL import Image

from utube_edit.media_paths import ffmpeg_executable
from utube_edit.subprocess_util import subprocess_run_no_window

_JPEG_SOI = b"\xff\xd8"
_JPEG_EOI = b"\xff\xd9"


def extract_preview_frame(video: Path, time_sec: float, *, max_width: int = 720) -> Image.Image | None:
    ff = ffmpeg_executable()
    if not ff:
        return None
    t = max(0.0, float(time_sec))
    cmd = [
        ff,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{t:.3f}",
        "-i",
        str(video),
        "-frames:v",
        "1",
        "-vf",
        f"scale='min({max_width},iw)':-2",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    r = subprocess_run_no_window(cmd, capture_output=True)
    if r.returncode != 0 or not r.stdout:
        return None
    try:
        return Image.open(io.BytesIO(r.stdout)).convert("RGB")
    except OSError:
        return None


def _read_jpegs_from_pipe(pipe: subprocess.Popen[bytes]) -> bytes:
    buf = bytearray()
    assert pipe.stdout is not None
    while True:
        chunk = pipe.stdout.read(65536)
        if not chunk:
            break
        buf.extend(chunk)
    pipe.wait()
    return bytes(buf)


def _split_jpegs(data: bytes) -> list[bytes]:
    frames: list[bytes] = []
    i = 0
    while True:
        start = data.find(_JPEG_SOI, i)
        if start < 0:
            break
        end = data.find(_JPEG_EOI, start + 2)
        if end < 0:
            break
        frames.append(data[start : end + 2])
        i = end + 2
    return frames


def iter_segment_frames(
    video: Path,
    start_sec: float,
    end_sec: float,
    *,
    fps: float = 10.0,
    max_width: int = 720,
) -> list[Image.Image]:
    ff = ffmpeg_executable()
    if not ff:
        return []
    duration = max(0.1, float(end_sec) - float(start_sec))
    cmd = [
        ff,
        "-hide_banner",
        "-loglevel",
        "error",
        "-ss",
        f"{start_sec:.3f}",
        "-i",
        str(video),
        "-t",
        f"{duration:.3f}",
        "-an",
        "-vf",
        f"fps={max(1.0, min(24.0, fps))},scale='min({max_width},iw)':-2",
        "-f",
        "image2pipe",
        "-vcodec",
        "mjpeg",
        "-",
    ]
    if hasattr(subprocess, "CREATE_NO_WINDOW"):
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=subprocess.CREATE_NO_WINDOW)
    else:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    raw = _read_jpegs_from_pipe(proc)
    out: list[Image.Image] = []
    for blob in _split_jpegs(raw):
        try:
            out.append(Image.open(io.BytesIO(blob)).convert("RGB"))
        except OSError:
            continue
    return out


class SegmentPreviewPlayer:
    """백그라운드에서 구간 프레임을 순환 재생."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2.0)
        self._thread = None
        self._stop.clear()

    def play(
        self,
        video: Path,
        start_sec: float,
        end_sec: float,
        *,
        on_frame,
        on_done,
        fps: float = 10.0,
    ) -> None:
        self.stop()
        self._stop.clear()

        def work() -> None:
            frames = iter_segment_frames(video, start_sec, end_sec, fps=fps)
            if not frames:
                on_done()
                return
            interval = max(0.04, 1.0 / fps)
            for im in frames:
                if self._stop.is_set():
                    break
                on_frame(im)
                if self._stop.wait(interval):
                    break
            on_done()

        self._thread = threading.Thread(target=work, daemon=True)
        self._thread.start()
