# -*- coding: utf-8 -*-
"""wisdom 통합 허브 — 파이프라인 GUI 를 탭으로 한 창에 표시."""

from __future__ import annotations

import sys

import tkinter as tk
from tkinter import ttk

from wisdom_gui_host import configure_notebook_tabs, request_shutdown
from wisdom_hub.loaders import LOADERS
from wisdom_hub.pipeline import HUB_TABS


def main() -> None:
    root = tk.Tk()
    root.title("wisdom")
    root.minsize(1000, 640)
    root.geometry("1280x800")

    def on_hub_close() -> None:
        request_shutdown(root)
        try:
            root.quit()
        except tk.TclError:
            pass
        try:
            root.destroy()
        except tk.TclError:
            pass

    root.protocol("WM_DELETE_WINDOW", on_hub_close)

    configure_notebook_tabs(root)

    nb = ttk.Notebook(root)
    nb.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

    tab_frames: dict[str, tk.Frame] = {}
    loaded: set[str] = set()

    for title, module in HUB_TABS:
        fr = ttk.Frame(nb, padding=0)
        nb.add(fr, text=title)
        tab_frames[module] = fr

    def ensure_loaded(module: str) -> None:
        if module in loaded:
            return
        loaded.add(module)
        fr = tab_frames[module]
        try:
            LOADERS[module](fr)
        except Exception:
            loaded.discard(module)
            raise

    def on_tab_changed(_event: object | None = None) -> None:
        try:
            idx = nb.index(nb.select())
        except tk.TclError:
            return
        if 0 <= idx < len(HUB_TABS):
            mod = HUB_TABS[idx][1]
            if mod not in loaded:
                root.after_idle(lambda m=mod: ensure_loaded(m))

    nb.bind("<<NotebookTabChanged>>", on_tab_changed)
    ensure_loaded(HUB_TABS[0][1])
    try:
        root.mainloop()
    finally:
        sys.exit(0)


if __name__ == "__main__":
    main()
