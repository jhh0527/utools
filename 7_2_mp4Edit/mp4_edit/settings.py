# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "mp4_edit_gui_config.json"

_STR_KEYS = (
    "mp4_path",
    "output_dir",
    "output_name",
    "start_sec",
    "end_sec",
)


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def load_gui_settings() -> dict[str, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in _STR_KEYS:
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def save_gui_settings(
    *,
    mp4_path: str | None = None,
    output_dir: str | None = None,
    output_name: str | None = None,
    start_sec: str | None = None,
    end_sec: str | None = None,
) -> None:
    if mp4_path is not None:
        try:
            from wisdom_workspace import touch_workspace_from_path

            touch_workspace_from_path(mp4_path)
        except ImportError:
            pass
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                for key in _STR_KEYS:
                    v = raw.get(key)
                    if isinstance(v, str):
                        data[key] = v
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    updates = {
        "mp4_path": mp4_path,
        "output_dir": output_dir,
        "output_name": output_name,
        "start_sec": start_sec,
        "end_sec": end_sec,
    }
    for key, val in updates.items():
        if val is not None:
            data[key] = val
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
