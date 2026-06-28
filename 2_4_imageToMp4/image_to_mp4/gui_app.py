# -*- coding: utf-8 -*-
"""2_4_imageToMp4 GUI — ComfyUI AnimateDiff."""

from __future__ import annotations

import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from image_to_mp4 import __version__
from image_to_mp4.comfyui_client import probe_server
from image_to_mp4.generator import run_batch
from image_to_mp4.paths import default_input_dir, default_output_dir, describe_input_folder, list_input_images
from image_to_mp4.settings import load_gui_settings, save_gui_settings
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _int_field(val: str, default: int) -> int:
    try:
        return int(val.strip())
    except (TypeError, ValueError):
        return default


def _float_field(val: str, default: float) -> float:
    try:
        return float(val.strip())
    except (TypeError, ValueError):
        return default


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_hub_destroy,
        bind_path_entry_dnd,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
    )

    cfg = load_gui_settings()
    root, standalone = tk_host(container)

    if not standalone and getattr(root, "_image_to_mp4_gui_built", False):
        return
    if not standalone:
        setattr(root, "_image_to_mp4_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_4 imageToMp4 {__version__}",
        minsize=(900, 680),
        geometry="1020x780",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    url_var = tk.StringVar(value=cfg.get("comfyui_url", "http://127.0.0.1:8188"))
    input_var = tk.StringVar(value=cfg.get("input_dir") or str(default_input_dir()))
    output_var = tk.StringVar(value=cfg.get("output_dir") or str(default_output_dir()))
    positive_var = tk.StringVar(value=cfg.get("positive_prompt", ""))
    negative_var = tk.StringVar(value=cfg.get("negative_prompt", ""))
    checkpoint_var = tk.StringVar(value=cfg.get("checkpoint", ""))
    motion_var = tk.StringVar(value=cfg.get("motion_module", ""))
    workflow_var = tk.StringVar(value=cfg.get("workflow_path", ""))
    frames_var = tk.StringVar(value=cfg.get("frames", "16"))
    fps_var = tk.StringVar(value=cfg.get("fps", "8"))
    seed_var = tk.StringVar(value=cfg.get("seed", "-1"))
    steps_var = tk.StringVar(value=cfg.get("steps", "20"))
    cfg_var = tk.StringVar(value=cfg.get("cfg", "7.0"))
    denoise_var = tk.StringVar(value=cfg.get("denoise", "0.6"))
    subfolder_var = tk.BooleanVar(value=cfg.get("include_subfolders", "0") in ("1", "true", "yes", "on"))
    status_var = tk.StringVar(
        value="ComfyUI(AnimateDiff) 서버를 켠 뒤 입력 PNG 폴더를 선택하고 「MP4 생성」을 누르세요."
    )
    busy = {"v": False}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(1, weight=1)

    def persist() -> None:
        save_gui_settings(
            comfyui_url=url_var.get().strip(),
            input_dir=input_var.get().strip(),
            output_dir=output_var.get().strip(),
            positive_prompt=positive_var.get().strip(),
            negative_prompt=negative_var.get().strip(),
            checkpoint=checkpoint_var.get().strip(),
            motion_module=motion_var.get().strip(),
            workflow_path=workflow_var.get().strip(),
            frames=frames_var.get().strip(),
            fps=fps_var.get().strip(),
            seed=seed_var.get().strip(),
            steps=steps_var.get().strip(),
            cfg=cfg_var.get().strip(),
            denoise=denoise_var.get().strip(),
            include_subfolders="1" if subfolder_var.get() else "0",
        )

    def pick_dir(var: tk.StringVar, title: str) -> None:
        init = Path(var.get().strip()) if var.get().strip() else Path.home()
        if init.is_file():
            init = init.parent
        p = filedialog.askdirectory(title=title, initialdir=folder_dialog_initial(init))
        if not p:
            return
        touch_workspace_from_path(p)
        var.set(p)
        persist()
        refresh_count()

    def pick_workflow() -> None:
        init = Path(workflow_var.get().strip()) if workflow_var.get().strip() else Path.home()
        if init.is_file():
            init = init.parent
        p = filedialog.askopenfilename(
            title="ComfyUI 워크플로 JSON",
            initialdir=folder_dialog_initial(init),
            filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        touch_workspace_from_path(p)
        workflow_var.set(p)
        persist()

    def refresh_count() -> None:
        folder = Path(input_var.get().strip())
        msg = describe_input_folder(folder, recursive=subfolder_var.get())
        out = output_var.get().strip() or "(미설정)"
        status_var.set(f"{msg} · 출력: {out}")

    row = 0

    def add_row(label: str, widget: tk.Widget, btn: tk.Widget | None = None) -> None:
        nonlocal row
        ttk.Label(frm, text=label, width=12).grid(row=row, column=0, sticky="w", pady=3)
        widget.grid(row=row, column=1, sticky="ew", padx=(4, 4), pady=3)
        if btn:
            btn.grid(row=row, column=2, pady=3)
        row += 1

    url_entry = ttk.Entry(frm, textvariable=url_var)
    add_row("ComfyUI URL", url_entry)

    input_entry = ttk.Entry(frm, textvariable=input_var)
    add_row(
        "입력 이미지 폴더",
        input_entry,
        ttk.Button(frm, text="찾기…", command=lambda: pick_dir(input_var, "입력 이미지 폴더")),
    )
    bind_path_entry_dnd(
        input_entry,
        input_var,
        mode="dir",
        on_set=lambda _p: (persist(), refresh_count()),
    )

    output_entry = ttk.Entry(frm, textvariable=output_var)
    add_row("출력 MP4 폴더", output_entry, ttk.Button(frm, text="찾기…", command=lambda: pick_dir(output_var, "출력 MP4 폴더")))
    bind_path_entry_dnd(
        output_entry,
        output_var,
        mode="dir",
        on_set=lambda _p: (persist(), refresh_count()),
    )

    wf_entry = ttk.Entry(frm, textvariable=workflow_var)
    add_row(
        "워크플로 JSON",
        wf_entry,
        ttk.Button(frm, text="찾기…", command=pick_workflow),
    )
    bind_path_entry_dnd(
        wf_entry,
        workflow_var,
        mode="file",
        extensions=(".json",),
        on_set=lambda _p: persist(),
    )

    pos_entry = ttk.Entry(frm, textvariable=positive_var)
    add_row("긍정 프롬프트", pos_entry)

    neg_entry = ttk.Entry(frm, textvariable=negative_var)
    add_row("부정 프롬프트", neg_entry)

    model_fr = ttk.Frame(frm)
    model_fr.grid_columnconfigure(1, weight=1)
    model_fr.grid_columnconfigure(3, weight=1)
    ttk.Label(model_fr, text="체크포인트").grid(row=0, column=0, sticky="w")
    ttk.Entry(model_fr, textvariable=checkpoint_var).grid(row=0, column=1, sticky="ew", padx=(4, 12))
    ttk.Label(model_fr, text="모션 모듈").grid(row=0, column=2, sticky="w")
    ttk.Entry(model_fr, textvariable=motion_var).grid(row=0, column=3, sticky="ew", padx=(4, 0))
    ttk.Label(frm, text="모델", width=12).grid(row=row, column=0, sticky="nw", pady=3)
    model_fr.grid(row=row, column=1, columnspan=2, sticky="ew", pady=3)
    row += 1

    param_fr = ttk.Frame(frm)
    for i, (lbl, var, w) in enumerate(
        (
            ("프레임", frames_var, 6),
            ("FPS", fps_var, 6),
            ("Seed", seed_var, 8),
            ("Steps", steps_var, 6),
            ("CFG", cfg_var, 6),
            ("Denoise", denoise_var, 6),
        )
    ):
        ttk.Label(param_fr, text=lbl).grid(row=0, column=i * 2, padx=(0, 4))
        ttk.Entry(param_fr, textvariable=var, width=w).grid(row=0, column=i * 2 + 1, padx=(0, 10))
    ttk.Label(frm, text="AnimateDiff", width=12).grid(row=row, column=0, sticky="w", pady=3)
    param_fr.grid(row=row, column=1, columnspan=2, sticky="w", pady=3)
    row += 1

    sub_cb = ttk.Checkbutton(
        frm,
        text="하위 폴더 포함 (jpg/png 등)",
        variable=subfolder_var,
        command=refresh_count,
    )
    sub_cb.grid(row=row, column=1, columnspan=2, sticky="w", pady=(0, 4))
    row += 1

    ctrl_fr = ttk.Frame(frm)
    btn_test = ttk.Button(ctrl_fr, text="서버 확인", command=lambda: test_server())
    btn_run = ttk.Button(ctrl_fr, text="MP4 생성", command=lambda: run_generate())
    btn_test.pack(side=tk.LEFT, padx=(0, 8))
    btn_run.pack(side=tk.LEFT)
    ttk.Label(frm, text="").grid(row=row, column=0)
    ctrl_fr.grid(row=row, column=1, sticky="w", pady=(8, 4))
    row += 1

    hint = ttk.Label(
        frm,
        text=(
            "기본 워크플로: ComfyUI + AnimateDiff Evolved + Video Helper Suite(VHS) 필요. "
            "커스텀 JSON은 __IMAGE__/__POSITIVE__/__NEGATIVE__ 플레이스홀더 지원."
        ),
        wraplength=920,
    )
    hint.grid(row=row, column=0, columnspan=3, sticky="w", pady=(4, 8))
    row += 1

    ttk.Label(frm, textvariable=status_var).grid(row=row, column=0, columnspan=3, sticky="w")

    input_var.trace_add("write", lambda *_: refresh_count())
    refresh_count()

    def set_busy(on: bool) -> None:
        busy["v"] = on
        for b in (btn_run, btn_test):
            b.state(["disabled"] if on else ["!disabled"])

    def test_server() -> None:
        url = url_var.get().strip()
        ok, msg = probe_server(url)
        if ok:
            safe_messagebox(root, "showinfo", "2_4 imageToMp4", msg)
            status_var.set(msg)
        else:
            safe_messagebox(root, "showwarning", "2_4 imageToMp4", msg)
            status_var.set("ComfyUI 연결 실패")

    def run_generate() -> None:
        if busy["v"]:
            return
        input_dir = Path(input_var.get().strip())
        output_dir = Path(output_var.get().strip())
        if not input_dir.is_dir():
            safe_messagebox(root, "showwarning", "2_4 imageToMp4", "입력 이미지 폴더를 선택하세요.")
            return
        images = list_input_images(input_dir, recursive=subfolder_var.get())
        if not images:
            safe_messagebox(
                root,
                "showwarning",
                "2_4 imageToMp4",
                describe_input_folder(input_dir, recursive=subfolder_var.get()),
            )
            return
        if not output_var.get().strip():
            safe_messagebox(root, "showwarning", "2_4 imageToMp4", "출력 MP4 폴더를 선택하세요.")
            return
        persist()
        set_busy(True)
        status_var.set("ComfyUI AnimateDiff 처리 시작…")

        wf_path = Path(workflow_var.get().strip()) if workflow_var.get().strip() else None
        if wf_path and not wf_path.is_file():
            wf_path = None

        def work() -> None:
            try:
                result = run_batch(
                    url=url_var.get().strip(),
                    input_dir=input_dir,
                    output_dir=output_dir,
                    positive=positive_var.get().strip(),
                    negative=negative_var.get().strip(),
                    checkpoint=checkpoint_var.get().strip(),
                    motion_module=motion_var.get().strip(),
                    frames=_int_field(frames_var.get(), 16),
                    fps=_int_field(fps_var.get(), 8),
                    seed=_int_field(seed_var.get(), -1),
                    steps=_int_field(steps_var.get(), 20),
                    cfg=_float_field(cfg_var.get(), 7.0),
                    denoise=_float_field(denoise_var.get(), 0.6),
                    workflow_path=wf_path,
                    recursive=subfolder_var.get(),
                    on_item_start=lambda i, t, p: safe_after(
                        root, lambda: status_var.set(f"[{i}/{t}] {p.name} 처리 중…")
                    ),
                    on_item_progress=lambda msg: safe_after(root, lambda m=msg: status_var.set(m)),
                )

                def ok() -> None:
                    msg = f"완료 — 성공 {len(result.ok)}개"
                    if result.failed:
                        msg += f", 실패 {len(result.failed)}개"
                    status_var.set(msg)
                    if result.failed:
                        lines = "\n".join(f"{p.name}: {err}" for p, err in result.failed[:5])
                        if len(result.failed) > 5:
                            lines += f"\n…외 {len(result.failed) - 5}건"
                        safe_messagebox(
                            root,
                            "showwarning",
                            "일부 실패",
                            f"{msg}\n\n{lines}",
                        )
                    else:
                        safe_messagebox(
                            root,
                            "showinfo",
                            "MP4 생성 완료",
                            f"{len(result.ok)}개 MP4가 저장되었습니다.\n{output_dir}",
                        )

                safe_after(root, ok)
            except Exception:
                err = traceback.format_exc()

                def fail() -> None:
                    status_var.set("오류")
                    safe_messagebox(root, "showerror", "2_4 imageToMp4", err[-2000:])

                safe_after(root, fail)
            finally:

                def fin() -> None:
                    set_busy(False)

                safe_after(root, fin)

        threading.Thread(target=work, daemon=True).start()

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    run_mainloop(root, standalone)
