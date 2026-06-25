# -*- coding: utf-8 -*-
"""PNG → SRT_XXX.jpg 변환 GUI."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable
import threading
import tkinter as tk
import traceback
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from png2jpg import __version__
from png2jpg.converter import (
    ConvertResult,
    ConvertSkip,
    convert_images,
    DEFAULT_JPEG_QUALITY,
    iter_source_images,
)
from png2jpg.paths import default_input_dir, default_output_dir
from png2jpg.settings import load_gui_settings, save_gui_settings
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _resolve_initial_dir(
    cli: Path | None,
    saved: str | None,
    fallback: Path,
) -> Path:
    if cli is not None:
        p = cli.expanduser().resolve()
        if p.is_dir():
            return p
    if saved:
        p = Path(saved).expanduser().resolve()
        if p.is_dir():
            return p
    return fallback.resolve()


def _count_targets(folder: Path, *, recursive: bool, include_jpg: bool) -> tuple[int, list[Path]]:
    try:
        files = iter_source_images(folder, recursive=recursive, include_jpg=include_jpg)
    except OSError:
        return 0, []
    return len(files), files


def main(
    *,
    container: tk.Misc | None = None,
    initial_input: Path | None = None,
    initial_output: Path | None = None,
) -> None:
    from wisdom_gui_host import apply_window_chrome, bind_close, run_mainloop, tk_host
    if initial_input is None and initial_output is None and len(sys.argv) > 1:
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("-i", "--input", type=Path, default=None)
        p.add_argument("-o", "--output", type=Path, default=None)
        ns, _ = p.parse_known_args()
        initial_input = ns.input
        initial_output = ns.output

    cfg = load_gui_settings()
    in_default = _resolve_initial_dir(
        initial_input,
        cfg.get("input_dir"),
        default_input_dir(),
    )
    out_default = _resolve_initial_dir(
        initial_output,
        cfg.get("output_dir"),
        default_output_dir(),
    )
    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"3_2_pngToJpg {__version__}",
        minsize=(680, 520),
        geometry="800x560",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    in_var = tk.StringVar(value=str(in_default))
    out_var = tk.StringVar(value=str(out_default))
    recursive_var = tk.BooleanVar(value=True)
    include_jpg_var = tk.BooleanVar(value=False)
    quality_var = tk.IntVar(value=DEFAULT_JPEG_QUALITY)
    target_count_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="변환 대상 폴더를 지정한 뒤 변환을 실행하세요.")

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)

    browse_widgets: list[tk.Widget] = []

    def row_dir(
        label: str,
        var: tk.StringVar,
        row: int,
        *,
        on_pick: Callable[[], None] | None = None,
    ) -> None:
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
        rf = ttk.Frame(frm)
        rf.grid(row=row + 1, column=0, sticky="ew", pady=(0, 10))
        rf.grid_columnconfigure(0, weight=1)
        ent = ttk.Entry(rf, textvariable=var)
        ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        def pick() -> None:
            initial = var.get().strip()
            init_dir = folder_dialog_initial(
                Path(initial) if initial and Path(initial).is_dir() else default_input_dir(),
            )
            p = filedialog.askdirectory(title=label, initialdir=init_dir)
            if p:
                touch_workspace_from_path(p)
                if on_pick:
                    on_pick()
                else:
                    var.set(p)

        btn = ttk.Button(rf, text="폴더 선택…", command=pick)
        btn.grid(row=0, column=1)
        browse_widgets.extend([ent, btn])

    def refresh_target_count() -> None:
        inp = Path(in_var.get().strip())
        if not inp.is_dir():
            target_count_var.set("(폴더 없음)")
            return
        n, _ = _count_targets(
            inp,
            recursive=bool(recursive_var.get()),
            include_jpg=bool(include_jpg_var.get()),
        )
        sub = "하위 포함" if recursive_var.get() else "현재 폴더만"
        target_count_var.set(f"PNG/JPG {n}개 ({sub})")

    def on_input_changed() -> None:
        refresh_target_count()

    def sync_paths_from_content_root() -> None:
        try:
            from wisdom_content_paths import default_jpg_dir, default_png_dir

            png = default_png_dir()
            jpg = default_jpg_dir()
            if png is not None:
                in_var.set(str(png))
            if jpg is not None:
                out_var.set(str(jpg))
        except ImportError:
            pass
        refresh_target_count()

    row_dir("변환 대상 폴더 (PNG·JPG)", in_var, 0, on_pick=sync_paths_from_content_root)
    row_dir("저장 폴더 (SRT_XXX.jpg)", out_var, 2)

    ttk.Label(
        frm,
        text="파일명 규칙: SRT_000, srt_00, SRT_042, 00_제목.png 등 → SRT_XXX.jpg (번호=시작초, 0부터, 최대 1920×1080)",
    ).grid(row=4, column=0, sticky="w", pady=(0, 10))

    frm.grid_columnconfigure(0, weight=1)

    row_target = ttk.Frame(frm)
    row_target.grid(row=5, column=0, sticky="ew", pady=(0, 8))
    ttk.Label(row_target, text="대상 파일:").pack(side=tk.LEFT)
    ttk.Label(row_target, textvariable=target_count_var).pack(side=tk.LEFT, padx=(6, 12))
    btn_scan = ttk.Button(row_target, text="대상 다시 확인", command=refresh_target_count)
    btn_scan.pack(side=tk.LEFT)
    browse_widgets.append(btn_scan)

    opts = ttk.Frame(frm)
    opts.grid(row=6, column=0, sticky="ew", pady=(0, 8))

    def on_opt_change() -> None:
        refresh_target_count()

    ttk.Checkbutton(
        opts, text="하위 폴더 포함", variable=recursive_var, command=on_opt_change
    ).pack(side=tk.LEFT)
    ttk.Checkbutton(
        opts,
        text="JPG 도 SRT 형식으로 재저장",
        variable=include_jpg_var,
        command=on_opt_change,
    ).pack(side=tk.LEFT, padx=(12, 0))
    ttk.Label(opts, text="JPEG 품질").pack(side=tk.LEFT, padx=(16, 4))
    ttk.Scale(opts, from_=60, to=95, orient=tk.HORIZONTAL, variable=quality_var, length=140).pack(
        side=tk.LEFT
    )
    ttk.Label(opts, textvariable=quality_var, width=3).pack(side=tk.LEFT, padx=(4, 0))

    prog = ttk.Progressbar(frm, mode="determinate", maximum=100)
    prog.grid(row=7, column=0, sticky="ew", pady=(4, 4))
    ttk.Label(frm, textvariable=status_var).grid(row=8, column=0, sticky="w")

    log = tk.Text(frm, height=10, wrap=tk.WORD, state=tk.DISABLED)
    log.grid(row=9, column=0, sticky="nsew", pady=(8, 0))
    frm.grid_rowconfigure(9, weight=1)

    def log_line(msg: str) -> None:
        log.configure(state=tk.NORMAL)
        log.insert(tk.END, msg + "\n")
        log.see(tk.END)
        log.configure(state=tk.DISABLED)

    btn_run: ttk.Button

    def set_busy(on: bool) -> None:
        state = tk.DISABLED if on else tk.NORMAL
        btn_run.configure(state=state)
        for w in browse_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

    def persist_dirs() -> None:
        try:
            save_gui_settings(
                input_dir=in_var.get().strip(),
                output_dir=out_var.get().strip(),
            )
        except OSError:
            pass

    def run_convert() -> None:
        inp = Path(in_var.get().strip())
        out = Path(out_var.get().strip())
        if not inp.is_dir():
            messagebox.showerror("변환 대상", f"폴더가 없습니다:\n{inp}")
            return
        if not out_var.get().strip():
            messagebox.showwarning("저장 폴더", "저장 폴더를 지정하세요.")
            return
        out.mkdir(parents=True, exist_ok=True)
        q = max(60, min(95, int(quality_var.get())))
        persist_dirs()

        n_pre, _ = _count_targets(
            inp,
            recursive=bool(recursive_var.get()),
            include_jpg=bool(include_jpg_var.get()),
        )
        if n_pre == 0:
            messagebox.showwarning(
                "변환 대상",
                f"변환할 PNG/JPG 가 없습니다.\n\n대상: {inp.resolve()}",
            )
            return
        def work() -> None:
            err: Exception | None = None
            results: list[ConvertResult] = []
            skipped: list[ConvertSkip] = []

            def on_prog(i: int, total: int, item: ConvertResult | ConvertSkip) -> None:
                pct = 0 if total <= 0 else int(100 * i / total)

                def ui() -> None:
                    prog.configure(value=pct)
                    if isinstance(item, ConvertResult):
                        saved = item.saved_bytes
                        status_var.set(
                            f"변환 중… {pct}% ({i}/{total}) — {item.output.name} "
                            f"({item.size_px[0]}×{item.size_px[1]}, -{saved // 1024}KB)"
                        )
                        note = f" · {item.match_note}" if item.match_note else ""
                        log_line(
                            f"[{item.output.name}] ← {item.source.name}{note} "
                            f"({item.bytes_before // 1024}KB → {item.bytes_after // 1024}KB)"
                        )
                    else:
                        log_line(f"건너뜀: {item.source.name} — {item.reason}")

                root.after(0, ui)

            try:
                results, skipped = convert_images(
                    inp,
                    out,
                    recursive=bool(recursive_var.get()),
                    include_jpg=bool(include_jpg_var.get()),
                    quality=q,
                    on_progress=on_prog,
                )
            except Exception as e:
                err = e
                traceback.print_exc()

            def done() -> None:
                set_busy(False)
                prog.configure(value=100 if not err else 0)
                refresh_target_count()
                if err:
                    messagebox.showerror("오류", str(err))
                    status_var.set("오류")
                    return
                total_saved = sum(r.saved_bytes for r in results)
                status_var.set(
                    f"완료: {len(results)}개 저장, 건너뜀 {len(skipped)}개 "
                    f"(절약 {total_saved // 1024}KB) → {out.resolve()}"
                )
                messagebox.showinfo(
                    "완료",
                    f"{len(results)}개 → {out.resolve()}\n"
                    f"건너뜀: {len(skipped)}개\n"
                    f"용량 절약: 약 {total_saved // 1024} KB",
                )

            root.after(0, done)

        set_busy(True)
        prog.configure(value=0)
        log.configure(state=tk.NORMAL)
        log.delete("1.0", tk.END)
        log.configure(state=tk.DISABLED)
        status_var.set(f"변환 시작… 대상 {n_pre}개 파일")
        threading.Thread(target=work, daemon=True).start()

    row_btns = ttk.Frame(frm)
    row_btns.grid(row=10, column=0, sticky="ew", pady=(8, 0))
    btn_run = ttk.Button(row_btns, text="PNG → SRT_XXX.jpg 변환", command=run_convert)
    btn_run.pack(side=tk.LEFT)

    def on_close() -> None:
        persist_dirs()

    bind_close(root, standalone, on_close)
    refresh_target_count()
    run_mainloop(root, standalone)
