# -*- coding: utf-8 -*-
"""모듈 md/ 폴더 txt 목록·클립보드 복사 GUI."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from md_file import __version__
from md_file.paths import default_scan_root
from md_file.scanner import read_text_file, scan_module_txt_files
from md_file.settings import load_gui_settings, save_gui_settings
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _resolve_initial_dir(saved: str | None) -> Path:
    if saved:
        p = Path(saved).expanduser()
        try:
            if p.is_dir():
                return p.resolve()
        except OSError:
            pass
    return default_scan_root()


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_hub_destroy,
        bind_path_entry_dnd,
        bind_path_row_dnd,
        run_mainloop,
        tk_host,
    )

    cfg = load_gui_settings()
    initial = _resolve_initial_dir(cfg.get("scan_dir"))

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"9_mdFile {__version__}",
        minsize=(720, 480),
        geometry="960x600",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    scan_var = tk.StringVar(value=str(initial))
    status_var = tk.StringVar(value="wisdom 루트 아래 각 모듈 md/ 폴더의 txt 파일을 표시합니다.")
    file_rows: list[Path] = []

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(2, weight=1)

    path_fr = ttk.Frame(frm)
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    path_fr.grid_columnconfigure(1, weight=1)
    ttk.Label(path_fr, text="wisdom 루트", width=10).grid(row=0, column=0, sticky="w")
    scan_ent = ttk.Entry(path_fr, textvariable=scan_var)
    scan_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6))

    def pick_dir() -> None:
        init = Path(scan_var.get().strip()) if scan_var.get().strip() else initial
        if not init.is_dir():
            init = initial
        p = filedialog.askdirectory(title="wisdom 루트", initialdir=folder_dialog_initial(init))
        if p:
            touch_workspace_from_path(p)
            scan_var.set(p)
            refresh_list()

    ttk.Button(path_fr, text="찾기…", command=pick_dir).grid(row=0, column=2, padx=(0, 6))
    bind_path_row_dnd(scan_ent, path_fr, scan_var, mode="dir", on_set=lambda _p: refresh_list())
    ttk.Button(path_fr, text="새로고침", command=lambda: refresh_list()).grid(row=0, column=3)

    cols = ("name", "path", "copy")
    tree = ttk.Treeview(frm, columns=cols, show="headings", selectmode="browse")
    tree.heading("name", text="파일명")
    tree.heading("path", text="파일 경로")
    tree.heading("copy", text="복사")
    tree.column("name", width=200, anchor="w", stretch=False)
    tree.column("path", width=520, anchor="w", stretch=True)
    tree.column("copy", width=72, anchor="center", stretch=False)
    ysb = ttk.Scrollbar(frm, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ysb.set)
    tree.grid(row=2, column=0, sticky="nsew")
    ysb.grid(row=2, column=1, sticky="ns")

    ttk.Label(frm, textvariable=status_var).grid(row=3, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def copy_file(path: Path) -> None:
        try:
            text = read_text_file(path)
        except OSError as e:
            messagebox.showerror("9_mdFile", str(e))
            return
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()
        status_var.set(f"클립보드 복사: {path.name} ({len(text):,}자)")

    def refresh_list() -> None:
        folder = Path(scan_var.get().strip() or ".")
        save_gui_settings(scan_dir=str(folder))
        for item in tree.get_children():
            tree.delete(item)
        file_rows.clear()
        if not folder.is_dir():
            status_var.set(f"폴더 없음: {folder}")
            return
        file_rows.extend(scan_module_txt_files(folder))
        for p in file_rows:
            tree.insert("", tk.END, values=(p.name, str(p), "복사"))
        status_var.set(
            f"{len(file_rows)}개 txt (모듈 md/ · .md 제외) · 「복사」 클릭 시 내용이 클립보드에 복사됩니다."
        )

    def on_tree_click(event: tk.Event) -> None:
        if tree.identify_region(event.x, event.y) != "cell":
            return
        if tree.identify_column(event.x) != "#3":
            return
        row_id = tree.identify_row(event.y)
        if not row_id:
            return
        idx = tree.index(row_id)
        if 0 <= idx < len(file_rows):
            copy_file(file_rows[idx])

    tree.bind("<ButtonRelease-1>", on_tree_click)

    def on_close() -> None:
        save_gui_settings(scan_dir=scan_var.get().strip())

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    refresh_list()
    run_mainloop(root, standalone)
