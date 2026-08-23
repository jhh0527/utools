# -*- coding: utf-8 -*-
"""2_2_scriptToVoice 설정 — GUI + ElevenLabs (2_1 dist 우선)."""

from __future__ import annotations

import json
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIRNAME = "2_2_scriptToVoice"
ELSUB_PROJECT = "2_1_ttsToVoice"
GUI_CONFIG_NAME = "script_voice_gui_config.json"
PRESET_NAMES: tuple[str, ...] = (
    "elsub_config.json",
    "elsub_config2.json",
    "elsub_config3.json",
    "elsub_config4.json",
    "elsub_config5.json",
)


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
    resolve_module_output,
    touch_workspace_from_path,
)

_config_path_override: Path | None = None


def set_config_path_override(path: Path | str | None) -> None:
    global _config_path_override
    if path is None or (isinstance(path, str) and not path.strip()):
        _config_path_override = None
        return
    _config_path_override = Path(path).expanduser().resolve()


def _frozen_exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def module_dist_dir() -> Path:
    return module_dir(PROJECT_DIRNAME) / "dist"


def elsub_dist_dir() -> Path:
    return module_dir(ELSUB_PROJECT) / "dist"


def default_output_dir() -> Path:
    """기본은 루트/mp3."""
    return mp3_dir(default_root_dir())


def default_root_dir() -> Path:
    from wisdom_workspace import get_workspace_dir

    ws = get_workspace_dir()
    if ws is not None:
        return ws
    # 모듈 output 부모가 아니라 작업 폴더 우선; 없으면 모듈 output
    return resolve_module_output(PROJECT_DIRNAME)


def mp3_dir(root: Path | str) -> Path:
    return Path(root).expanduser() / "mp3"


def tts_dir(root: Path | str) -> Path:
    """대본·dialogue JSON 폴더 (루트/tts)."""
    return Path(root).expanduser() / "tts"


def default_dialogue_json(root: Path | str) -> Path:
    """루트 지정 시 쓸 dialogue JSON — ``tts/{루트이름}.json`` 우선, 없으면 tts 안 단일 json."""
    r = Path(root).expanduser()
    td = tts_dir(r)
    preferred = td / f"{r.name}.json"
    if preferred.is_file():
        return preferred.resolve()
    try:
        jsons = sorted(p for p in td.glob("*.json") if p.is_file())
    except OSError:
        jsons = []
    if len(jsons) == 1:
        return jsons[0].resolve()
    return preferred


def ensure_root_layout(root: Path | str) -> Path:
    """루트/mp3·tts 생성, mp3 경로 반환."""
    r = Path(root).expanduser()
    r.mkdir(parents=True, exist_ok=True)
    t = mp3_dir(r)
    t.mkdir(parents=True, exist_ok=True)
    tts_dir(r).mkdir(parents=True, exist_ok=True)
    return t


def migrate_root_from_saved(cfg: dict[str, str]) -> str:
    """구 output_dir / tts_dir / mp3_dir → root_dir 추정."""
    saved_root = (cfg.get("root_dir") or "").strip()
    if saved_root:
        return saved_root
    out = (
        (cfg.get("mp3_dir") or "").strip()
        or (cfg.get("tts_dir") or "").strip()
        or (cfg.get("output_dir") or "").strip()
    )
    if not out:
        return str(default_root_dir())
    p = Path(out)
    name = p.name.casefold()
    if name in {"mp3", "tts", "output"}:
        return str(p.parent)
    return str(p)


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
        "output_dir",
        "mp3_dir",
        "tts_dir",
        "config_file",
        "dialogue_json",
        "script_text",
        "gap_sec",
        "range_spec",
    ):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
        elif key == "gap_sec" and isinstance(v, (int, float)):
            out[key] = str(v)
    return out


def save_gui_settings(
    *,
    root_dir: str = "",
    output_dir: str = "",
    tts_path: str = "",
    mp3_path: str = "",
    config_file: str = "",
    dialogue_json: str = "",
    script_text: str = "",
    gap_sec: str = "1",
    range_spec: str = "",
) -> None:
    root = (root_dir or "").strip()
    outp = (mp3_path or tts_path or output_dir or "").strip()
    if root:
        touch_workspace_from_path(root)
    elif outp:
        touch_workspace_from_path(outp)
    p = gui_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {
        "gap_sec": (gap_sec or "1").strip(),
    }
    if root:
        data["root_dir"] = root
    if outp:
        data["mp3_dir"] = outp
        data["tts_dir"] = outp  # 호환
        data["output_dir"] = outp
    if config_file.strip():
        data["config_file"] = config_file.strip()
    if (dialogue_json or "").strip():
        data["dialogue_json"] = dialogue_json.strip()
    if (range_spec or "").strip():
        data["range_spec"] = range_spec.strip()
    if script_text:
        # 너무 긴 대본은 저장 생략 (경로·설정만 유지)
        if len(script_text) <= 200_000:
            data["script_text"] = script_text
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def preset_config_paths() -> list[Path]:
    """2_1 dist 우선, 없으면 본 모듈 dist."""
    out: list[Path] = []
    for base in (elsub_dist_dir(), module_dist_dir()):
        for name in PRESET_NAMES:
            p = base / name
            if p.is_file() and p not in out:
                out.append(p)
    if not out:
        out = [elsub_dist_dir() / PRESET_NAMES[0], module_dist_dir() / PRESET_NAMES[0]]
    return out


def resolve_preset_config(saved: str | None = None) -> Path:
    presets = preset_config_paths()
    by_name = {p.name: p for p in presets}
    if saved and saved.strip():
        raw = Path(saved.strip()).expanduser()
        if raw.is_file():
            return raw.resolve()
        if raw.name in by_name:
            return by_name[raw.name]
    for p in presets:
        if p.is_file():
            return p
    return presets[0]


def config_file_path() -> Path:
    if _config_path_override is not None:
        return _config_path_override
    return resolve_preset_config()


@dataclass
class AppSettings:
    elevenlabs_api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_multilingual_v2"


def load_settings() -> AppSettings:
    path = config_file_path()
    if not path.is_file():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(raw, dict):
        return AppSettings()
    return AppSettings(
        elevenlabs_api_key=str(raw.get("elevenlabs_api_key", "") or "").strip(),
        voice_id=str(raw.get("voice_id", "") or "").strip(),
        model_id=str(raw.get("model_id", "") or "eleven_multilingual_v2").strip(),
    )


# re-export for GUI
__all__ = [
    "AppSettings",
    "PROJECT_DIRNAME",
    "config_file_path",
    "default_output_dir",
    "default_root_dir",
    "ensure_root_layout",
    "folder_dialog_initial",
    "load_gui_settings",
    "load_settings",
    "migrate_root_from_saved",
    "module_dist_dir",
    "mp3_dir",
    "preset_config_paths",
    "resolve_preset_config",
    "save_gui_settings",
    "set_config_path_override",
    "tts_dir",  # 루트/tts (dialogue JSON)
]
