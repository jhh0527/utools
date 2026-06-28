# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "mp4_search_gui_config.json"


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def load_download_mp4_inputs() -> dict[str, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("download_mp4_inputs")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip():
            out[k.strip()] = v.strip()
    return out


def save_download_mp4_inputs(inputs: dict[str, str]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError):
            base = {}
    base["download_mp4_inputs"] = inputs
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_gui_settings() -> dict[str, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("srt_file", "mp4_dir", "download_dir", "mp3_file", "preview_pane_width"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def save_gui_settings(
    *,
    srt_file: str = "",
    mp4_dir: str = "",
    download_dir: str = "",
    mp3_file: str = "",
    preview_pane_width: str = "",
) -> None:
    p = config_path()
    data: dict = {}
    if p.is_file():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                data = old
        except (OSError, json.JSONDecodeError):
            pass
    if srt_file.strip():
        data["srt_file"] = srt_file.strip()
    if mp4_dir.strip():
        data["mp4_dir"] = mp4_dir.strip()
    if download_dir.strip():
        data["download_dir"] = download_dir.strip()
    if mp3_file.strip():
        data["mp3_file"] = mp3_file.strip()
    if preview_pane_width.strip().isdigit():
        data["preview_pane_width"] = int(preview_pane_width.strip())
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
