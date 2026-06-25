#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 진입점.

- ``dist/9_mdFile_gui.exe`` 가 있으면 우선 실행 (빌드 산출물).
- 소스 강제: 환경 변수 ``MD_FILE_GUI_SOURCE=1``
"""

from __future__ import annotations

import os
import subprocess
import sys
import traceback
from pathlib import Path


def _dist_gui_exe() -> Path:
    return Path(__file__).resolve().parent / "dist" / "9_mdFile_gui.exe"


def main() -> None:
    _WISDOM = Path(__file__).resolve().parent.parent
    if str(_WISDOM) not in sys.path:
        sys.path.insert(0, str(_WISDOM))
    from wisdom_bootstrap import run as wisdom_run

    work = wisdom_run(__file__)

    if getattr(sys, "frozen", False):
        try:
            from md_file.gui_app import main as gui_main

            gui_main()
        except Exception:
            _show_error_dialog()
            raise
        return

    exe = _dist_gui_exe()
    use_source = os.environ.get("MD_FILE_GUI_SOURCE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    if not use_source and exe.is_file():
        r = subprocess.run([str(exe)], cwd=str(work))
        raise SystemExit(r.returncode or 0)

    try:
        from md_file.gui_app import main as gui_main

        gui_main()
    except Exception:
        traceback.print_exc()
        raise


def _show_error_dialog() -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("9_mdFile", traceback.format_exc())
        r.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    main()
