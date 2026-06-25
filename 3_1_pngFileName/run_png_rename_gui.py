#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""3_1_pngFileName GUI 진입점."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import traceback
from pathlib import Path


def _dist_exe() -> Path:
    return Path(__file__).resolve().parent / "dist" / "3_1_pngFileName_gui.exe"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="3_1_pngFileName — SRT 매칭 PNG 이름 변경")
    p.add_argument("--srt", type=Path, default=None)
    p.add_argument("--png-dir", type=Path, default=None)
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
            from png_rename.gui_app import main as gui_main

            gui_main(initial_srt=args.srt, initial_png_dir=args.png_dir)
        except Exception:
            _show_error_dialog()
            raise
        return

    root = Path(__file__).resolve().parent
    exe = _dist_exe()
    use_source = os.environ.get("PNG_RENAME_GUI_SOURCE", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )
    forward: list[str] = []
    if args.srt is not None:
        forward.extend(["--srt", str(args.srt)])
    if args.png_dir is not None:
        forward.extend(["--png-dir", str(args.png_dir)])

    if not use_source and exe.is_file():
        r = subprocess.run([str(exe), *forward], cwd=str(work))
        raise SystemExit(r.returncode or 0)

    from png_rename.gui_app import main as gui_main

    try:
        gui_main(initial_srt=args.srt, initial_png_dir=args.png_dir)
    except Exception:
        traceback.print_exc()
        raise


def _show_error_dialog() -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox

        r = tk.Tk()
        r.withdraw()
        messagebox.showerror("3_1_pngFileName", traceback.format_exc())
        r.destroy()
    except Exception:
        pass


if __name__ == "__main__":
    main()
