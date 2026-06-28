# -*- coding: utf-8 -*-
"""MP3 주변에서 원본·TTS 대본 자동 로드."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

_PART_MP3_RE = re.compile(r"part(\d+)", re.IGNORECASE)
_PART_HEADER = re.compile(r"^\s*(\d+)\.\{\}\s*$")
_ORIGINAL_LABEL = r"(?:원본|原稿|Original)"
_CAPTION_ID_ONLY = re.compile(r"^\s*(\d+-\d+)\s*$")
_CAPTION_LINE_RE = re.compile(
    rf"^\s*(\d+-\d+)\s+{_ORIGINAL_LABEL}:\s*(.+)$",
    re.IGNORECASE,
)
_ORIGINAL_LINE = re.compile(
    rf"^\s*{_ORIGINAL_LABEL}:\s*(.*)$",
    re.IGNORECASE,
)
_TTS_LINE = re.compile(r"^\s*TTS:\s*(.*)$", re.IGNORECASE)
_STT_REF_LINE = re.compile(r"^\s*STT_Reference:\s*(.*)$", re.IGNORECASE)
_TTS_SEP = re.compile(r"\s+TTS:\s+", re.IGNORECASE)
_STT_REF_SEP = re.compile(r"\s+STT_Reference:\s*", re.IGNORECASE)
_SENTENCE_END = frozenset(".!?…。！？")


@dataclass(frozen=True)
class ScriptTexts:
    original: str
    tts: str
    source: str


def _part_id_from_mp3(mp3_path: Path) -> str | None:
    m = _PART_MP3_RE.search(mp3_path.stem)
    if not m:
        return None
    return str(int(m.group(1)))


def _load_text(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except (OSError, UnicodeDecodeError):
            continue
    raise OSError(f"텍스트를 읽을 수 없습니다: {path}")


def _strip_stt_reference(text: str) -> str:
    return _STT_REF_SEP.split(text, 1)[0].strip()


def _parse_knowledgetts(text: str, *, part_id: str | None) -> tuple[list[str], list[str]]:
    originals: list[str] = []
    tts_lines: list[str] = []
    pending_id: str | None = None
    pending_orig: str | None = None

    def _append(cap_id: str, orig: str, tts: str) -> None:
        cap_part = cap_id.split("-", 1)[0]
        if part_id is not None and cap_part != part_id:
            return
        originals.append(orig.strip())
        tts_lines.append(tts.strip())

    for raw in text.splitlines():
        line = raw.rstrip("\r\n")
        if not line.strip():
            continue
        hm = _PART_HEADER.match(line)
        if hm:
            pending_id = pending_orig = None
            continue
        if line.strip().startswith("**"):
            continue

        m = _CAPTION_LINE_RE.match(line)
        if m:
            pending_id = pending_orig = None
            cap_id = m.group(1)
            parts = _TTS_SEP.split(m.group(2), 1)
            if len(parts) == 2:
                _append(cap_id, parts[0], _strip_stt_reference(parts[1]))
            continue

        id_m = _CAPTION_ID_ONLY.match(line)
        if id_m:
            pending_id = id_m.group(1)
            pending_orig = None
            continue

        if _STT_REF_LINE.match(line):
            continue

        orig_m = _ORIGINAL_LINE.match(line)
        if orig_m and pending_id:
            pending_orig = orig_m.group(1).strip()
            continue

        tts_m = _TTS_LINE.match(line)
        if tts_m and pending_id and pending_orig is not None:
            _append(pending_id, pending_orig, tts_m.group(1))
            pending_id = pending_orig = None
            continue

    return originals, tts_lines


def _from_part_json(mp3_path: Path) -> ScriptTexts | None:
    json_path = mp3_path.with_suffix(".json")
    if not json_path.is_file():
        return None
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    segments = data.get("segments")
    if not isinstance(segments, list) or not segments:
        return None
    originals: list[str] = []
    tts_lines: list[str] = []
    for seg in segments:
        if not isinstance(seg, dict):
            continue
        orig = str(seg.get("original") or "").strip()
        tts = str(seg.get("tts") or "").strip()
        if orig:
            originals.append(orig)
        if tts:
            tts_lines.append(tts)
    if not tts_lines:
        return None
    return ScriptTexts(
        original="".join(originals),
        tts="".join(tts_lines),
        source=json_path.name,
    )


def _from_tts_txt(mp3_path: Path) -> ScriptTexts | None:
    part_id = _part_id_from_mp3(mp3_path)
    candidates: list[Path] = []
    for folder in (mp3_path.parent, mp3_path.parent.parent / "tts", mp3_path.parent / "tts"):
        if folder.is_dir():
            candidates.extend(sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen:
            continue
        seen.add(path)
        try:
            text = _load_text(path)
        except OSError:
            continue
        origs, tts_list = _parse_knowledgetts(text, part_id=part_id)
        if tts_list:
            return ScriptTexts(
                original="".join(origs),
                tts="".join(tts_list),
                source=path.name,
            )
    return None


def load_script_texts(mp3_path: Path) -> ScriptTexts | None:
    """MP3와 같은 part.json 또는 주변 TTS txt에서 원본·TTS를 찾습니다."""
    mp3_path = Path(mp3_path)
    from_json = _from_part_json(mp3_path)
    if from_json:
        return from_json
    return _from_tts_txt(mp3_path)
