# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "img_down_gui_config.json"

_KEYS = (
    "srt_file",
    "png_dir",
    "guide_file",
    "genspark_url",
    "genspark_model_selector",
    "chunk_index",
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
        if isinstance(v, str) and v.strip():
            out[k] = v.strip()
        elif k == "chunk_index" and isinstance(v, int):
            out[k] = str(v)
    return out


def load_model_selector() -> str:
    cfg = load_gui_settings()
    sel = cfg.get("genspark_model_selector", "").strip()
    if sel:
        return sel
    legacy = Path(__file__).resolve().parents[2] / "dist" / "srtToImage_gui_config.json"
    if legacy.is_file():
        try:
            data = json.loads(legacy.read_text(encoding="utf-8"))
            v = data.get("genspark_prompt_selector")
            if isinstance(v, str) and v.strip():
                return v.strip()
        except (OSError, json.JSONDecodeError, ValueError):
            pass
    return ""


def save_gui_settings(**kwargs: str) -> None:
    try:
        from wisdom_workspace import touch_workspace_from_path

        for key in ("srt_file", "png_dir", "guide_file"):
            v = kwargs.get(key, "").strip()
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
            base[k] = str(kwargs[k]).strip()
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
