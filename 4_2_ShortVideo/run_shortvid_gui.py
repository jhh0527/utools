#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""4_2_ShortVideo GUI 진입점 — ``dist/4_2_shortvideo_gui.exe`` 우선."""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path


def _wisdom_workdir() -> Path:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    from wisdom_bootstrap import run as wisdom_run

    return wisdom_run(__file__)


def _dist_gui_exe() -> Path:
    return Path(__file__).resolve().parent / "dist" / "4_2_shortvideo_gui.exe"


def main() -> None:
    work = _wisdom_workdir()
    if getattr(sys, "frozen", False):
        try:
            from shortvid.gui_app import main as gui_main

            gui_main()
        except Exception:
            try:
                import tkinter as tk
                from tkinter import messagebox

                r = tk.Tk()
                r.withdraw()
                messagebox.showerror("4_2_ShortVideo", traceback.format_exc())
                r.destroy()
            except Exception:
                pass
            raise
        return

    exe = _dist_gui_exe()
    use_source = os.environ.get("SHORTVID_GUI_SOURCE", "").strip() in ("1", "true", "yes", "on")

    if not use_source and exe.is_file():
        r = subprocess.run([str(exe), *sys.argv[1:]], cwd=str(work))
        raise SystemExit(r.returncode or 0)

    try:
        from shortvid.gui_app import main as gui_main

        gui_main()
    except Exception:
        traceback.print_exc()
        raise


if __name__ == "__main__":
    main()
