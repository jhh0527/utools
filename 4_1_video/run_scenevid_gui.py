#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 진입점.

기본: ``dist/4_1_video_gui.exe`` 가 있으면 그 실행 파일을 띄웁니다 (빌드 산출물).
없으면: 소스 트리에서 ``scenevid.gui_app`` 을 직접 실행합니다.

소스 실행을 강제하려면 환경 변수 ``SCENEVID_GUI_SOURCE=1`` 을 설정하세요.
"""

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
    return Path(__file__).resolve().parent / "dist" / "4_1_video_gui.exe"


def main() -> None:
    work = _wisdom_workdir()
    # PyInstaller 단일 exe로 실행 중이면 여기서 바로 GUI 로드 (dist 재실행 금지).
    if getattr(sys, "frozen", False):
        try:
            from scenevid.gui_app import main as gui_main

            gui_main()
        except Exception:
            try:
                import tkinter as tk
                from tkinter import messagebox

                r = tk.Tk()
                r.withdraw()
                messagebox.showerror("4_1_video GUI", traceback.format_exc())
                r.destroy()
            except Exception:
                pass
            raise
        return

    root = Path(__file__).resolve().parent
    exe = _dist_gui_exe()
    use_source = os.environ.get("SCENEVID_GUI_SOURCE", "").strip() in ("1", "true", "yes", "on")

    if not use_source and exe.is_file():
        r = subprocess.run(
            [str(exe), *sys.argv[1:]],
            cwd=str(work),
        )
        raise SystemExit(r.returncode or 0)

    try:
        from scenevid.gui_app import main as gui_main

        gui_main()
    except Exception:
        if getattr(sys, "frozen", False):
            try:
                import tkinter as tk
                from tkinter import messagebox

                r = tk.Tk()
                r.withdraw()
                messagebox.showerror("4_1_video GUI", traceback.format_exc())
                r.destroy()
            except Exception:
                pass
        else:
            traceback.print_exc()
            raise


if __name__ == "__main__":
    main()
