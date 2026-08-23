# -*- coding: utf-8 -*-
"""2_3_stt GUI — 루트/mp3 음성 → Whisper → 동일 폴더 SRT."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from stt import __version__
from stt.settings import (
    MODEL_CHOICES,
    ensure_root_layout,
    folder_dialog_initial,
    list_mp3_media,
    load_gui_settings,
    migrate_root_from_saved,
    mp3_dir,
    save_gui_settings,
)
from stt.whisper_stt import has_faster_whisper, transcribe_to_srt_text
from wisdom_workspace import touch_workspace_from_path


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_hub_destroy,
        bind_path_entry_dnd,
        bind_path_row_dnd,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
    )

    root, standalone = tk_host(container)
    if not standalone and getattr(root, "_stt_gui_built", False):
        return
    if not standalone:
        setattr(root, "_stt_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_3 STT {__version__}",
        minsize=(680, 400),
        geometry="820x460",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    root_default = migrate_root_from_saved(cfg)
    mp3_default = cfg.get("mp3_dir") or str(mp3_dir(root_default))
    if Path(mp3_default).name.casefold() != "mp3":
        mp3_default = str(mp3_dir(root_default))
    audio_default = cfg.get("audio_path") or ""
    model_var = tk.StringVar(value=cfg.get("whisper_model") or "base")
    if model_var.get() not in MODEL_CHOICES:
        model_var.set("base")
    lang_var = tk.StringVar(value=cfg.get("language") or "ko")

    root_var = tk.StringVar(value=root_default)
    mp3_var = tk.StringVar(value=mp3_default)
    audio_var = tk.StringVar(value=audio_default)
    status_var = tk.StringVar(
        value="루트 → mp3/ 음성 선택 → Whisper → 같은 mp3 폴더에 SRT"
    )
    prog_var = tk.DoubleVar(value=0.0)
    busy = {"v": False}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(1, weight=1)

    def persist() -> None:
        save_gui_settings(
            root_dir=root_var.get().strip(),
            mp3_path=mp3_var.get().strip(),
            audio_path=audio_var.get().strip(),
            whisper_model=model_var.get().strip(),
            language=lang_var.get().strip() or "ko",
        )

    def set_status(msg: str) -> None:
        status_var.set(msg)

    def set_progress(pct: float, msg: str = "") -> None:
        prog_var.set(max(0.0, min(100.0, float(pct))))
        if msg:
            status_var.set(msg)

    def set_busy(v: bool) -> None:
        busy["v"] = v
        st = tk.DISABLED if v else tk.NORMAL
        for b in (btn_root, btn_audio, btn_refresh, btn_run):
            try:
                b.configure(state=st)
            except tk.TclError:
                pass

    def apply_root(*, force: bool = True, auto_pick: bool = True) -> Path:
        raw = root_var.get().strip()
        if not raw:
            raise ValueError("루트 폴더가 비어 있습니다.")
        r = Path(raw).expanduser()
        m = ensure_root_layout(r)
        try:
            mp3_ent.configure(state="normal")
        except (tk.TclError, NameError):
            pass
        mp3_var.set(str(m))
        try:
            mp3_ent.configure(state="readonly")
        except (tk.TclError, NameError):
            pass
        if force:
            touch_workspace_from_path(str(r))
        refresh_audio(auto_pick=auto_pick)
        persist()
        set_status(f"루트 → mp3: {m}")
        return m

    def refresh_audio(*, auto_pick: bool = True) -> None:
        m = Path(mp3_var.get().strip() or ".")
        files = list_mp3_media(m)
        paths = [str(p) for p in files]
        audio_cb["values"] = paths
        cur = audio_var.get().strip()
        if auto_pick:
            if cur and cur in paths:
                pass
            elif paths:
                audio_var.set(paths[0])
            elif cur and not Path(cur).is_file():
                audio_var.set("")
        set_status(f"mp3 미디어 {len(files)}개 → {m}")

    ttk.Label(frm, text="루트 폴더", width=12).grid(row=0, column=0, sticky="w")
    root_ent = ttk.Entry(frm, textvariable=root_var)
    root_ent.grid(row=0, column=1, sticky="ew", padx=4)

    def pick_root() -> None:
        try:
            init = folder_dialog_initial(
                Path(root_var.get().strip()) if root_var.get().strip() else None
            )
            d = filedialog.askdirectory(
                parent=root,
                title="루트 폴더 (하위 mp3 = 음성·SRT)",
                initialdir=init,
            )
        except Exception as e:
            safe_messagebox(root, "showerror", "2_3 STT", f"폴더 선택 오류:\n{e}")
            return
        if d:
            root_var.set(d)
            try:
                apply_root(force=True)
            except Exception as e:
                safe_messagebox(root, "showerror", "2_3 STT", str(e))

    def on_root_drop(_path: str) -> None:
        try:
            apply_root(force=True)
        except Exception as e:
            safe_messagebox(root, "showerror", "2_3 STT", str(e))

    bind_path_row_dnd(root_ent, frm, root_var, mode="dir", on_set=on_root_drop)
    btn_root = ttk.Button(frm, text="찾기", command=pick_root, width=8)
    btn_root.grid(row=0, column=2, padx=(4, 0))

    ttk.Label(frm, text="mp3 폴더", width=12).grid(row=1, column=0, sticky="w", pady=(6, 0))
    mp3_ent = ttk.Entry(frm, textvariable=mp3_var, state="readonly")
    mp3_ent.grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
    ttk.Label(frm, text="(=SRT)", width=8).grid(row=1, column=2, sticky="w", pady=(6, 0))

    ttk.Label(frm, text="음성/영상", width=12).grid(row=2, column=0, sticky="w", pady=(6, 0))
    audio_cb = ttk.Combobox(frm, textvariable=audio_var)
    audio_cb.grid(row=2, column=1, sticky="ew", padx=4, pady=(6, 0))
    bind_path_entry_dnd(audio_cb, audio_var, mode="file")

    def pick_audio() -> None:
        init = folder_dialog_initial(
            Path(mp3_var.get()) if mp3_var.get().strip() else None
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="음성/영상 (mp3 폴더)",
            initialdir=init,
            filetypes=[
                ("Media", "*.mp3;*.wav;*.m4a;*.mp4;*.mkv;*.webm;*.flac;*.ogg"),
                ("All", "*.*"),
            ],
        )
        if p:
            audio_var.set(p)
            # 파일이 mp3 하위면 루트 동기화
            ap = Path(p)
            if ap.parent.name.casefold() == "mp3":
                root_var.set(str(ap.parent.parent))
                try:
                    apply_root(force=True, auto_pick=False)
                except Exception:
                    pass
            audio_var.set(p)
            touch_workspace_from_path(p)
            persist()

    btn_audio = ttk.Button(frm, text="찾기", command=pick_audio, width=8)
    btn_audio.grid(row=2, column=2, padx=(4, 0), pady=(6, 0))

    def do_refresh() -> None:
        try:
            apply_root(force=False)
        except Exception as e:
            safe_messagebox(root, "showwarning", "2_3 STT", str(e))

    btn_refresh = ttk.Button(frm, text="목록", command=do_refresh, width=8)

    ttk.Label(frm, text="Whisper 모델", width=12).grid(row=3, column=0, sticky="w", pady=(6, 0))
    model_cb = ttk.Combobox(
        frm, textvariable=model_var, values=MODEL_CHOICES, state="readonly", width=14
    )
    model_cb.grid(row=3, column=1, sticky="w", padx=4, pady=(6, 0))
    btn_refresh.grid(row=3, column=2, padx=(4, 0), pady=(6, 0))

    ttk.Label(frm, text="언어", width=12).grid(row=4, column=0, sticky="w", pady=(6, 0))
    lang_ent = ttk.Entry(frm, textvariable=lang_var, width=8)
    lang_ent.grid(row=4, column=1, sticky="w", padx=4, pady=(6, 0))

    tip = ttk.Label(
        frm,
        text="루트/mp3 의 음성 → 같은 mp3 폴더에 SRT. 한 트랙 20~25자. PATH에 ffmpeg 권장.",
        foreground="#555",
    )
    tip.grid(row=5, column=0, columnspan=3, sticky="w", pady=(10, 0))

    def do_run() -> None:
        if busy["v"]:
            return
        if not root_var.get().strip():
            safe_messagebox(root, "showwarning", "2_3 STT", "루트 폴더를 지정하세요.")
            return
        try:
            out_dir = apply_root(force=False, auto_pick=False)
        except Exception as e:
            safe_messagebox(root, "showwarning", "2_3 STT", str(e))
            return
        audio = Path(audio_var.get().strip())
        if not audio.is_file():
            safe_messagebox(root, "showwarning", "2_3 STT", "음성/영상 파일을 선택하세요.")
            return
        if not has_faster_whisper():
            safe_messagebox(
                root,
                "showerror",
                "2_3 STT",
                "faster-whisper 가 설치되어 있지 않습니다.\n"
                "pip install faster-whisper",
            )
            return
        dest = out_dir / f"{audio.stem}.srt"
        persist()

        def work() -> None:
            try:
                srt = transcribe_to_srt_text(
                    audio,
                    model_size=model_var.get().strip() or "base",
                    language=lang_var.get().strip() or "ko",
                    min_chars=20,
                    max_chars=25,
                    on_progress=lambda m, p: safe_after(
                        root, lambda msg=m, pct=p: set_progress(pct, msg)
                    ),
                )
                dest.write_text(srt, encoding="utf-8")

                def done() -> None:
                    set_busy(False)
                    set_progress(100.0, f"완료 → {dest}")
                    safe_messagebox(
                        root, "showinfo", "2_3 STT", f"SRT 저장\n{dest}"
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_progress(0.0, f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_3 STT", err)

                safe_after(root, fail)

        set_busy(True)
        set_progress(0.0, "STT 시작…")
        threading.Thread(target=work, daemon=True).start()

    btn_run = ttk.Button(frm, text="SRT 만들기", command=do_run)
    btn_run.grid(row=6, column=0, columnspan=3, sticky="w", pady=(16, 0))

    prog_fr = ttk.Frame(frm)
    prog_fr.grid(row=7, column=0, columnspan=3, sticky="ew", pady=(12, 0))
    prog_fr.grid_columnconfigure(0, weight=1)
    ttk.Progressbar(
        prog_fr,
        maximum=100,
        mode="determinate",
        variable=prog_var,
    ).grid(row=0, column=0, sticky="ew")
    ttk.Label(prog_fr, textvariable=status_var).grid(
        row=1, column=0, sticky="ew", pady=(4, 0)
    )

    def on_root_focus_out(_e: object | None = None) -> None:
        if root_var.get().strip():
            try:
                apply_root(force=False)
            except Exception:
                pass

    root_ent.bind("<FocusOut>", on_root_focus_out)
    root_ent.bind("<Return>", lambda _e: on_root_focus_out())

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    def _boot() -> None:
        if root_var.get().strip():
            try:
                apply_root(force=False)
            except Exception:
                pass

    root.after(100, _boot)
    run_mainloop(root, standalone)
