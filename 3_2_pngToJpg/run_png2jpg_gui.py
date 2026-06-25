#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""GUI 진입점.

- ``dist/3_2_pngToJpg_gui.exe`` 가 있으면 우선 실행 (빌드 산출물).
- 변환 대상 폴더: ``-i`` / ``--input``, 출력: ``-o`` / ``--output``
- 소스 강제: 환경 변수 ``PNG2JPG_GUI_SOURCE=1``

예:
  python run_png2jpg_gui.py -i "D:\\images\\png"
  python run_png2jpg_gui.py --input ..\\2_2_srtToImage\\output\\old -o output
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
from pathlib import Path


def _dist_gui_exe() -> Path:
    return Path(__file__).resolve().parent / "dist" / "3_2_pngToJpg_gui.exe"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="3_2_pngToJpg GUI - PNG to SRT_XXX.jpg")
    p.add_argument("-i", "--input", type=Path, default=None, help="변환 대상 폴더 (PNG)")
    p.add_argument("-o", "--output", type=Path, default=None, help="저장 폴더 (SRT_XXX.jpg)")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    _WISDOM = Path(__file__).resolve().parent.parent
    if str(_WISDOM) not in sys.path:
        sys.path.insert(0, str(_WISDOM))
    from wisdom_bootstrap import run as wisdom_run

    work = wisdom_run(__file__)
    args = _parse_args(argv)

    if getattr(sys, "frozen", False):
        try:
            from png2jpg.gui_app import main as gui_main

            gui_main(initial_input=args.input, initial_output=args.output)
        except Exception:
            _show_error_dialog()
            raise
        return

    root = Path(__file__).resolve().parent
    exe = _dist_gui_exe()
    use_source = os.environ.get("PNG2JPG_GUI_SOURCE", "").strip().lower() in ("1", "true", "yes", "on")

    forward: list[str] = []
    if args.input is not None:
        forward.extend(["--input", str(args.input)])
    if args.output is not None:
        forward.extend(["--output", str(args.output)])

    if not use_source and exe.is_file():
        r = subprocess.run([str(exe), *forward], cwd=str(work))
        raise SystemExit(r.returncode or 0)

    try:
        from png2jpg.gui_app import main as gui_main

        gui_main(initial_input=args.input, initial_output=args.output)
    except Exception:
        traceback.print_exc()
        raise


def _show_error_dialog() -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("3_2_pngToJpg", traceback.format_exc())
        r.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    main()
