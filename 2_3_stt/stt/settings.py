# -*- coding: utf-8 -*-
"""2_3_stt GUI 설정 — 루트/mp3 (음성·SRT)."""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

PROJECT_DIRNAME = "2_3_stt"
GUI_CONFIG_NAME = "stt_gui_config.json"
MODEL_CHOICES = ("tiny", "base", "small", "medium", "large-v3")
_AUDIO_EXTS = {".mp3", ".wav", ".m4a", ".mp4", ".mkv", ".webm", ".flac", ".ogg"}


def _ensure_wisdom_on_path(from_file: str | Path) -> None:
    if importlib.util.find_spec("wisdom_root") is not None:
        return
    candidates: list[Path] = [Path.cwd(), *Path(from_file).resolve().parents]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    seen: set[str] = set()
    for base in candidates:
        try:
            root = base.resolve()
        except OSError:
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        if (root / "wisdom_root.py").is_file():
            if key not in sys.path:
                sys.path.insert(0, key)
            return


_ensure_wisdom_on_path(__file__)
from wisdom_root import module_dir
from wisdom_workspace import (
    folder_dialog_initial,
    get_workspace_dir,
    resolve_module_output,
    touch_workspace_from_path,
)


def _frozen_exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def module_dist_dir() -> Path:
    return module_dir(PROJECT_DIRNAME) / "dist"


def default_root_dir() -> Path:
    ws = get_workspace_dir()
    if ws is not None:
        return ws
    return resolve_module_output(PROJECT_DIRNAME)


def mp3_dir(root: Path | str) -> Path:
    return Path(root).expanduser() / "mp3"


def ensure_root_layout(root: Path | str) -> Path:
    """루트/mp3 생성 · mp3 경로 반환 (음성·SRT 동일)."""
    r = Path(root).expanduser()
    r.mkdir(parents=True, exist_ok=True)
    m = mp3_dir(r)
    m.mkdir(parents=True, exist_ok=True)
    return m


def default_output_dir() -> Path:
    return mp3_dir(default_root_dir())


def migrate_root_from_saved(cfg: dict[str, str]) -> str:
    saved = (cfg.get("root_dir") or "").strip()
    if saved:
        return saved
    for key in ("mp3_dir", "output_dir", "audio_path"):
        raw = (cfg.get(key) or "").strip()
        if not raw:
            continue
        p = Path(raw)
        if p.is_file():
            p = p.parent
        name = p.name.casefold()
        if name in {"mp3", "tts", "output", "stt"}:
            return str(p.parent)
        return str(p)
    return str(default_root_dir())


def list_mp3_media(mp3_folder: Path | str) -> list[Path]:
    d = Path(mp3_folder)
    if not d.is_dir():
        return []
    found: list[Path] = []
    try:
        for p in d.iterdir():
            if p.is_file() and p.suffix.lower() in _AUDIO_EXTS:
                found.append(p)
    except OSError:
        return []
    return sorted(found, key=lambda x: x.stat().st_mtime, reverse=True)


def gui_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return _frozen_exe_dir() / GUI_CONFIG_NAME
    d = module_dist_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / GUI_CONFIG_NAME


def load_gui_settings() -> dict[str, str]:
    p = gui_config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in (
        "root_dir",
        "mp3_dir",
        "audio_path",
        "output_dir",
        "whisper_model",
        "language",
    ):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def save_gui_settings(
    *,
    root_dir: str = "",
    mp3_path: str = "",
    audio_path: str = "",
    output_dir: str = "",
    whisper_model: str = "base",
    language: str = "ko",
) -> None:
    root = (root_dir or "").strip()
    mp3 = (mp3_path or output_dir or "").strip()
    if root:
        touch_workspace_from_path(root)
    elif mp3:
        touch_workspace_from_path(mp3)
    if audio_path.strip():
        touch_workspace_from_path(audio_path)
    p = gui_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "root_dir": root,
        "mp3_dir": mp3,
        "output_dir": mp3,  # 호환: SRT = mp3
        "audio_path": audio_path.strip(),
        "whisper_model": whisper_model.strip() or "base",
        "language": language.strip() or "ko",
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


__all__ = [
    "MODEL_CHOICES",
    "PROJECT_DIRNAME",
    "default_output_dir",
    "default_root_dir",
    "ensure_root_layout",
    "folder_dialog_initial",
    "list_mp3_media",
    "load_gui_settings",
    "migrate_root_from_saved",
    "module_dist_dir",
    "mp3_dir",
    "save_gui_settings",
]
