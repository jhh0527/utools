# -*- coding: utf-8 -*-
"""Whisper(faster-whisper) MP3 → 텍스트."""

from __future__ import annotations

from pathlib import Path

WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")


def transcribe_mp3(mp3_path: Path, *, model_name: str = "base") -> str:
    """MP3 파일을 Whisper로 전사합니다."""
    mp3_path = Path(mp3_path)
    if not mp3_path.is_file():
        raise FileNotFoundError(str(mp3_path))
    model_name = (model_name or "base").strip()
    if model_name not in WHISPER_MODELS:
        raise ValueError(f"지원 모델: {', '.join(WHISPER_MODELS)}")

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper 가 설치되어 있지 않습니다.\n"
            "pip install faster-whisper 후 다시 시도하세요."
        ) from e

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(mp3_path),
        language="ko",
        vad_filter=True,
    )
    parts: list[str] = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            parts.append(t)
    if not parts:
        return ""
    return " ".join(parts)
