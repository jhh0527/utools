# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "stt_gui_config.json"


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
    for key in ("mp3_path", "original_path", "whisper_model"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def save_gui_settings(
    *,
    mp3_path: str = "",
    original_path: str = "",
    whisper_model: str = "",
) -> None:
    for p in (mp3_path, original_path):
        if p:
            try:
                from wisdom_workspace import touch_workspace_from_path

                touch_workspace_from_path(p)
            except ImportError:
                pass
    cfg = config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data: dict[str, str] = {}
    if mp3_path.strip():
        data["mp3_path"] = mp3_path.strip()
    if original_path.strip():
        data["original_path"] = original_path.strip()
    if whisper_model.strip():
        data["whisper_model"] = whisper_model.strip()
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
