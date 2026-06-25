#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""wisdom 통합 허브 GUI (모든 파이프라인 탭)."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path


def main() -> None:
    wisdom = Path(__file__).resolve().parent
    if str(wisdom) not in sys.path:
        sys.path.insert(0, str(wisdom))
    from wisdom_bootstrap import run as wisdom_run

    wisdom_run(__file__)
    try:
        from wisdom_hub.gui_app import main as hub_main

        hub_main()
    except Exception:
        if getattr(sys, "frozen", False):
            try:
                import tkinter as tk
                from tkinter import messagebox

                from wisdom_gui_host import is_hub_shutting_down

                if not is_hub_shutting_down():
                    r = tk.Tk()
                    r.withdraw()
                    messagebox.showerror("wisdom 허브", traceback.format_exc())
                    r.destroy()
            except Exception:
                pass
        else:
            traceback.print_exc()
            raise


if __name__ == "__main__":
    main()
