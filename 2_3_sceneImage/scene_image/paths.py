# -*- coding: utf-8 -*-
"""기본 경로."""

from __future__ import annotations

from pathlib import Path

from wisdom_workspace import get_workspace_dir, resolve_module_output

MODULE = "2_3_sceneImage"
GENSPARK_AI_IMAGE_URL = "https://www.genspark.ai/ai_image"


def default_png_dir() -> Path:
    ws = get_workspace_dir()
    if ws is not None:
        return ws / "png"
    return resolve_module_output(MODULE) / "png"


def default_script_file() -> Path | None:
    ws = get_workspace_dir()
    if ws is not None:
        for name in ("scene_script.txt", "image_scenes.txt"):
            p = ws / name
            if p.is_file():
                return p
    out = resolve_module_output(MODULE)
    for name in ("scene_script.txt", "image_scenes.txt"):
        p = out / name
        if p.is_file():
            return p
    return None
