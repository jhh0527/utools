# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "scene_image_gui_config.json"

_KEYS = (
    "root_dir",
    "png_dir",
    "tts_dir",
    "genspark_url",
    "genspark_model_selector",
    "scene_script",
    "scene_index",
    "srt_path",
    "prompt_path",
    "interval_sec",
    "request_wait_sec",
    "manual_secs",
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
    for k in _KEYS:
        v = data.get(k)
        if isinstance(v, str):
            out[k] = v
        elif k in ("scene_index", "interval_sec", "request_wait_sec") and isinstance(
            v, int
        ):
            out[k] = str(v)
    return out


def load_model_selector() -> str:
    return load_gui_settings().get("genspark_model_selector", "").strip()


def save_gui_settings(**kwargs: str) -> None:
    try:
        from wisdom_workspace import touch_workspace_from_path

        v = kwargs.get("root_dir", "").strip() or kwargs.get("png_dir", "").strip()
        if v:
            touch_workspace_from_path(v)
    except ImportError:
        pass
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError, ValueError):
            base = {}
    for k in _KEYS:
        if k in kwargs and kwargs[k] is not None:
            base[k] = str(kwargs[k])
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
