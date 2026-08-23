# -*- coding: utf-8 -*-
"""대본(TTS) 파일에서 교정용 평문 추출."""

from __future__ import annotations

import json
import re
from pathlib import Path

# ElevenLabs 감정·연출 태그: [calm], [angry][slowly], 정렬 후 [ca lm ] 등
_EL_TAG_RE = re.compile(r"\[[^\]]*\]")
# TTS 대본의 대사 따옴표 — 자막에는 넣지 않음
_QUOTE_RE = re.compile(r'["\u201c\u201d\u201e\u201f\u00ab\u00bb\u300c\u300d\u300e\u300f]')


def strip_elevenlabs_tags(text: str) -> str:
    """일레븐랩스 ``[...]`` 태그·대사 따옴표 제거 (자막에 남기지 않음)."""
    s = _EL_TAG_RE.sub("", text or "")
    s = _QUOTE_RE.sub("", s)
    s = re.sub(r"[^\S\n]{2,}", " ", s)
    s = re.sub(r" *\n *", "\n", s)
    return s.strip()


def read_script_text(path: str | Path, *, limit: int = 500_000) -> str:
    """txt/md/json 대본 → 평문. JSON 은 text 필드들을 이어 붙인다.

    ElevenLabs ``[calm]`` 등 태그는 제거한다.
    """
    p = Path(path)
    if not p.is_file():
        return ""
    try:
        raw = p.read_text(encoding="utf-8-sig", errors="replace")
    except OSError:
        return ""
    if p.suffix.lower() == ".json":
        text = _texts_from_json(raw)
    else:
        text = raw
    text = strip_elevenlabs_tags(text)
    if limit and len(text) > limit:
        text = text[:limit]
    return text


def _texts_from_json(raw: str) -> str:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    parts: list[str] = []

    def walk(obj: object) -> None:
        if isinstance(obj, dict):
            # 흔한 TTS/라인 JSON: {"text": "..."} 우선
            if isinstance(obj.get("text"), str) and obj["text"].strip():
                parts.append(obj["text"].strip())
            for k, v in obj.items():
                if k == "text":
                    continue
                walk(v)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)
        elif isinstance(obj, str) and len(obj.strip()) > 40:
            # 너무 짧은 키/라벨은 제외
            if not re.match(r"^[\w.\-]+$", obj.strip()):
                parts.append(obj.strip())

    walk(data)
    # 중복 연속 제거
    out: list[str] = []
    prev = ""
    for t in parts:
        if t and t != prev:
            out.append(t)
            prev = t
    return "\n".join(out)


def script_plaintext_for_attach(
    path: str | Path, *, work_dir: Path | None = None
) -> Path:
    """Genspark 첨부용 .txt. 이미 txt/md 이면 원본 경로 반환."""
    p = Path(path)
    if p.suffix.lower() in {".txt", ".md"}:
        # 내용이 너무 짧으면 json 등 더 긴 대본을 쓰는 쪽은 GUI에서 처리
        return p
    text = read_script_text(p)
    base = work_dir or p.parent
    base.mkdir(parents=True, exist_ok=True)
    dest = base / f"_srt_edit_script_{p.stem}.txt"
    dest.write_text(text + ("\n" if text and not text.endswith("\n") else ""), encoding="utf-8")
    return dest


def pick_richest_script(files: list[Path]) -> Path | None:
    """추출 평문이 가장 긴 대본 파일."""
    best: Path | None = None
    best_n = -1
    for p in files:
        n = len(read_script_text(p))
        if n > best_n:
            best_n = n
            best = p
    return best


def pick_tts_json(files: list[Path]) -> Path | None:
    """tts 폴더 대본 — ``*.json``(text 필드) 우선, 없으면 기존 최장 평문."""
    jsons = [p for p in files if p.suffix.lower() == ".json"]
    if jsons:
        return pick_richest_script(jsons)
    return pick_richest_script(files)


def resolve_tts_json(
    selected: Path | None, *, root: Path | str | None = None
) -> Path | None:
    """선택 경로가 txt여도 같은 stem 의 ``tts/xx.json`` 을 원문으로 씀."""
    if selected is not None and selected.is_file() and selected.suffix.lower() == ".json":
        return selected
    stem = ""
    if selected is not None:
        stem = selected.stem
        # 첨부용 임시 plaintext: _srt_edit_script_2.txt → 2.json
        if stem.startswith("_srt_edit_script_"):
            stem = stem[len("_srt_edit_script_") :]
        sibling = selected.with_suffix(".json")
        if sibling.is_file():
            return sibling
    search_dirs: list[Path] = []
    if selected is not None:
        search_dirs.append(selected.parent)
    if root:
        search_dirs.append(Path(root).expanduser() / "tts")
    seen: set[str] = set()
    for d in search_dirs:
        key = str(d.resolve()) if d.is_dir() else ""
        if not key or key in seen:
            continue
        seen.add(key)
        if stem:
            cand = d / f"{stem}.json"
            if cand.is_file():
                return cand
        try:
            jsons = sorted(
                (p for p in d.iterdir() if p.is_file() and p.suffix.lower() == ".json"),
                key=lambda x: x.stat().st_mtime,
                reverse=True,
            )
        except OSError:
            jsons = []
        if jsons:
            return pick_richest_script(jsons) or jsons[0]
    return selected if selected is not None and selected.is_file() else None
