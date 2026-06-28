# -*- coding: utf-8 -*-
"""2_3_stt: MP3 Whisper STT + 원본 대본 diff GUI."""

from __future__ import annotations

import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk

from stt import __version__
from stt.paths import guess_original_txt
from stt.settings import load_gui_settings, save_gui_settings
from stt.diagnosis import format_diagnosis_line, diagnose
from stt.script_sources import load_script_texts
from stt.text_diff import apply_diff_to_text, configure_diff_tags
from stt.whisper_stt import WHISPER_LANGUAGES, WHISPER_MODELS, transcribe_mp3
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _load_text_file(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except (OSError, UnicodeDecodeError):
            continue
    raise OSError(f"텍스트를 읽을 수 없습니다: {path}")


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_hub_destroy,
        bind_path_entry_dnd,
        bind_text_widget_file_dnd,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
    )

    cfg = load_gui_settings()
    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"2_3 STT {__version__}",
        minsize=(860, 620),
        geometry="1080x760",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    mp3_var = tk.StringVar(value=cfg.get("mp3_path", ""))
    original_var = tk.StringVar(value=cfg.get("original_path", ""))
    model_var = tk.StringVar(value=cfg.get("whisper_model", "base") or "base")
    lang_var = tk.StringVar(value=cfg.get("whisper_language", "auto") or "auto")
    status_var = tk.StringVar(value="MP3와 원본 대본(txt)을 선택한 뒤 「Whisper STT 실행」을 누르세요.")
    busy = {"v": False}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(3, weight=1)
    frm.grid_rowconfigure(6, weight=1)

    tts_ref: dict[str, str | None] = {"text": None, "source": None}

    def persist() -> None:
        save_gui_settings(
            mp3_path=mp3_var.get().strip(),
            original_path=original_var.get().strip(),
            whisper_model=model_var.get().strip(),
            whisper_language=lang_var.get().strip(),
        )

    def refresh_script_from_mp3(mp3: Path) -> None:
        scripts = load_script_texts(mp3)
        if not scripts:
            tts_ref["text"] = None
            tts_ref["source"] = None
            return
        tts_ref["text"] = scripts.tts
        tts_ref["source"] = scripts.source
        if not original_txt.get("1.0", "end-1c").strip() and scripts.original:
            original_txt.delete("1.0", tk.END)
            original_txt.insert("1.0", scripts.original)
            status_var.set(
                f"자동 로드 ({scripts.source}) — 원본 {len(scripts.original):,}자 · TTS {len(scripts.tts):,}자"
            )

    def pick_mp3() -> None:
        init = Path(mp3_var.get().strip()) if mp3_var.get().strip() else Path.home()
        if init.is_file():
            init = init.parent
        p = filedialog.askopenfilename(
            title="MP3 파일",
            initialdir=folder_dialog_initial(init),
            filetypes=[("MP3", "*.mp3"), ("오디오", "*.mp3 *.wav *.m4a"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        touch_workspace_from_path(p)
        mp3_var.set(p)
        refresh_script_from_mp3(Path(p))
        guess = guess_original_txt(Path(p))
        if guess and not original_var.get().strip():
            original_var.set(str(guess))
            load_original_file(guess)
        persist()

    def pick_original() -> None:
        init = Path(original_var.get().strip()) if original_var.get().strip() else Path.home()
        if init.is_file():
            init = init.parent
        p = filedialog.askopenfilename(
            title="원본 대본 (txt)",
            initialdir=folder_dialog_initial(init),
            filetypes=[("텍스트", "*.txt"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        touch_workspace_from_path(p)
        original_var.set(p)
        load_original_file(Path(p))
        persist()

    def load_original_file(path: Path) -> None:
        try:
            text = _load_text_file(path)
        except OSError as e:
            safe_messagebox(root, "showerror", "2_3 STT", str(e))
            return
        original_txt.configure(state=tk.NORMAL)
        original_txt.delete("1.0", tk.END)
        original_txt.insert("1.0", text)
        original_txt.configure(state=tk.NORMAL)
        status_var.set(f"원본 로드: {path.name} ({len(text):,}자)")

    path_fr = ttk.Frame(frm)
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    path_fr.grid_columnconfigure(1, weight=1)

    ttk.Label(path_fr, text="MP3", width=8).grid(row=0, column=0, sticky="w")
    mp3_ent = ttk.Entry(path_fr, textvariable=mp3_var)
    mp3_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6))
    ttk.Button(path_fr, text="찾기…", command=pick_mp3).grid(row=0, column=2)

    ttk.Label(path_fr, text="원본 txt", width=8).grid(row=1, column=0, sticky="w", pady=(6, 0))
    original_ent = ttk.Entry(path_fr, textvariable=original_var)
    original_ent.grid(row=1, column=1, sticky="ew", padx=(4, 6), pady=(6, 0))
    ttk.Button(path_fr, text="찾기…", command=pick_original).grid(row=1, column=2, pady=(6, 0))

    def _on_mp3_drop(_p: str) -> None:
        touch_workspace_from_path(_p)
        refresh_script_from_mp3(Path(_p))
        guess = guess_original_txt(Path(_p))
        if guess and not original_var.get().strip():
            original_var.set(str(guess))
            load_original_file(guess)
        persist()

    def _on_original_drop(p: str) -> None:
        load_original_file(Path(p))
        persist()

    bind_path_entry_dnd(
        mp3_ent,
        mp3_var,
        mode="file",
        extensions=(".mp3", ".wav", ".m4a"),
        on_set=_on_mp3_drop,
    )
    bind_path_entry_dnd(
        original_ent,
        original_var,
        mode="file",
        extensions=(".txt",),
        on_set=_on_original_drop,
    )

    ctrl_fr = ttk.Frame(frm)
    ctrl_fr.grid(row=1, column=0, sticky="w", pady=(0, 8))
    ttk.Label(ctrl_fr, text="Whisper 모델").grid(row=0, column=0, padx=(0, 6))
    model_cb = ttk.Combobox(
        ctrl_fr,
        textvariable=model_var,
        values=WHISPER_MODELS,
        width=12,
        state="readonly",
    )
    model_cb.grid(row=0, column=1, padx=(0, 12))
    ttk.Label(ctrl_fr, text="언어").grid(row=0, column=2, padx=(0, 6))
    lang_cb = ttk.Combobox(
        ctrl_fr,
        textvariable=lang_var,
        values=WHISPER_LANGUAGES,
        width=8,
        state="readonly",
    )
    lang_cb.grid(row=0, column=3, padx=(0, 12))
    btn_run = ttk.Button(ctrl_fr, text="Whisper STT 실행", command=lambda: run_stt())
    btn_run.grid(row=0, column=4)

    ttk.Label(
        frm,
        text="원본 대본 (비교 기준 · 직접 붙여넣기 가능)",
    ).grid(row=2, column=0, sticky="w")
    original_txt = scrolledtext.ScrolledText(frm, height=10, wrap=tk.WORD)
    original_txt.grid(row=3, column=0, sticky="nsew", pady=(4, 8))
    def _on_original_text_drop(p: Path, text: str) -> None:
        original_var.set(str(p))
        status_var.set(f"원본 로드: {p.name} ({len(text):,}자)")
        persist()

    bind_text_widget_file_dnd(
        original_txt,
        extensions=(".txt",),
        on_loaded=_on_original_text_drop,
    )

    legend = ttk.Label(
        frm,
        text="STT 결과 — 빨강: 다름  노랑: 추가  보라⟨⟩: 원본에만 있음(누락)  ※비교 시 공백·구두점·数字 콤마 정규화",
    )
    legend.grid(row=4, column=0, sticky="w")
    verdict_var = tk.StringVar(value="판정: STT 실행 후 자동 표시 (part.json·tts txt 있으면 TTS 대비 발음/Whisper 구분)")
    ttk.Label(frm, textvariable=verdict_var, wraplength=980).grid(row=5, column=0, sticky="w", pady=(0, 4))
    stt_txt = scrolledtext.ScrolledText(frm, height=12, wrap=tk.WORD, state=tk.DISABLED)
    stt_txt.grid(row=6, column=0, sticky="nsew", pady=(4, 0))
    configure_diff_tags(stt_txt)

    ttk.Label(frm, textvariable=status_var).grid(row=7, column=0, sticky="w", pady=(8, 0))

    if mp3_var.get().strip():
        mp3_init = Path(mp3_var.get().strip())
        if mp3_init.is_file():
            refresh_script_from_mp3(mp3_init)

    if original_var.get().strip():
        p = Path(original_var.get().strip())
        if p.is_file():
            try:
                load_original_file(p)
            except Exception:
                pass

    def set_busy(on: bool) -> None:
        busy["v"] = on
        btn_run.state(["disabled"] if on else ["!disabled"])

    def run_stt() -> None:
        if busy["v"]:
            return
        mp3 = Path(mp3_var.get().strip())
        if not mp3.is_file():
            safe_messagebox(root, "showwarning", "2_3 STT", "MP3 파일을 선택하세요.")
            return
        original = original_txt.get("1.0", "end-1c")
        if not original.strip():
            safe_messagebox(root, "showwarning", "2_3 STT", "원본 대본(txt)을 불러오거나 붙여넣으세요.")
            return
        persist()
        refresh_script_from_mp3(mp3)
        set_busy(True)
        status_var.set("Whisper STT 처리 중… (처음 실행 시 모델 다운로드로 시간이 걸릴 수 있습니다)")

        def work() -> None:
            try:
                text = transcribe_mp3(
                    mp3,
                    model_name=model_var.get().strip() or "base",
                    language=lang_var.get().strip() or "auto",
                )

                def ok() -> None:
                    stats = apply_diff_to_text(stt_txt, original, text)
                    diag = diagnose(
                        original=original,
                        transcribed=text,
                        tts=tts_ref.get("text"),
                        whisper_model=model_var.get().strip() or "base",
                    )
                    verdict_var.set(format_diagnosis_line(diag))
                    tts_note = ""
                    if diag.tts_match is not None:
                        tts_note = f" · TTS {diag.tts_match}%"
                    status_var.set(
                        f"완료 — STT {len(text):,}자 · 원본 일치 {stats.match_ratio}%"
                        f"{tts_note} · {diag.title} "
                        f"(다름 {stats.diff_chars}, 추가 {stats.extra_chars}, 누락 {stats.missing_chars})"
                    )
                    popup = (
                        f"전사 {len(text):,}자\n"
                        f"원본 대비 일치 {stats.match_ratio}%"
                    )
                    if diag.tts_match is not None:
                        popup += f"\nTTS 대비 일치 {diag.tts_match}%"
                    popup += f"\n\n【{diag.title}】\n{diag.message}"
                    safe_messagebox(
                        root,
                        "showinfo",
                        "STT 완료",
                        popup,
                    )

                safe_after(root, ok)
            except Exception:
                err = traceback.format_exc()
                lines = [ln for ln in err.strip().splitlines() if ln.strip()]
                short = lines[-1] if lines else "알 수 없는 오류"

                def fail() -> None:
                    status_var.set("STT 오류")
                    safe_messagebox(
                        root,
                        "showerror",
                        "STT 오류",
                        f"실패했습니다.\n\n{short}\n\n(자세한 내용은 아래 STT 결과 영역)",
                    )
                    original_txt.configure(state=tk.NORMAL)
                    stt_txt.configure(state=tk.NORMAL)
                    stt_txt.delete("1.0", tk.END)
                    stt_txt.insert("1.0", err)
                    stt_txt.configure(state=tk.DISABLED)

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
