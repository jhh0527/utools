# -*- coding: utf-8 -*-
"""대화형 dialogue JSON 로드 · speaker → voice_id 해석."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from script_voice.mob import (
    MobVoiceRotator,
    is_mob_speaker,
    load_mob_voice_pool,
    strip_dialogue_quotes,
)


@dataclass(frozen=True)
class DialogueLine:
    index: int  # 1-based → 01.mp3
    speaker: str
    voice_id: str
    text: str

    @property
    def mp3_name(self) -> str:
        n = self.index
        stem = f"{n:02d}" if n < 100 else str(n)
        return f"{stem}.mp3"


def _is_placeholder_voice(vid: str) -> bool:
    v = (vid or "").strip()
    if not v:
        return True
    u = v.upper()
    return u.startswith("VOICE_ID") or u.startswith("YOUR_") or u in {"TODO", "TBD", "XXX"}


def _resolve_voices_file_path(raw: str, *, json_path: Path) -> Path:
    """voices_file 경로 — 절대/상대(대화 JSON 기준) 해석."""
    vp = Path(raw.strip()).expanduser()
    if vp.is_file():
        return vp.resolve()
    rel = (json_path.parent / raw.strip()).resolve()
    if rel.is_file():
        return rel
    raise FileNotFoundError(
        f"voices_file 없음: {raw}\n"
        f"(대화 JSON 기준: {rel})"
    )


def _load_voices_map(
    data: dict,
    *,
    json_path: Path,
) -> dict[str, str]:
    """voices_file(권장) + 선택적 본문 voices 병합. 파일 로드 후 본문이 덮어씀."""
    merged: dict[str, str] = {}
    vf = data.get("voices_file")
    if isinstance(vf, str) and vf.strip():
        vp = _resolve_voices_file_path(vf, json_path=json_path)
        try:
            raw = json.loads(vp.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise ValueError(f"voices_file JSON 파싱 실패: {vp}\n{e}") from e
        if isinstance(raw, dict):
            # {"narrator": "..."} 평면 또는 {"voices": {...}}
            inner = raw.get("voices") if isinstance(raw.get("voices"), dict) else raw
            if isinstance(inner, dict):
                for k, v in inner.items():
                    if isinstance(k, str) and isinstance(v, str) and v.strip():
                        # 메타 키 제외
                        if k.strip() in {"chapter", "note", "chunk_id", "inputs", "voices_file"}:
                            continue
                        merged[k.strip()] = v.strip()
    voices = data.get("voices")
    if isinstance(voices, dict):
        for k, v in voices.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                merged[k.strip()] = v.strip()
    if not merged:
        raise ValueError(
            "화자 voice 맵이 비어 있습니다.\n"
            '예: \"voices_file\": \"../../voices.json\"\n'
            'voices.json 예: {\"narrator\": \"…\", \"jin\": \"…\"}'
        )
    return merged


def resolve_voice_id(
    *,
    speaker: str,
    line_voice_id: str,
    voices: dict[str, str],
) -> str:
    """기본: voices[speaker]. 줄에 실제 voice_id가 있으면 그 값을 사용."""
    sp = (speaker or "").strip()
    line_vid = (line_voice_id or "").strip()
    if not _is_placeholder_voice(line_vid):
        return line_vid
    if sp and sp in voices and voices[sp].strip():
        return voices[sp].strip()
    if sp:
        keys = ", ".join(sorted(voices)) or "(없음)"
        raise ValueError(
            f"speaker '{sp}' 가 voices_file 에 없습니다.\n"
            f"등록된 키: {keys}"
        )
    raise ValueError("inputs[].speaker 가 필요합니다 (voice_id 없이 합성).")


@dataclass(frozen=True)
class SpeakerCheckResult:
    """대본 speaker ↔ voices 맵 검사 결과."""

    dialogue_path: Path
    voices_path: Path | None
    speakers_in_script: tuple[str, ...]
    voices_keys: tuple[str, ...]
    missing: tuple[str, ...]
    empty_speaker_lines: int

    @property
    def ok(self) -> bool:
        return not self.missing and self.empty_speaker_lines == 0


def check_speakers_against_voices(path: Path | str) -> SpeakerCheckResult:
    """대본 inputs 의 speaker 가 voices_file(또는 voices)에 모두 있는지 확인.

    voice_id 유무와 관계없이 speaker 키 존재만 검사합니다.
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {p.name}\n{e}") from e
    if not isinstance(data, dict):
        raise ValueError("dialogue JSON 루트는 객체여야 합니다.")

    inputs = data.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("dialogue JSON 에 inputs 배열이 필요합니다.")

    voices_path: Path | None = None
    vf = data.get("voices_file")
    if isinstance(vf, str) and vf.strip():
        voices_path = _resolve_voices_file_path(vf, json_path=p)

    voices = _load_voices_map(data, json_path=p)
    mob_pool = load_mob_voice_pool(voices, voices_file_path=voices_path)
    seen: list[str] = []
    seen_set: set[str] = set()
    empty_lines = 0
    for item in inputs:
        if not isinstance(item, dict):
            continue
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        sp = str(item.get("speaker", "") or "").strip()
        if not sp:
            empty_lines += 1
            continue
        if sp not in seen_set:
            seen_set.add(sp)
            seen.append(sp)

    missing = tuple(
        s
        for s in seen
        if s not in voices and not (is_mob_speaker(s) and mob_pool)
    )
    return SpeakerCheckResult(
        dialogue_path=p,
        voices_path=voices_path,
        speakers_in_script=tuple(seen),
        voices_keys=tuple(sorted(voices)),
        missing=missing,
        empty_speaker_lines=empty_lines,
    )


def load_dialogue_json(path: Path | str) -> list[DialogueLine]:
    """dialogue JSON → 합성 줄 목록.

    권장 형식: voices_file + inputs[].speaker / text (voice_id 불필요).
    """
    p = Path(path).expanduser().resolve()
    if not p.is_file():
        raise FileNotFoundError(str(p))
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"JSON 파싱 실패: {p.name}\n{e}") from e
    if not isinstance(data, dict):
        raise ValueError("dialogue JSON 루트는 객체여야 합니다.")

    inputs = data.get("inputs")
    if not isinstance(inputs, list) or not inputs:
        raise ValueError("dialogue JSON 에 inputs 배열이 필요합니다.")

    voices = _load_voices_map(data, json_path=p)
    voices_path: Path | None = None
    vf = data.get("voices_file")
    if isinstance(vf, str) and vf.strip():
        voices_path = _resolve_voices_file_path(vf, json_path=p)
    mob_pool = load_mob_voice_pool(voices, voices_file_path=voices_path)
    mob_rotator: MobVoiceRotator | None = (
        MobVoiceRotator(mob_pool) if mob_pool else None
    )
    lines: list[DialogueLine] = []
    for i, item in enumerate(inputs, start=1):
        if not isinstance(item, dict):
            raise ValueError(f"inputs[{i - 1}] 가 객체가 아닙니다.")
        text = str(item.get("text", "") or "").strip()
        if not text:
            continue
        speaker = str(item.get("speaker", "") or "").strip()
        # voice_id 키는 선택 — 없으면 voices_file[speaker]
        line_vid = str(item.get("voice_id", "") or "").strip()
        if is_mob_speaker(speaker):
            if not _is_placeholder_voice(line_vid):
                vid = line_vid
            elif mob_rotator is None:
                raise ValueError(
                    "speaker 'mob' 인데 voices.json 에 mob_pool(또는 mob_1…)이 없습니다."
                )
            else:
                vid = mob_rotator.next()
            text = strip_dialogue_quotes(text)
        else:
            vid = resolve_voice_id(
                speaker=speaker, line_voice_id=line_vid, voices=voices
            )
        lines.append(
            DialogueLine(
                index=len(lines) + 1,
                speaker=speaker or "unknown",
                voice_id=vid,
                text=text,
            )
        )
    if not lines:
        raise ValueError("낭독할 text 가 있는 inputs 항목이 없습니다.")
    return lines


def format_dialogue_for_textarea(lines: list[DialogueLine]) -> str:
    """본문 textarea용 — ``[1] speaker | text`` 줄번호 미리보기."""
    out: list[str] = []
    for line in lines:
        text = " ".join((line.text or "").split())
        out.append(f"[{line.index}] {line.speaker} | {text}")
    return "\n".join(out) + ("\n" if out else "")


__all__ = [
    "DialogueLine",
    "SpeakerCheckResult",
    "check_speakers_against_voices",
    "format_dialogue_for_textarea",
    "load_dialogue_json",
    "resolve_voice_id",
]
