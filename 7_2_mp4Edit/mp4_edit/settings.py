# -*- coding: utf-8 -*-
"""GUI 마지막 MP4 경로 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "mp4_edit_gui_config.json"


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
    v = data.get("mp4_path")
    if isinstance(v, str) and v.strip():
        out["mp4_path"] = v.strip()
    return out


def save_gui_settings(*, mp4_path: str) -> None:
    try:
        from wisdom_workspace import touch_workspace_from_path

        touch_workspace_from_path(mp4_path)
    except ImportError:
        pass
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"mp4_path": mp4_path}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
