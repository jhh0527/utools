# -*- coding: utf-8 -*-
"""GUI 마지막 스캔 폴더 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "md_file_gui_config.json"


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
    v = data.get("scan_dir")
    if isinstance(v, str) and v.strip():
        out["scan_dir"] = v.strip()
    return out


def save_gui_settings(*, scan_dir: str) -> None:
    try:
        from wisdom_workspace import touch_workspace_from_path

        touch_workspace_from_path(scan_dir)
    except ImportError:
        pass
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {"scan_dir": scan_dir}
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
