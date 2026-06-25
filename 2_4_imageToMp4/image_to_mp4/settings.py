# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "image_to_mp4_gui_config.json"

_DEFAULTS: dict[str, str] = {
    "comfyui_url": "http://127.0.0.1:8188",
    "input_dir": "",
    "output_dir": "",
    "positive_prompt": "high quality, smooth natural motion, cinematic",
    "negative_prompt": "bad quality, blurry, static, distorted, watermark",
    "checkpoint": "v1-5-pruned-emaonly.safetensors",
    "motion_module": "mm_sd_v15_v2.ckpt",
    "frames": "16",
    "fps": "8",
    "seed": "-1",
    "steps": "20",
    "cfg": "7.0",
    "denoise": "0.6",
    "workflow_path": "",
    "include_subfolders": "0",
}


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def load_gui_settings() -> dict[str, str]:
    p = config_path()
    out = dict(_DEFAULTS)
    if not p.is_file():
        return out
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return out
    if not isinstance(data, dict):
        return out
    for key in _DEFAULTS:
        v = data.get(key)
        if isinstance(v, (str, int, float, bool)) and str(v).strip():
            out[key] = str(v).strip()
    return out


def save_gui_settings(**kwargs: str) -> None:
    for p in (kwargs.get("input_dir", ""), kwargs.get("output_dir", ""), kwargs.get("workflow_path", "")):
        if p:
            try:
                from wisdom_workspace import touch_workspace_from_path

                touch_workspace_from_path(p)
            except ImportError:
                pass
    cfg = config_path()
    cfg.parent.mkdir(parents=True, exist_ok=True)
    data = load_gui_settings()
    for key, val in kwargs.items():
        if key in _DEFAULTS and isinstance(val, str):
            data[key] = val.strip()
    cfg.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
