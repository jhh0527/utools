# -*- coding: utf-8 -*-
"""C/S/T/U/X → W 반출, W → USB 복사 GUI (단독 실행)."""

from __future__ import annotations

import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from file_explorer import __version__
from file_explorer.copier import copy_items, count_copy_targets
from file_explorer.paths import (
    DEFAULT_DEST_DRIVE,
    SOURCE_DRIVES,
    available_source_drives,
    available_usb_drives,
    default_dest_dir,
    dest_on_export_drive,
    dest_on_usb_drive,
    drive_root,
    first_available_source,
    path_on_drive,
)
from file_explorer.settings import load_gui_settings, save_gui_settings
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _resolve_initial_dir(saved: str | None, fallback: Path) -> Path:
    if saved:
        p = Path(saved).expanduser().resolve()
        if p.is_dir():
            return p
    return fallback.resolve()


def _list_dir(path: Path) -> tuple[list[Path], list[Path]]:
    try:
        entries = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
    except OSError:
        return [], []
    dirs = [p for p in entries if p.is_dir()]
    files = [p for p in entries if p.is_file()]
    return dirs, files


def _fill_listbox(
    listbox: tk.Listbox,
    entries: list[tuple[str, Path]],
    path: Path,
) -> None:
    listbox.delete(0, tk.END)
    entries.clear()
    if not path.is_dir():
        return
    dirs, files = _list_dir(path)
    for d in dirs:
        label = f"[폴더] {d.name}"
        listbox.insert(tk.END, label)
        entries.append((label, d))
    for f in files:
        label = f.name
        listbox.insert(tk.END, label)
        entries.append((label, f))


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import apply_window_chrome, bind_close, run_mainloop, tk_host

    cfg = load_gui_settings()
    src_default = _resolve_initial_dir(cfg.get("source_dir"), first_available_source())
    dest_default = _resolve_initial_dir(cfg.get("dest_dir"), default_dest_dir())

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"8_fileExplorer {__version__}",
        minsize=(900, 620),
        geometry="1020x700",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    src_var = tk.StringVar(value=str(src_default))
    dest_var = tk.StringVar(value=str(dest_default))
    usb_dest_var = tk.StringVar(value="")
    recursive_var = tk.BooleanVar(value=True)
    overwrite_var = tk.BooleanVar(value=True)
    status_var = tk.StringVar(
        value="① 소스(C/S/T/U/X) → W 반출  ② W → USB 복사 — 각각 별도 버튼으로 실행하세요."
    )
    drive_status_var = tk.StringVar(value="")

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(3, weight=1)

    browse_widgets: list[tk.Widget] = []
    src_entries: list[tuple[str, Path]] = []
    dest_entries: list[tuple[str, Path]] = []

    def refresh_drive_status() -> None:
        avail = available_source_drives()
        w = drive_root(DEFAULT_DEST_DRIVE)
        w_txt = DEFAULT_DEST_DRIVE if w.exists() else f"{DEFAULT_DEST_DRIVE} (미연결)"
        usb = available_usb_drives()
        usb_txt = ", ".join(usb) if usb else "없음"
        if avail:
            drive_status_var.set(
                f"소스: {', '.join(avail)}  |  W: {w_txt}  |  USB: {usb_txt}"
            )
        else:
            drive_status_var.set(
                f"소스 드라이브 미연결  |  W: {w_txt}  |  USB: {usb_txt}"
            )
        if usb_target_row is not None:
            rebuild_usb_target_buttons()

    def refresh_src_list() -> None:
        _fill_listbox(src_listbox, src_entries, Path(src_var.get().strip()))

    def refresh_dest_list() -> None:
        _fill_listbox(dest_listbox, dest_entries, Path(dest_var.get().strip()))

    def set_source(path: Path) -> None:
        if path.is_dir():
            src_var.set(str(path.resolve()))
            refresh_src_list()

    def set_dest(path: Path) -> None:
        if path.is_dir():
            dest_var.set(str(path.resolve()))
            refresh_dest_list()

    def pick_source() -> None:
        initial = src_var.get().strip()
        init_dir = folder_dialog_initial(
            Path(initial) if initial and Path(initial).is_dir() else first_available_source(),
        )
        p = filedialog.askdirectory(title="소스 폴더", initialdir=init_dir)
        if p:
            touch_workspace_from_path(p)
            set_source(Path(p))

    def pick_dest() -> None:
        initial = dest_var.get().strip()
        init_dir = folder_dialog_initial(
            Path(initial) if initial and Path(initial).is_dir() else default_dest_dir(),
        )
        p = filedialog.askdirectory(title=f"대상 폴더 ({DEFAULT_DEST_DRIVE})", initialdir=init_dir)
        if p:
            path = Path(p)
            if not dest_on_export_drive(path):
                messagebox.showwarning(
                    "대상",
                    f"W 반출 대상은 {DEFAULT_DEST_DRIVE} 드라이브 아래 폴더만 선택할 수 있습니다.",
                )
                return
            touch_workspace_from_path(p)
            set_dest(path)

    def go_src_parent() -> None:
        cur = Path(src_var.get().strip())
        if cur.parent != cur:
            set_source(cur.parent)

    def go_dest_parent() -> None:
        cur = Path(dest_var.get().strip())
        if cur.parent != cur:
            set_dest(cur.parent)

    def go_dest_root() -> None:
        w = drive_root(DEFAULT_DEST_DRIVE)
        if w.exists():
            set_dest(w)
        else:
            messagebox.showwarning("드라이브", f"{DEFAULT_DEST_DRIVE} 드라이브가 연결되어 있지 않습니다.")

    def go_dest_usb(letter: str) -> None:
        root_path = drive_root(letter)
        if root_path.exists():
            usb_dest_var.set(str(root_path.resolve()))
        else:
            messagebox.showwarning("드라이브", f"{letter} 드라이브가 연결되어 있지 않습니다.")

    usb_target_row: ttk.Frame | None = None
    usb_target_btns: list[ttk.Button] = []

    def rebuild_usb_target_buttons() -> None:
        if usb_target_row is None:
            return
        for btn in usb_target_btns:
            if btn in browse_widgets:
                browse_widgets.remove(btn)
            btn.destroy()
        usb_target_btns.clear()
        for letter in available_usb_drives():
            btn = ttk.Button(
                usb_target_row,
                text=letter,
                width=4,
                command=lambda lp=letter: go_dest_usb(lp),
            )
            btn.pack(side=tk.LEFT, padx=(0, 4))
            usb_target_btns.append(btn)
            browse_widgets.append(btn)
        if not usb_dest_var.get().strip() and available_usb_drives():
            go_dest_usb(available_usb_drives()[0])

    # 소스 드라이브
    ttk.Label(frm, text="소스 드라이브 (C / S / T / U / X · W)").grid(row=0, column=0, sticky="w")
    drive_row = ttk.Frame(frm)
    drive_row.grid(row=1, column=0, sticky="w", pady=(0, 4))
    for letter in SOURCE_DRIVES:
        root_path = drive_root(letter)

        def make_drive_cmd(lp: Path = root_path) -> None:
            def cmd() -> None:
                if lp.exists():
                    set_source(lp)
                else:
                    messagebox.showwarning("드라이브", f"{lp} 드라이브가 연결되어 있지 않습니다.")

            return cmd

        btn = ttk.Button(drive_row, text=letter, width=4, command=make_drive_cmd())
        btn.pack(side=tk.LEFT, padx=(0, 4))
        browse_widgets.append(btn)

    w_src = drive_root(DEFAULT_DEST_DRIVE)

    def go_w_source() -> None:
        if w_src.exists():
            set_source(w_src)
        else:
            messagebox.showwarning("드라이브", f"{DEFAULT_DEST_DRIVE} 드라이브가 연결되어 있지 않습니다.")

    btn_w_src = ttk.Button(drive_row, text=f"{DEFAULT_DEST_DRIVE}*", width=5, command=go_w_source)
    btn_w_src.pack(side=tk.LEFT, padx=(8, 0))
    browse_widgets.append(btn_w_src)
    ttk.Label(frm, textvariable=drive_status_var).grid(row=2, column=0, sticky="w", pady=(0, 8))

    # 좌우 탐색기
    paned = ttk.PanedWindow(frm, orient=tk.HORIZONTAL)
    paned.grid(row=3, column=0, sticky="nsew", pady=(0, 8))

    src_pane = ttk.Frame(paned, padding=(0, 0, 4, 0))
    dest_pane = ttk.Frame(paned, padding=(4, 0, 0, 0))
    paned.add(src_pane, weight=1)
    paned.add(dest_pane, weight=1)
    src_pane.grid_columnconfigure(0, weight=1)
    src_pane.grid_rowconfigure(2, weight=1)
    dest_pane.grid_columnconfigure(0, weight=1)
    dest_pane.grid_rowconfigure(2, weight=1)

    ttk.Label(src_pane, text="소스 폴더").grid(row=0, column=0, sticky="w")
    src_row = ttk.Frame(src_pane)
    src_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    src_row.grid_columnconfigure(0, weight=1)
    src_ent = ttk.Entry(src_row, textvariable=src_var)
    src_ent.grid(row=0, column=0, sticky="ew", padx=(0, 4))
    btn_src_up = ttk.Button(src_row, text="상위", width=5, command=go_src_parent)
    btn_src_up.grid(row=0, column=1, padx=(0, 4))
    btn_src = ttk.Button(src_row, text="선택…", command=pick_source)
    btn_src.grid(row=0, column=2)
    browse_widgets.extend([src_ent, btn_src_up, btn_src])

    src_list_frm = ttk.Frame(src_pane)
    src_list_frm.grid(row=2, column=0, sticky="nsew")
    src_list_frm.grid_columnconfigure(0, weight=1)
    src_list_frm.grid_rowconfigure(0, weight=1)
    src_listbox = tk.Listbox(src_list_frm, selectmode=tk.EXTENDED, height=14)
    src_listbox.grid(row=0, column=0, sticky="nsew")
    src_scroll = ttk.Scrollbar(src_list_frm, orient=tk.VERTICAL, command=src_listbox.yview)
    src_scroll.grid(row=0, column=1, sticky="ns")
    src_listbox.configure(yscrollcommand=src_scroll.set)

    def on_src_double(_event: tk.Event) -> None:
        sel = src_listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(src_entries):
            _label, path = src_entries[idx]
            if path.is_dir():
                set_source(path)

    src_listbox.bind("<Double-Button-1>", on_src_double)

    ttk.Label(
        dest_pane,
        text=f"대상 폴더 ({DEFAULT_DEST_DRIVE} 반출 결과 확인)",
    ).grid(
        row=0, column=0, sticky="w"
    )
    dest_row = ttk.Frame(dest_pane)
    dest_row.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    dest_row.grid_columnconfigure(1, weight=1)
    btn_w = ttk.Button(dest_row, text=DEFAULT_DEST_DRIVE, width=4, command=go_dest_root)
    btn_w.grid(row=0, column=0, padx=(0, 4))
    dest_ent = ttk.Entry(dest_row, textvariable=dest_var)
    dest_ent.grid(row=0, column=1, sticky="ew", padx=(0, 4))
    btn_dest_up = ttk.Button(dest_row, text="상위", width=5, command=go_dest_parent)
    btn_dest_up.grid(row=0, column=2, padx=(0, 4))
    btn_dest = ttk.Button(dest_row, text="선택…", command=pick_dest)
    btn_dest.grid(row=0, column=3)
    browse_widgets.extend([btn_w, dest_ent, btn_dest_up, btn_dest])

    dest_list_frm = ttk.Frame(dest_pane)
    dest_list_frm.grid(row=2, column=0, sticky="nsew")
    dest_list_frm.grid_columnconfigure(0, weight=1)
    dest_list_frm.grid_rowconfigure(0, weight=1)
    dest_listbox = tk.Listbox(dest_list_frm, selectmode=tk.BROWSE, height=14)
    dest_listbox.grid(row=0, column=0, sticky="nsew")
    dest_scroll = ttk.Scrollbar(dest_list_frm, orient=tk.VERTICAL, command=dest_listbox.yview)
    dest_scroll.grid(row=0, column=1, sticky="ns")
    dest_listbox.configure(yscrollcommand=dest_scroll.set)

    def on_dest_double(_event: tk.Event) -> None:
        sel = dest_listbox.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if 0 <= idx < len(dest_entries):
            _label, path = dest_entries[idx]
            if path.is_dir():
                set_dest(path)

    dest_listbox.bind("<Double-Button-1>", on_dest_double)

    opts = ttk.Frame(frm)
    opts.grid(row=4, column=0, sticky="w", pady=(0, 6))
    ttk.Checkbutton(opts, text="하위 폴더 포함", variable=recursive_var).pack(side=tk.LEFT)
    ttk.Checkbutton(opts, text="기존 파일 덮어쓰기", variable=overwrite_var).pack(side=tk.LEFT, padx=(12, 0))

    prog = ttk.Progressbar(frm, mode="determinate", maximum=100)
    prog.grid(row=5, column=0, sticky="ew", pady=(4, 4))
    ttk.Label(frm, textvariable=status_var).grid(row=6, column=0, sticky="w")

    log = tk.Text(frm, height=5, wrap=tk.WORD, state=tk.DISABLED)
    log.grid(row=7, column=0, sticky="ew", pady=(6, 0))

    def log_line(msg: str) -> None:
        log.configure(state=tk.NORMAL)
        log.insert(tk.END, msg + "\n")
        log.see(tk.END)
        log.configure(state=tk.DISABLED)

    btn_copy_w: ttk.Button
    btn_copy_usb: ttk.Button

    def set_busy(on: bool) -> None:
        state = tk.DISABLED if on else tk.NORMAL
        btn_copy_w.configure(state=state)
        btn_copy_usb.configure(state=state)
        for w in browse_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass
        src_listbox.configure(state=state)
        dest_listbox.configure(state=tk.DISABLED if on else tk.NORMAL)

    def persist_paths() -> None:
        try:
            save_gui_settings(
                source_dir=src_var.get().strip(),
                dest_dir=dest_var.get().strip(),
            )
        except OSError:
            pass

    def selected_paths() -> list[Path]:
        sel = src_listbox.curselection()
        if not sel:
            return []
        out: list[Path] = []
        for i in sel:
            if 0 <= i < len(src_entries):
                out.append(src_entries[i][1])
        return out

    def run_copy_to_w() -> None:
        sources = selected_paths()
        if not sources:
            messagebox.showwarning("선택", "왼쪽 목록에서 복사할 파일·폴더를 선택하세요.")
            return
        if not dest_var.get().strip():
            messagebox.showwarning("대상", "오른쪽에서 W 반출 대상 폴더를 지정하세요.")
            return
        dest = Path(dest_var.get().strip())
        if not dest_on_export_drive(dest):
            messagebox.showwarning(
                "대상",
                f"W 반출은 {DEFAULT_DEST_DRIVE} 드라이브를 대상으로 지정하세요.",
            )
            return
        _run_copy(sources, dest, target_label=DEFAULT_DEST_DRIVE)

    def run_copy_w_to_usb() -> None:
        w_root = drive_root(DEFAULT_DEST_DRIVE)
        if not w_root.exists():
            messagebox.showwarning("드라이브", f"{DEFAULT_DEST_DRIVE} 드라이브가 연결되어 있지 않습니다.")
            return
        sources = selected_paths()
        if not sources:
            messagebox.showwarning("선택", "W 드라이브에서 복사할 파일·폴더를 선택하세요.")
            return
        off_w = [p for p in sources if not path_on_drive(p, DEFAULT_DEST_DRIVE)]
        if off_w:
            messagebox.showwarning(
                "소스",
                f"USB 복사는 {DEFAULT_DEST_DRIVE} 드라이브의 파일·폴더만 선택할 수 있습니다.\n"
                f"상단 {DEFAULT_DEST_DRIVE}* 버튼으로 W 드라이브를 여세요.",
            )
            return
        usb_txt = usb_dest_var.get().strip()
        if not usb_txt:
            usbs = available_usb_drives()
            if not usbs:
                messagebox.showwarning("USB", "USB 드라이브가 연결되어 있지 않습니다.")
                return
            go_dest_usb(usbs[0])
            usb_txt = usb_dest_var.get().strip()
        dest = Path(usb_txt)
        if not dest_on_usb_drive(dest):
            messagebox.showwarning(
                "대상",
                "USB 복사 대상을 USB 드라이브로 지정하세요.\n"
                "아래 USB 버튼을 누르세요.",
            )
            return
        _run_copy(sources, dest, target_label="USB")

    def _run_copy(sources: list[Path], dest: Path, *, target_label: str) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        persist_paths()

        def work() -> None:
            err: Exception | None = None
            file_ok = 0
            errors: list[str] = []
            recursive = bool(recursive_var.get())
            total_steps = max(count_copy_targets(sources, dest, recursive=recursive), 1)

            def on_prog(i: int, _total: int, item) -> None:
                pct = int(100 * i / total_steps)

                def ui() -> None:
                    prog.configure(value=pct)
                    status_var.set(
                        f"복사 중… {pct}% ({i}/{total_steps}) — "
                        f"[{target_label}] {item.source.name}"
                    )

                root.after(0, ui)

            try:
                file_ok, errors = copy_items(
                    sources,
                    dest,
                    recursive=recursive,
                    overwrite=bool(overwrite_var.get()),
                    on_progress=on_prog,
                )
            except Exception as e:
                err = e
                traceback.print_exc()

            def done() -> None:
                set_busy(False)
                prog.configure(value=100 if not err else 0)
                refresh_drive_status()
                refresh_dest_list()
                if err:
                    messagebox.showerror("오류", str(err))
                    status_var.set("오류")
                    return
                for msg in errors:
                    log_line(msg)
                status_var.set(f"완료: {file_ok}개 파일 → {dest.resolve()}")
                if errors:
                    messagebox.showwarning(
                        "완료 (일부 오류)",
                        f"{file_ok}개 파일 → {dest.resolve()}\n"
                        f"오류 {len(errors)}건 — 로그를 확인하세요.",
                    )
                else:
                    hint = (
                        "USB 복사가 완료되었습니다."
                        if target_label == "USB"
                        else "오른쪽 목록에서 W 반출 결과를 확인하세요."
                    )
                    messagebox.showinfo(
                        "완료",
                        f"{file_ok}개 파일 → {dest.resolve()}\n{hint}",
                    )

            root.after(0, done)

        set_busy(True)
        prog.configure(value=0)
        log.configure(state=tk.NORMAL)
        log.delete("1.0", tk.END)
        log.configure(state=tk.DISABLED)
        status_var.set(f"{target_label} 복사 시작… 선택 {len(sources)}개 항목")
        threading.Thread(target=work, daemon=True).start()

    row_btns = ttk.Frame(frm)
    row_btns.grid(row=8, column=0, sticky="ew", pady=(8, 0))
    btn_copy_w = ttk.Button(
        row_btns,
        text=f"① 소스 → {DEFAULT_DEST_DRIVE} 반출",
        command=run_copy_to_w,
    )
    btn_copy_w.pack(side=tk.LEFT)
    btn_copy_usb = ttk.Button(
        row_btns,
        text="② W → USB 복사",
        command=run_copy_w_to_usb,
    )
    btn_copy_usb.pack(side=tk.LEFT, padx=(8, 0))

    usb_row = ttk.Frame(frm)
    usb_row.grid(row=9, column=0, sticky="w", pady=(6, 0))
    ttk.Label(usb_row, text="USB 대상:").pack(side=tk.LEFT)
    usb_ent = ttk.Entry(usb_row, textvariable=usb_dest_var, width=48)
    usb_ent.pack(side=tk.LEFT, padx=(6, 6))
    usb_target_row = ttk.Frame(usb_row)
    usb_target_row.pack(side=tk.LEFT)
    browse_widgets.append(usb_ent)
    rebuild_usb_target_buttons()

    row_tools = ttk.Frame(frm)
    row_tools.grid(row=10, column=0, sticky="ew", pady=(6, 0))
    ttk.Button(row_tools, text="소스 새로고침", command=refresh_src_list).pack(side=tk.LEFT)
    ttk.Button(row_tools, text="W 대상 새로고침", command=refresh_dest_list).pack(side=tk.LEFT, padx=(8, 0))

    def on_close() -> None:
        persist_paths()

    bind_close(root, standalone, on_close)
    refresh_drive_status()
    refresh_src_list()
    refresh_dest_list()
    run_mainloop(root, standalone)
