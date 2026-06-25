# -*- coding: utf-8 -*-
"""GUI 마지막 사용 경로 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "srtToImage_gui_config.json"


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def default_png_dir() -> Path:
    from wisdom_workspace import resolve_module_output

    return resolve_module_output("2_2_srtToImage") / "png"


def default_srt_file() -> Path:
    from wisdom_workspace import get_workspace_dir, resolve_module_output

    ws = get_workspace_dir()
    if ws is not None:
        cand = ws / "2_1_ttsToVoice" / "output" / "all.srt"
        if cand.is_file():
            return cand
    return resolve_module_output("2_1_ttsToVoice") / "all.srt"


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
    for key in ("png_dir", "srt_file", "genspark_prompt_selector", "image_guide"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    pw = data.get("preview_pane_width")
    if isinstance(pw, int) and pw >= 200:
        out["preview_pane_width"] = str(pw)
    elif isinstance(pw, str) and pw.isdigit() and int(pw) >= 200:
        out["preview_pane_width"] = pw
    return out


def save_gui_settings(
    *,
    png_dir: str,
    srt_file: str | None = None,
    preview_pane_width: int | None = None,
    genspark_prompt_selector: str | None = None,
    image_guide: str | None = None,
) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                data = cur
        except (OSError, json.JSONDecodeError, ValueError):
            data = {}
    data["png_dir"] = png_dir
    if srt_file is not None and srt_file.strip():
        data["srt_file"] = srt_file.strip()
    try:
        from wisdom_workspace import touch_workspace_from_path

        touch_workspace_from_path(png_dir)
        if srt_file:
            touch_workspace_from_path(srt_file)
    except ImportError:
        pass
    if preview_pane_width is not None and preview_pane_width >= 200:
        data["preview_pane_width"] = preview_pane_width
    if genspark_prompt_selector is not None:
        sel = genspark_prompt_selector.strip()
        if sel:
            data["genspark_prompt_selector"] = sel
        else:
            data.pop("genspark_prompt_selector", None)
    if image_guide is not None:
        g = image_guide.strip()
        if g:
            data["image_guide"] = g
        else:
            data.pop("image_guide", None)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
