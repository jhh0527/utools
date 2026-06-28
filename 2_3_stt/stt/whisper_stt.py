# -*- coding: utf-8 -*-
"""Whisper(faster-whisper) MP3 → 텍스트."""

from __future__ import annotations

from pathlib import Path

WHISPER_MODELS = ("tiny", "base", "small", "medium", "large-v3")
WHISPER_LANGUAGES = ("auto", "ko", "ja")


def transcribe_mp3(
    mp3_path: Path,
    *,
    model_name: str = "base",
    language: str = "auto",
) -> str:
    """MP3 파일을 Whisper로 전사합니다."""
    mp3_path = Path(mp3_path)
    if not mp3_path.is_file():
        raise FileNotFoundError(str(mp3_path))
    model_name = (model_name or "base").strip()
    if model_name not in WHISPER_MODELS:
        raise ValueError(f"지원 모델: {', '.join(WHISPER_MODELS)}")
    language = (language or "auto").strip().lower()
    if language not in WHISPER_LANGUAGES:
        raise ValueError(f"지원 언어: {', '.join(WHISPER_LANGUAGES)}")

    try:
        from faster_whisper import WhisperModel
    except ImportError as e:
        raise RuntimeError(
            "faster-whisper 가 설치되어 있지 않습니다.\n"
            "pip install faster-whisper 후 다시 시도하세요."
        ) from e

    model = WhisperModel(model_name, device="cpu", compute_type="int8")
    transcribe_kwargs: dict = {"vad_filter": True}
    if language != "auto":
        transcribe_kwargs["language"] = language

    try:
        segments, _info = model.transcribe(str(mp3_path), **transcribe_kwargs)
    except (FileNotFoundError, OSError, RuntimeError) as e:
        msg = str(e).lower()
        if transcribe_kwargs.get("vad_filter") and (
            "silero" in msg or "vad" in msg or "onnx" in msg or ".onnx" in msg
        ):
            transcribe_kwargs["vad_filter"] = False
            segments, _info = model.transcribe(str(mp3_path), **transcribe_kwargs)
        else:
            raise

    parts: list[str] = []
    for seg in segments:
        t = (seg.text or "").strip()
        if t:
            parts.append(t)
    if not parts:
        return ""
    return " ".join(parts)
