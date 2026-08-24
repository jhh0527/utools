# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "mp4_merge_gui_config.json"


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def load_gui_settings() -> dict:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_gui_settings(
    *,
    mp4_folder: str | None = None,
    mute_files: dict[str, str] | None = None,
) -> None:
    if mp4_folder is not None:
        try:
            from wisdom_workspace import touch_workspace_from_path

            touch_workspace_from_path(mp4_folder)
        except ImportError:
            pass
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                data = raw
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    if mp4_folder is not None:
        data["mp4_folder"] = mp4_folder
    if mute_files is not None:
        data["mute_files"] = {
            str(k).lower(): ("mute" if str(v).strip().lower() in ("mute", "1", "true", "음소거") else "sound")
            for k, v in mute_files.items()
        }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_mute_files() -> dict[str, str]:
    raw = load_gui_settings().get("mute_files")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip():
            key = k.strip().lower()
            mute = str(v).strip().lower() in ("mute", "1", "true", "음소거")
            out[key] = "mute" if mute else "sound"
    return out
