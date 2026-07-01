# -*- coding: utf-8 -*-
"""허브 탭별 GUI 로드 (지연 import)."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path
from typing import Callable

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from wisdom_hub.pipeline import HUB_TABS
from wisdom_root import module_dir


def _ensure_module_path(module: str) -> Path:
    d = module_dir(module)
    s = str(d)
    if s not in sys.path:
        sys.path.insert(0, s)
    return d


def _show_load_error(container: tk.Misc, module: str, tb: str) -> None:
    for w in container.winfo_children():
        w.destroy()
    fr = ttk.Frame(container, padding=12)
    fr.pack(fill=tk.BOTH, expand=True)
    ttk.Label(fr, text=f"{module} GUI 로드 실패", font=("", 11, "bold")).pack(anchor=tk.W)
    txt = scrolledtext.ScrolledText(fr, height=16, wrap=tk.WORD)
    txt.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
    txt.insert("1.0", tb)
    txt.configure(state=tk.DISABLED)


def load_tab_ui(module: str, container: tk.Misc) -> None:
    """모듈 GUI 를 ``container``(탭 Frame) 안에 구성합니다."""
    if getattr(container, "_wisdom_tab_module", None) == module:
        return
    _ensure_module_path(module)
    try:
        if module == "1_1_textTo700Text":
            import manuscript_700_splitter as m

            m.run_gui(container=container)
        elif module == "2_1_ttsToVoice":
            from elsub.gui_app import main

            main(container=container)
        elif module == "2_2_srtToImage":
            from prompt2image.gui_app import main

            main(container=container)
        elif module == "2_3_stt":
            from stt.gui_app import main

            main(container=container)
        elif module == "2_4_imageToMp4":
            from image_to_mp4.gui_app import main

            main(container=container)
        elif module == "3_1_pngFileName":
            from png_rename.gui_app import main

            main(container=container)
        elif module == "3_2_pngToJpg":
            from png2jpg.gui_app import main

            main(container=container)
        elif module == "4_1_video":
            from scenevid.gui_app import main

            main(container=container)
        elif module == "4_2_ShortVideo":
            from shortvid.gui_app import main

            main(container=container)
        elif module == "6_thumbnail":
            from thumbnail_gui.app import main

            main(container=container)
        elif module == "7_utube":
            from utube.gui_app import main

            main(container=container)
        elif module == "7_2_mp4Edit":
            from mp4_edit.gui_app import main

            main(container=container)
        elif module == "7_3_mp4Search":
            from mp4_search.gui_app import main

            main(container=container)
        elif module == "9_mdFile":
            from md_file.gui_app import main

            main(container=container)
        else:
            raise ValueError(f"알 수 없는 모듈: {module}")
        setattr(container, "_wisdom_tab_module", module)
    except Exception:
        _show_load_error(container, module, traceback.format_exc())


def tab_loader(module: str) -> Callable[[tk.Misc], None]:
    return lambda c, m=module: load_tab_ui(m, c)


LOADERS: dict[str, Callable[[tk.Misc], None]] = {
    mod: tab_loader(mod) for _title, mod in HUB_TABS
}
