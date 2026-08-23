# -*- coding: utf-8 -*-
"""1_2_textToJson GUI 설정."""

from __future__ import annotations

import json
import importlib.util
import sys
from pathlib import Path

PROJECT_DIRNAME = "1_2_textToJson"
GUI_CONFIG_NAME = "text_to_json_gui_config.json"


def _ensure_wisdom_on_path(from_file: str | Path) -> None:
    if importlib.util.find_spec("wisdom_root") is not None:
        return
    candidates: list[Path] = [Path.cwd(), *Path(from_file).resolve().parents]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)
    seen: set[str] = set()
    for base in candidates:
        try:
            root = base.resolve()
        except OSError:
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        if (root / "wisdom_root.py").is_file():
            if key not in sys.path:
                sys.path.insert(0, key)
            return


_ensure_wisdom_on_path(__file__)
from wisdom_root import module_dir
from wisdom_workspace import (
    folder_dialog_initial,
    get_workspace_dir,
    resolve_module_output,
    touch_workspace_from_path,
)


def _frozen_exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def module_dist_dir() -> Path:
    return module_dir(PROJECT_DIRNAME) / "dist"


def default_root_dir() -> Path:
    ws = get_workspace_dir()
    if ws is not None:
        return ws
    return resolve_module_output(PROJECT_DIRNAME)


def gui_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return _frozen_exe_dir() / GUI_CONFIG_NAME
    d = module_dist_dir()
    d.mkdir(parents=True, exist_ok=True)
    return d / GUI_CONFIG_NAME


def load_gui_settings() -> dict[str, str]:
    p = gui_config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("root_dir", "txt_file", "md_file", "command", "email"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def save_gui_settings(
    *,
    root_dir: str = "",
    txt_file: str = "",
    md_file: str = "",
    command: str = "",
    email: str = "",
) -> None:
    if root_dir.strip():
        touch_workspace_from_path(root_dir)
    p = gui_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "root_dir": root_dir.strip(),
        "txt_file": txt_file.strip(),
        "md_file": md_file.strip(),
        "command": command.strip(),
        "email": email.strip(),
    }
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
