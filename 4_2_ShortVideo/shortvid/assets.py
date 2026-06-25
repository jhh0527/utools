"""프로젝트 폴더에 에셋 폴더 만들기, 플레이스홀더 이미지, ffprobe 로 길이."""

from __future__ import annotations

from pathlib import Path

from shortvid.media_paths import ffmpeg_executable, ffprobe_executable
from shortvid.subprocess_util import subprocess_run_no_window


def ensure_layout(root: Path) -> None:
    for sub in ("audio", "images", "subtitles", "output"):
        (root / sub).mkdir(parents=True, exist_ok=True)


def audio_duration_ffprobe(audio_path: Path) -> float:
    fp_bin = ffprobe_executable()
    if fp_bin is None:
        raise RuntimeError(
            "ffprobe 를 찾을 수 없습니다. wisdom/tools/ffmpeg/bin 또는 FFmpeg PATH를 확인하세요."
        )
    cmd = [
        fp_bin,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(audio_path),
    ]
    r = subprocess_run_no_window(cmd, capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        raise RuntimeError(f"ffprobe 실패: {r.stderr}")
    try:
        return float((r.stdout or "0").strip())
    except ValueError as e:
        raise RuntimeError(f"ffprobe 결과 파싱 실패: {r.stdout!r}") from e


def make_placeholder_png(
    path: Path,
    width: int,
    height: int,
    *,
    title: str = "",
) -> None:
    """Pillow 있으면 그라데이션 느낌 플레이스홀더, 없으면 극히 작은 BMP 대신 간단히 실패 안내."""
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:
        raise RuntimeError(
            "PNG 플레이스홀더에 Pillow 필요: pip install Pillow\n"
            "또는 images/sceneN.png 를 직접 넣으세요."
        ) from None
    img = Image.new("RGB", (width, height), color=(24, 28, 40))
    dr = ImageDraw.Draw(img)
    for y in range(height):
        k = int(40 + (y / height) * 30)
        dr.line([(0, y), (width, y)], fill=(24 + k // 4, 28 + k // 6, 50 + k // 5))
    caption = title[:120] if title else path.stem
    try:
        font = ImageFont.truetype("malgun.ttf", 36)
    except OSError:
        font = ImageFont.load_default()
    tw, th = dr.textbbox((0, 0), caption, font=font)[2:4]
    dr.text(((width - tw) // 2, (height - th) // 2), caption, fill=(220, 220, 230), font=font)
    img.save(path, "PNG")


def make_silent_mp3(path: Path, duration_sec: float) -> None:
    """테스트용 무비트 MP3 (FFmpeg만 사용)."""
    ff_bin = ffmpeg_executable()
    if ff_bin is None:
        raise RuntimeError("ffmpeg 가 필요합니다. wisdom/tools/ffmpeg/bin 또는 PATH를 확인하세요.")
    path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(0.5, duration_sec)
    cmd = [
        ff_bin,
        "-y",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-t",
        str(dur),
        "-c:a",
        "libmp3lame",
        "-q:a",
        "6",
        str(path.resolve()),
    ]
    subprocess_run_no_window(cmd, capture_output=True, text=True, check=True, timeout=60)


