"""저장소(wisdom) 루트 기준 경로 — 열린 워크스페이스 폴더를 기준으로 합니다."""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path


def _ensure_wisdom_on_path(from_file: str | Path) -> None:
    for base in [Path.cwd(), *Path(from_file).resolve().parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            return
    raise ImportError("wisdom_root.py not found — wisdom 폴더를 워크스페이스 루트로 여세요.")


_ensure_wisdom_on_path(__file__)
from wisdom_root import module_output, resolve_wisdom_root
from wisdom_workspace import resolve_module_output


def wisdom_repo_root() -> Path:
    return resolve_wisdom_root()


def default_scenevid_output_dir() -> Path:
    """videoPG: 자막·음성·이미지 합성 산출물 기본 폴더."""
    return resolve_module_output("4_1_video")


def default_tts_voice_output_dir() -> Path:
    """TTS 산출물 (``mp3`` 폴더)."""
    try:
        from wisdom_content_paths import default_mp3_dir

        mp3 = default_mp3_dir()
        if mp3 is not None:
            return mp3
    except ImportError:
        pass
    return resolve_module_output("2_1_ttsToVoice")


def default_srt_image_output_dir() -> Path:
    """이미지·영상 (``jpg`` 폴더)."""
    try:
        from wisdom_content_paths import default_jpg_dir

        jpg = default_jpg_dir()
        if jpg is not None:
            return jpg
    except ImportError:
        pass
    return resolve_module_output("2_2_srtToImage")


def default_scenevid_compose_mp4_name() -> str:
    """videoPG: 합성 MP4 기본 파일명 ``yyyymmdd.mp4``."""
    return f"{date.today():%Y%m%d}.mp4"


def default_scenevid_compose_mp4() -> Path:
    try:
        from wisdom_content_paths import content_root

        root = content_root()
        if root is not None:
            return root / default_scenevid_compose_mp4_name()
    except ImportError:
        pass
    return default_scenevid_output_dir() / default_scenevid_compose_mp4_name()


def pick_default_compose_audio_srt(tts_output: Path | None = None) -> tuple[Path | None, Path | None]:
    """videoPG 기본: ``all.mp3`` / ``all.srt`` 우선, 없으면 ``part01.*``."""
    root = (tts_output or default_tts_voice_output_dir()).resolve()
    all_mp3 = root / "all.mp3"
    all_srt = root / "all.srt"
    if all_mp3.is_file() and all_srt.is_file():
        return all_mp3, all_srt
    p1 = root / "part01.mp3"
    s1 = root / "part01.srt"
    if p1.is_file() and s1.is_file():
        return p1, s1
    mp3s = sorted(root.glob("*.mp3"))
    srts = sorted(root.glob("*.srt"))
    if mp3s and srts:
        return mp3s[0], srts[0]
    return (mp3s[0] if mp3s else None, srts[0] if srts else None)
