# -*- coding: utf-8 -*-
"""mob speaker — voice pool TTS + quiet crowd bed mix (1차)."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from script_voice.elevenlabs_client import (
    mix_speech_over_bed,
    synthesize_sound_effect_mp3,
)

MOB_SPEAKER = "mob"

# voices.json 키 후보 (우선순위)
_MOB_KEY_CANDIDATES = (
    "mob_1",
    "mob_2",
    "mob_3",
    "mob_4",
    "MOB_MALE_01",
    "MOB_MALE_02",
    "MOB_MALE_03",
    "MOB_MALE_04",
    "mob",
)

# 기본 볼륨 (dB)
MOB_SPEECH_DB = -4.0
CROWD_BED_DB = -20.0

CROWD_PROMPT = (
    "Quiet distant crowd murmur in an ancient martial arts examination yard, "
    "soft ambient chatter and shuffling, no clearly understandable speech, "
    "no shouting, subtle and continuous background atmosphere"
)

_QUOTE_CHARS = "\"'“”‘’「」『』"


def is_mob_speaker(speaker: str) -> bool:
    return (speaker or "").strip().casefold() == MOB_SPEAKER


def strip_dialogue_quotes(text: str) -> str:
    """TTS용 — 바깥 따옴표 제거 (내용은 유지)."""
    s = (text or "").strip()
    if len(s) >= 2 and s[0] in _QUOTE_CHARS and s[-1] in _QUOTE_CHARS:
        s = s[1:-1].strip()
    # 오디오 태그 뒤 따옴표: [calm] "말" → [calm] 말
    s = re.sub(
        r'(\[[^\]]+\])\s*["“‘「『](.+?)["”’」』]\s*$',
        r"\1 \2",
        s,
        flags=re.DOTALL,
    )
    return s.strip() or (text or "").strip()


def _voices_raw_dict(path: Path | None) -> dict[str, Any]:
    if path is None or not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    inner = data.get("voices") if isinstance(data.get("voices"), dict) else data
    return inner if isinstance(inner, dict) else {}


def load_mob_voice_pool(
    voices: dict[str, str],
    *,
    voices_file_path: Path | None = None,
) -> list[str]:
    """mob TTS voice_id 풀.

    1) voices.json ``mob_pool`` 배열
    2) mob_1… / MOB_MALE_01… / mob 키
    3) narrator 제외 캐릭터 voice (임시 폴백)
    """
    raw = _voices_raw_dict(voices_file_path)
    pool: list[str] = []
    seen: set[str] = set()

    def add(vid: str) -> None:
        v = (vid or "").strip()
        if v and v not in seen:
            seen.add(v)
            pool.append(v)

    mp = raw.get("mob_pool")
    if isinstance(mp, list):
        for item in mp:
            if isinstance(item, str):
                add(item)
    if pool:
        return pool

    for key in _MOB_KEY_CANDIDATES:
        if key in voices:
            add(voices[key])
        elif key in raw and isinstance(raw[key], str):
            add(str(raw[key]))
    if pool:
        return pool

    # 폴백: narrator 제외
    for k, v in voices.items():
        if k.casefold() in {"narrator", "note", "chapter"}:
            continue
        if k.casefold().startswith("mob"):
            continue
        add(v)
    return pool


class MobVoiceRotator:
    """순차 로테이션."""

    def __init__(self, pool: list[str]) -> None:
        if not pool:
            raise ValueError(
                "mob voice 풀이 비어 있습니다.\n"
                'voices.json 에 \"mob_pool\": [\"id1\", \"id2\", ...] '
                "또는 mob_1…mob_4 키를 넣으세요."
            )
        self._pool = list(pool)
        self._i = 0

    def next(self) -> str:
        vid = self._pool[self._i % len(self._pool)]
        self._i += 1
        return vid


def crowd_cache_path(out_dir: Path, *, kind: str = "quiet") -> Path:
    d = Path(out_dir) / "_sfx"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"crowd_{kind}.mp3"


def ensure_crowd_bed(
    *,
    api_key: str,
    out_dir: Path,
    duration_sec: float = 8.0,
    kind: str = "quiet",
    force: bool = False,
) -> Path:
    """조용한 군중 bed 캐시 (없으면 SFX API 생성)."""
    path = crowd_cache_path(out_dir, kind=kind)
    if path.is_file() and path.stat().st_size > 500 and not force:
        return path
    audio = synthesize_sound_effect_mp3(
        api_key.strip(),
        CROWD_PROMPT,
        duration_seconds=max(3.0, min(30.0, float(duration_sec))),
        loop=True,
        prompt_influence=0.4,
    )
    path.write_bytes(audio)
    return path


def apply_mob_mix(
    speech_mp3: Path,
    *,
    api_key: str,
    out_dir: Path,
    speech_db: float = MOB_SPEECH_DB,
    bed_db: float = CROWD_BED_DB,
) -> Path:
    """합성된 mob 대사에 군중 bed 믹스 (같은 파일 덮어쓰기)."""
    speech = Path(speech_mp3)
    bed = ensure_crowd_bed(api_key=api_key, out_dir=out_dir, duration_sec=8.0)
    tmp = speech.with_suffix(".mob_speech_only.mp3")
    try:
        # 원본 보존 후 믹스 결과를 speech 경로에
        speech.replace(tmp)
        mix_speech_over_bed(
            tmp,
            bed,
            speech,
            speech_db=speech_db,
            bed_db=bed_db,
        )
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
    return speech


__all__ = [
    "CROWD_BED_DB",
    "CROWD_PROMPT",
    "MOB_SPEAKER",
    "MOB_SPEECH_DB",
    "MobVoiceRotator",
    "apply_mob_mix",
    "ensure_crowd_bed",
    "is_mob_speaker",
    "load_mob_voice_pool",
    "strip_dialogue_quotes",
]
