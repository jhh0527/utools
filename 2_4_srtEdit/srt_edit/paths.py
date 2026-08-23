# -*- coding: utf-8 -*-
"""루트/tts · mp3 · 모듈 md 경로·파일 탐색."""

from __future__ import annotations

import sys
from pathlib import Path

GENSPARK_AI_CHAT_URL = "https://www.genspark.ai/agents?type=ai_chat"

_TTS_EXTS = {".txt", ".md", ".srt", ".json"}
_SRT_EXTS = {".srt"}
_MD_EXTS = {".md", ".txt"}


def subdir(root: Path | str, name: str) -> Path:
    return Path(root).expanduser() / name


def ensure_layout(root: Path | str) -> dict[str, Path]:
    """tts/mp3 폴더를 만들고 경로 dict 반환 (SRT는 mp3)."""
    r = Path(root).expanduser()
    r.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name in ("tts", "mp3"):
        p = r / name
        p.mkdir(parents=True, exist_ok=True)
        out[name] = p
    return out


def module_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def module_md_dir() -> Path:
    """모듈 ``2_4_srtEdit/md`` (보정 프롬프트)."""
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            p = Path(meipass) / "md"
            if p.is_dir():
                return p
        beside = Path(sys.executable).resolve().parent / "md"
        if beside.is_dir():
            return beside
    return module_root() / "md"


def _list_files(folder: Path, exts: set[str]) -> list[Path]:
    if not folder.is_dir():
        return []
    found: list[Path] = []
    try:
        for p in folder.iterdir():
            if p.is_file() and p.suffix.lower() in exts:
                found.append(p)
    except OSError:
        return []
    return sorted(found, key=lambda x: x.stat().st_mtime, reverse=True)


def list_tts_files(root: Path | str) -> list[Path]:
    files = _list_files(subdir(root, "tts"), _TTS_EXTS)
    # 첨부용 임시 plaintext 제외
    return [p for p in files if not p.name.startswith("_srt_edit_script_")]


def list_srt_files(root: Path | str) -> list[Path]:
    """Whisper SRT — 루트/mp3 우선, 없으면 구 stt. ``new.srt`` 는 산출물이라 제외."""
    files = _list_files(subdir(root, "mp3"), _SRT_EXTS)
    if not files:
        files = _list_files(subdir(root, "stt"), _SRT_EXTS)
    return [p for p in files if p.name.casefold() != "new.srt"]


def pick_source_srt(files: list[Path]) -> Path | None:
    """보정 입력 SRT — ``all.srt`` 우선, ``new.srt`` 는 쓰지 않음."""
    usable = [p for p in files if p.name.casefold() != "new.srt"]
    if not usable:
        return None
    for p in usable:
        if p.name.casefold() == "all.srt":
            return p
    return usable[0]


def write_new_srt(root: Path | str, body: str) -> Path:
    """검증된 SRT 본문을 ``{root}/mp3/new.srt`` 에 저장."""
    mp3 = ensure_layout(root)["mp3"]
    text = body if body.endswith("\n") else body + "\n"
    dest = mp3 / "new.srt"
    dest.write_text(text, encoding="utf-8")
    return dest


def list_stt_files(root: Path | str) -> list[Path]:
    """호환 별칭."""
    return list_srt_files(root)


def list_md_files(root: Path | str | None = None) -> list[Path]:
    """보정 지침 — 모듈 md 우선, 없으면 루트/md."""
    files = _list_files(module_md_dir(), _MD_EXTS)
    if files:
        return files
    if root is not None:
        return _list_files(subdir(root, "md"), _MD_EXTS)
    return []


def pick_latest(files: list[Path]) -> Path | None:
    return files[0] if files else None


def default_correct_command(*, srt_name: str, tts_name: str, md_name: str) -> str:
    """첨부 후 입력창에 넣을 보정 명령."""
    return (
        f"첨부한 「{md_name}」 지침에 따라, "
        f"첨부한 「{tts_name}」(tts/xx.json 의 text 원문)을 기준으로 "
        f"첨부한 「{srt_name}」(STT SRT) 중 원본과 다른 부분만 수정해 주세요. "
        f"띄어쓰기도 대본과 동일하게 맞추고, STT가 붙여 쓴 말은 공백을 복원하세요. "
        f"대본에 없는 구간은 SRT 원문을 유지하고, "
        f"결과는 start 와 end 를 구분자로 써서 "
        f"(start와 end 사이 내용만 교정 SRT) 출력해 주세요."
    )
