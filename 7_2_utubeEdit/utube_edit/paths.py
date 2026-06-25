"""7_2_utubeEdit 경로."""

from __future__ import annotations

import sys
from pathlib import Path


def _ensure_wisdom_on_path() -> None:
    for base in [Path.cwd(), *Path(__file__).resolve().parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            return


def wisdom_repo_root() -> Path:
    _ensure_wisdom_on_path()
    from wisdom_root import resolve_wisdom_root

    return resolve_wisdom_root()


def module_root() -> Path:
    _ensure_wisdom_on_path()
    from wisdom_root import module_dir

    mod = module_dir("7_2_utubeEdit")
    if mod.is_dir():
        return mod
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve().parent
        if exe.name == "dist" and exe.parent.name == "7_2_utubeEdit":
            return exe.parent
        return exe
    return Path(__file__).resolve().parents[1]


def default_output_dir() -> Path:
    _ensure_wisdom_on_path()
    from wisdom_workspace import resolve_module_output

    return resolve_module_output("7_2_utubeEdit")
