# -*- coding: utf-8 -*-
"""루트/tts · 모듈 md 경로·파일 탐색."""

from __future__ import annotations

import json
import sys
from pathlib import Path

GENSPARK_AI_CHAT_URL = "https://www.genspark.ai/agents?type=ai_chat"

_TXT_EXTS = {".txt", ".md"}
_MD_EXTS = {".md", ".txt"}


def subdir(root: Path | str, name: str) -> Path:
    return Path(root).expanduser() / name


def ensure_layout(root: Path | str) -> dict[str, Path]:
    """tts·md 폴더를 만들고 경로 dict 반환."""
    r = Path(root).expanduser()
    r.mkdir(parents=True, exist_ok=True)
    out: dict[str, Path] = {}
    for name in ("tts", "md"):
        p = r / name
        p.mkdir(parents=True, exist_ok=True)
        out[name] = p
    return out


def tts_dir(root: Path | str) -> Path:
    return Path(root).expanduser() / "tts"


def md_dir(root: Path | str) -> Path:
    return Path(root).expanduser() / "md"


def module_root() -> Path:
    """워크스페이스의 ``1_2_textToJson`` (없으면 패키지/번들)."""
    try:
        from wisdom_root import module_dir

        src = module_dir("1_2_textToJson")
        if src.is_dir():
            return src.resolve()
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def module_md_dir() -> Path:
    """모듈 ``1_2_textToJson/md`` — 소스 트리 우선 (exe ``_MEI`` 임시폴더보다 앞)."""
    src = module_root() / "md"
    if src.is_dir():
        return src.resolve()
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", "")
        if meipass:
            p = Path(meipass) / "md"
            if p.is_dir():
                return p
        beside = Path(sys.executable).resolve().parent / "md"
        if beside.is_dir():
            return beside
    return src


def default_dialogue_json_md() -> Path | None:
    """변환 지침 디폴트: ``…/1_2_textToJson/md/dialogue_json.txt``."""
    p = module_md_dir() / "dialogue_json.txt"
    if p.is_file():
        return p.resolve()
    ranked = _rank_md_files(_list_files(module_md_dir(), _MD_EXTS))
    return ranked[0].resolve() if ranked else None


def is_canonical_dialogue_md(path: Path | str | None) -> bool:
    """모듈 dialogue_json.txt 인지 (임시 _MEI 경로 제외)."""
    if path is None:
        return False
    try:
        p = Path(path).expanduser()
        s = str(p).replace("\\", "/")
        if "_MEI" in s:
            return False
        if p.name.casefold() != "dialogue_json.txt":
            return False
        if not p.is_file():
            return False
        guide = default_dialogue_json_md()
        if guide is not None and p.resolve() == guide.resolve():
            return True
        return "1_2_textToJson" in s and "/md/" in s.casefold()
    except OSError:
        return False


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


def _rank_md_files(files: list[Path]) -> list[Path]:
    """dialogue_json* 우선, jsonSample 제외."""
    preferred: list[Path] = []
    others: list[Path] = []
    for p in files:
        name = p.name.casefold()
        if "sample" in name and name.endswith(".json"):
            continue
        if name.startswith("dialogue_json") or (
            name.startswith("json") and name.endswith((".txt", ".md"))
        ):
            preferred.append(p)
        else:
            others.append(p)
    return preferred + others


def list_txt_files(root: Path | str) -> list[Path]:
    """루트/tts 의 txt (임시·합본·진단 덤프 제외)."""
    skip = {
        "text_to_json_bundle.txt",
        "text_to_json_diag.log",
    }
    files = _list_files(subdir(root, "tts"), _TXT_EXTS)
    out: list[Path] = []
    for p in files:
        name = p.name.casefold()
        if p.name.startswith("_"):
            continue
        if name in skip:
            continue
        if name.startswith("text_to_json_page_"):
            continue
        if name.startswith("text_to_json_bundle"):
            continue
        out.append(p)
    return out


def is_source_txt_path(path: Path | str | None) -> bool:
    """대본 TXT로 쓸 수 있는 경로인지 (합본·덤프 제외)."""
    if path is None:
        return False
    try:
        p = Path(path)
    except (TypeError, ValueError):
        return False
    if not p.is_file():
        return False
    name = p.name.casefold()
    if name.startswith("_") or name.startswith("text_to_json_"):
        return False
    return p.suffix.lower() in _TXT_EXTS


def list_md_files(root: Path | str | None = None) -> list[Path]:
    """변환 지침 — **모듈 md 우선** (dialogue_json.txt), 없으면 루트/md."""
    mod = _rank_md_files(_list_files(module_md_dir(), _MD_EXTS))
    if mod:
        return mod
    if root is not None:
        return _rank_md_files(_list_files(subdir(root, "md"), _MD_EXTS))
    return []


def path_under_root(path: Path | str, root: Path | str) -> bool:
    try:
        Path(path).expanduser().resolve().relative_to(Path(root).expanduser().resolve())
        return True
    except (ValueError, OSError):
        return False


def pick_latest(files: list[Path]) -> Path | None:
    return files[0] if files else None


def json_sample_path() -> Path | None:
    """형식 참고용 ``md/jsonSample.json``."""
    md = module_md_dir()
    for name in ("jsonSample.json", "json_sample.json", "JsonSample.json"):
        p = md / name
        if p.is_file():
            return p.resolve()
    try:
        for p in md.glob("jsonSample*.json"):
            if p.is_file():
                return p.resolve()
    except OSError:
        pass
    return None


def find_voices_json(root: Path | str | None) -> Path | None:
    """장 루트 기준 ``voices.json`` — ``{부}/voices.json`` 등."""
    if root is None:
        return None
    r = Path(root).expanduser()
    candidates: list[Path] = [
        r / "voices.json",
        r.parent / "voices.json",
        r.parent.parent / "voices.json",
        r / "tts" / "voices.json",
    ]
    # tts 파일에서 온 경우: …/4장/tts → …/1부/voices.json
    if r.name.casefold() == "tts":
        candidates.insert(0, r.parent.parent / "voices.json")
    seen: set[str] = set()
    for p in candidates:
        try:
            key = str(p.resolve())
        except OSError:
            key = str(p)
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            return p.resolve()
    return None


def voice_speaker_keys(voices_path: Path | str | None) -> list[str]:
    """voices.json 의 speaker 키 (mob_pool 제외)."""
    if voices_path is None:
        return []
    p = Path(voices_path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    inner = data.get("voices") if isinstance(data.get("voices"), dict) else data
    if not isinstance(inner, dict):
        return []
    keys: list[str] = []
    for k, v in inner.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if k.strip().casefold() in {"mob_pool", "voices"}:
            continue
        if isinstance(v, (list, dict)):
            continue
        keys.append(k.strip())
    return keys


def default_json_path(txt_path: Path | str, root: Path | str | None = None) -> Path:
    """``{루트}/tts/{txt stem}.json``."""
    t = Path(txt_path).expanduser()
    parent = t.parent if t.suffix else tts_dir(root or ".")
    if root is not None:
        parent = tts_dir(root)
        if t.parent.name.casefold() == "tts":
            parent = t.parent
    return parent / f"{t.stem}.json"


def default_convert_command(
    *,
    txt_name: str,
    md_name: str,
    sample_name: str = "",
    voices_name: str = "",
    voice_keys: list[str] | None = None,
) -> str:
    """합본 텍스트 앞에 붙일 변환 명령."""
    sample_bit = (
        f"아래 「{sample_name}」 형식 예시를 참고하고, "
        if sample_name.strip()
        else ""
    )
    voices_bit = (
        f"아래 「{voices_name}」의 speaker 키만 사용하고, "
        if voices_name.strip()
        else ""
    )
    keys = [k for k in (voice_keys or []) if k]
    keys_bit = ""
    if keys:
        shown = ", ".join(keys[:24])
        more = " …" if len(keys) > 24 else ""
        keys_bit = (
            f"허용 speaker: {shown}{more}, 그 외 단역은 mob. "
            f"청허→cheongheo(chung 금지). "
        )
    return (
        f"아래 「{md_name}」 지침에 따라, "
        f"{sample_bit}"
        f"{voices_bit}"
        f"{keys_bit}"
        f"아래 「{txt_name}」(대본 텍스트)를 "
        f"2_2 scriptToVoice용 dialogue JSON으로 변환해 주세요. "
        f"모든 대사·속마음에 [calm] 등 감정 태그를 반드시 붙이세요 "
        f"(원문에 없어도 부여). "
        f"설명·마크다운 없이 JSON 본문만 출력해 주세요. "
        f"형식: chapter, voices_file, chunk_id, inputs[{{speaker, text}}]."
    )
