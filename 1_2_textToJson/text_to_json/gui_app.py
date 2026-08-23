# -*- coding: utf-8 -*-
"""1_2_textToJson GUI — 루트/tts txt + 루트/md 지침 → Genspark → tts/*.json."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, scrolledtext, ttk

from text_to_json import __version__
from text_to_json import diag_log
from text_to_json.credentials import load_credentials, save_credentials
from text_to_json.genspark_chat import has_playwright, run_convert_flow
from text_to_json.json_io import (
    normalize_dialogue_json,
    parse_dialogue_json,
    write_dialogue_json,
)
from text_to_json.paths import (
    GENSPARK_AI_CHAT_URL,
    default_convert_command,
    default_dialogue_json_md,
    default_json_path,
    ensure_layout,
    find_voices_json,
    is_canonical_dialogue_md,
    is_source_txt_path,
    json_sample_path,
    list_md_files,
    list_txt_files,
    module_md_dir,
    path_under_root,
    pick_latest,
    tts_dir,
    voice_speaker_keys,
)
from text_to_json.settings import (
    default_root_dir,
    folder_dialog_initial,
    load_gui_settings,
    module_dist_dir,
    save_gui_settings,
)
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
    if not standalone and getattr(root, "_text_to_json_gui_built", False):
        return
    if not standalone:
        setattr(root, "_text_to_json_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"1_2 textToJson {__version__}",
        minsize=(780, 580),
        geometry="920x760",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    cred_email, cred_pw = load_credentials()
    root_var = tk.StringVar(value=cfg.get("root_dir") or str(default_root_dir()))
    txt_var = tk.StringVar(value=cfg.get("txt_file") or "")
    _guide = default_dialogue_json_md()
    _cfg_md = (cfg.get("md_file") or "").strip()
    if _guide is not None and not is_canonical_dialogue_md(_cfg_md):
        _cfg_md = str(_guide)
    elif not _cfg_md and _guide is not None:
        _cfg_md = str(_guide)
    md_var = tk.StringVar(value=_cfg_md)
    email_var = tk.StringVar(value=cfg.get("email") or cred_email or "")
    pw_var = tk.StringVar(value=cred_pw or "")
    status_var = tk.StringVar(
        value="루트/tts txt · 모듈 md/dialogue_json · Genspark → tts/*.json"
    )
    busy = {"v": False}
    _last_root = {"v": root_var.get().strip()}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(1, weight=1)
    frm.grid_rowconfigure(7, weight=1)
    frm.grid_rowconfigure(8, weight=2)

    def profile_dir() -> Path:
        base = module_dist_dir()
        base.mkdir(parents=True, exist_ok=True)
        return base / ".genspark_text_to_json_profile"

    def _diag_dir() -> Path:
        root_raw = root_var.get().strip()
        if root_raw:
            try:
                return ensure_layout(root_raw)["tts"]
            except OSError:
                pass
        d = module_dist_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def persist() -> None:
        save_gui_settings(
            root_dir=root_var.get().strip(),
            txt_file=txt_var.get().strip(),
            md_file=md_var.get().strip(),
            command=cmd_text.get("1.0", tk.END).strip(),
            email=email_var.get().strip(),
        )
        if email_var.get().strip() and pw_var.get():
            save_credentials(email_var.get().strip(), pw_var.get())

    def _account() -> tuple[str, str] | None:
        email = email_var.get().strip()
        password = pw_var.get()
        if not password:
            _e, _p = load_credentials()
            if _p:
                password = _p
            if not email and _e:
                email = _e
                email_var.set(_e)
        if not email:
            safe_messagebox(
                root,
                "showwarning",
                "1_2 textToJson",
                "Genspark 로그인 이메일을 입력하세요.",
            )
            return None
        if not password:
            safe_messagebox(
                root,
                "showwarning",
                "1_2 textToJson",
                "Genspark 로그인 비밀번호를 입력하세요.",
            )
            return None
        return email, password

    def set_status(msg: str) -> None:
        status_var.set(msg)

    def set_busy(v: bool) -> None:
        busy["v"] = v
        st = tk.DISABLED if v else tk.NORMAL
        for b in (btn_root, btn_txt, btn_md, btn_browser, btn_save):
            try:
                b.configure(state=st)
            except tk.TclError:
                pass

    def refresh_files(*, auto_pick: bool = True, force: bool = False) -> None:
        """루트 기준 tts txt · 모듈 dialogue_json 지침을 맞춘다."""
        r = Path(root_var.get().strip() or ".").expanduser()
        ensure_layout(r)
        txts = list_txt_files(r)
        mds = list_md_files(r)
        if auto_pick:
            cur_txt = Path(txt_var.get()) if txt_var.get().strip() else None
            need_txt = (
                force
                or cur_txt is None
                or not is_source_txt_path(cur_txt)
                or not path_under_root(cur_txt, r)
                or cur_txt.parent.name.casefold() != "tts"
            )
            if need_txt:
                p = pick_latest(txts)
                txt_var.set(str(p) if p else "")

            cur_md = Path(md_var.get()) if md_var.get().strip() else None
            cur_s = str(cur_md).replace("\\", "/") if cur_md else ""
            need_md = (
                force
                or cur_md is None
                or not cur_md.is_file()
                or "_MEI" in cur_s
            )
            if need_md:
                guide = default_dialogue_json_md() or pick_latest(mds)
                md_var.set(str(guide) if guide else "")
        _sync_command_default()
        set_status(
            f"tts(txt) {len(txts)} · md {len(mds)}  → {r}"
            f"  |  지침: {module_md_dir()}"
        )
        persist()

    def apply_root(*, force: bool = True) -> None:
        raw = root_var.get().strip()
        if not raw:
            return
        r = Path(raw).expanduser()
        ensure_layout(r)
        if force:
            touch_workspace_from_path(str(r))
        refresh_files(auto_pick=True, force=force)
        _last_root["v"] = str(r)

    def _voices_for_root() -> Path | None:
        return find_voices_json(root_var.get().strip() or None)

    def _sync_command_default() -> None:
        cur = cmd_text.get("1.0", tk.END).strip()
        saved = (cfg.get("command") or "").strip()
        txt_p = Path(txt_var.get()) if txt_var.get() else None
        md_p = Path(md_var.get()) if md_var.get() else None
        if not (txt_p and md_p and txt_p.is_file() and md_p.is_file()):
            return
        voices = _voices_for_root()
        fresh = default_convert_command(
            txt_name=txt_p.name,
            md_name=md_p.name,
            sample_name=(json_sample_path() or Path()).name,
            voices_name=voices.name if voices else "",
            voice_keys=voice_speaker_keys(voices),
        )
        if (
            not cur
            or cur == saved
            or "첨부한" in cur
            or "아래 「" in cur
            or "dialogue JSON" in cur
        ):
            cmd_text.delete("1.0", tk.END)
            cmd_text.insert("1.0", fresh)

    ttk.Label(frm, text="루트 폴더", width=12).grid(row=0, column=0, sticky="w")
    root_ent = ttk.Entry(frm, textvariable=root_var)
    root_ent.grid(row=0, column=1, sticky="ew", padx=4)

    def pick_root() -> None:
        d = filedialog.askdirectory(
            parent=root,
            title="루트 폴더 (하위 tts)",
            initialdir=folder_dialog_initial(
                Path(root_var.get().strip()) if root_var.get().strip() else None
            ),
        )
        if d:
            root_var.set(d)
            apply_root(force=True)

    def on_root_drop(_path: str) -> None:
        apply_root(force=True)

    def on_root_focus_out(_e: object | None = None) -> None:
        cur = root_var.get().strip()
        if cur and cur != _last_root["v"]:
            apply_root(force=True)

    bind_path_row_dnd(root_ent, frm, root_var, mode="dir", on_set=on_root_drop)
    root_ent.bind("<FocusOut>", on_root_focus_out)
    btn_root = ttk.Button(frm, text="찾기", command=pick_root, width=8)
    btn_root.grid(row=0, column=2, padx=(4, 0))

    def _on_file_path_set(_path: str) -> None:
        _sync_command_default()
        persist()

    def pick_txt() -> None:
        r = Path(root_var.get().strip() or ".")
        tdir = tts_dir(r)
        init = (
            Path(txt_var.get()).parent
            if txt_var.get().strip()
            else (tdir if tdir.is_dir() else r)
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="대본 TXT (tts/)",
            initialdir=folder_dialog_initial(init),
            filetypes=[("텍스트", "*.txt;*.md"), ("모든 파일", "*.*")],
        )
        if p:
            txt_var.set(p)
            _on_file_path_set(p)

    def pick_md() -> None:
        mdir = module_md_dir()
        init = (
            Path(md_var.get()).parent
            if md_var.get().strip()
            else (mdir if mdir.is_dir() else Path.home())
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="변환 지침 (모듈 md/dialogue_json)",
            initialdir=folder_dialog_initial(init),
            filetypes=[("지침", "*.txt;*.md"), ("모든 파일", "*.*")],
        )
        if p:
            md_var.set(p)
            _on_file_path_set(p)

    ttk.Label(frm, text="TXT (tts/)", width=12).grid(
        row=1, column=0, sticky="w", pady=(6, 0)
    )
    txt_ent = ttk.Entry(frm, textvariable=txt_var)
    txt_ent.grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
    btn_txt = ttk.Button(frm, text="찾기", command=pick_txt, width=8)
    btn_txt.grid(row=1, column=2, padx=(4, 0), pady=(6, 0))
    bind_path_entry_dnd(
        txt_ent, txt_var, mode="file", extensions=(".txt", ".md"), on_set=_on_file_path_set
    )
    bind_path_row_dnd(
        txt_ent, frm, txt_var, mode="file", extensions=(".txt", ".md"), on_set=_on_file_path_set
    )

    ttk.Label(frm, text="MD (지침)", width=12).grid(
        row=2, column=0, sticky="w", pady=(6, 0)
    )
    md_ent = ttk.Entry(frm, textvariable=md_var)
    md_ent.grid(row=2, column=1, sticky="ew", padx=4, pady=(6, 0))
    btn_md = ttk.Button(frm, text="찾기", command=pick_md, width=8)
    btn_md.grid(row=2, column=2, padx=(4, 0), pady=(6, 0))
    bind_path_entry_dnd(
        md_ent, md_var, mode="file", extensions=(".md", ".txt"), on_set=_on_file_path_set
    )
    bind_path_row_dnd(
        md_ent, frm, md_var, mode="file", extensions=(".md", ".txt"), on_set=_on_file_path_set
    )

    ttk.Label(frm, text="이메일", width=12).grid(row=3, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(frm, textvariable=email_var).grid(
        row=3, column=1, sticky="ew", padx=4, pady=(6, 0)
    )
    ttk.Label(frm, text="비밀번호", width=12).grid(
        row=4, column=0, sticky="w", pady=(6, 0)
    )
    ttk.Entry(frm, textvariable=pw_var, show="•").grid(
        row=4, column=1, sticky="ew", padx=4, pady=(6, 0)
    )

    tip = ttk.Label(
        frm,
        text="루트=장 폴더 → tts TXT 자동 · 지침=모듈 md/dialogue_json.txt · 결과는 tts/*.json",
        foreground="#555",
    )
    tip.grid(row=5, column=0, columnspan=3, sticky="w", pady=(8, 0))

    cmd_fr = ttk.LabelFrame(frm, text="변환 명령", padding=4)
    cmd_fr.grid(row=6, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    cmd_fr.grid_columnconfigure(0, weight=1)
    cmd_fr.grid_rowconfigure(0, weight=1)
    cmd_text = scrolledtext.ScrolledText(cmd_fr, wrap=tk.WORD, height=3)
    cmd_text.grid(row=0, column=0, sticky="nsew")
    if cfg.get("command"):
        cmd_text.insert("1.0", cfg["command"])

    res_fr = ttk.LabelFrame(frm, text="변환 결과 JSON", padding=4)
    res_fr.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    res_fr.grid_columnconfigure(0, weight=1)
    res_fr.grid_rowconfigure(0, weight=1)
    result_text = scrolledtext.ScrolledText(res_fr, wrap=tk.WORD, height=14)
    result_text.grid(row=0, column=0, sticky="nsew")

    log_fr = ttk.LabelFrame(frm, text="진단 로그", padding=4)
    log_fr.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    log_fr.grid_columnconfigure(0, weight=1)
    log_fr.grid_rowconfigure(0, weight=1)
    log_text = scrolledtext.ScrolledText(log_fr, wrap=tk.WORD, height=6)
    log_text.grid(row=0, column=0, sticky="nsew")

    def begin_diag(title: str) -> Path:
        log_text.delete("1.0", tk.END)
        path = diag_log.start_session(
            _diag_dir() / "text_to_json_diag.log", title=title
        )
        set_status(f"진단로그 → {path}")
        return path

    def _on_diag_line(line: str) -> None:
        def append() -> None:
            try:
                log_text.insert(tk.END, line + "\n")
                log_text.see(tk.END)
            except tk.TclError:
                pass

        safe_after(root, append)

    diag_log.add_listener(_on_diag_line)

    def show_json_result(raw: str) -> str:
        voices = _voices_for_root()
        body = normalize_dialogue_json(raw, voices_path=voices)
        result_text.delete("1.0", tk.END)
        result_text.insert("1.0", body)
        return body

    def export_json(source: str) -> Path | None:
        root_raw = root_var.get().strip()
        txt_raw = txt_var.get().strip()
        if not root_raw or not txt_raw:
            diag_log.log("저장실패 — 루트/TXT 없음")
            return None
        try:
            dest = default_json_path(txt_raw, root_raw)
            voices = _voices_for_root()
            path = write_dialogue_json(dest, source, voices_path=voices)
            n = len(parse_dialogue_json(path.read_text(encoding="utf-8"))["inputs"])
            diag_log.log(f"JSON 저장OK → {path} inputs={n} voices={voices or '-'}")
            return path
        except (ValueError, OSError) as e:
            diag_log.log(f"저장거부 — {e}")
            safe_messagebox(root, "showwarning", "1_2 textToJson", str(e))
            return None

    def do_save_json() -> None:
        begin_diag("JSON 저장")
        raw = result_text.get("1.0", tk.END)
        if not raw.strip():
            try:
                raw = root.clipboard_get()
            except tk.TclError:
                raw = ""
        if not raw.strip():
            safe_messagebox(
                root,
                "showwarning",
                "1_2 textToJson",
                "결과 JSON을 아래 칸에 붙여넣거나,\n"
                "클립보드에 복사한 뒤 「JSON 저장」을 누르세요.",
            )
            return
        try:
            show_json_result(raw)
        except ValueError as e:
            safe_messagebox(root, "showwarning", "1_2 textToJson", str(e))
            return
        exported = export_json(raw)
        if exported:
            set_status(f"JSON 저장 → {exported}")
            safe_messagebox(
                root,
                "showinfo",
                "1_2 textToJson",
                f"dialogue JSON 저장:\n{exported}",
            )

    act = ttk.Frame(frm)
    act.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    def _prepare_convert() -> tuple[str, str, Path, Path, str] | None:
        acc = _account()
        if acc is None:
            return None
        email, password = acc
        txt = Path(txt_var.get().strip())
        md = Path(md_var.get().strip())
        missing = [
            n for n, p in (("TXT", txt), ("MD", md)) if not p.is_file()
        ]
        if missing:
            safe_messagebox(
                root,
                "showwarning",
                "1_2 textToJson",
                "파일이 없습니다: "
                + ", ".join(missing)
                + "\n루트/tts · 모듈 md/dialogue_json 을 확인하세요.",
            )
            return None
        if not has_playwright():
            safe_messagebox(
                root, "showerror", "1_2 textToJson", "Playwright가 필요합니다."
            )
            return None
        cmd = cmd_text.get("1.0", tk.END).strip()
        persist()
        return email, password, txt, md, cmd

    def _start_convert() -> None:
        if busy["v"]:
            return
        prep = _prepare_convert()
        if prep is None:
            return
        email, password, txt, md, cmd = prep
        log_path = begin_diag("브라우저 열기")
        diag_log.log(f"준비 txt={txt} md={md}")

        def work() -> None:
            try:
                result = run_convert_flow(
                    txt_path=txt,
                    md_path=md,
                    profile_dir=profile_dir(),
                    command=cmd,
                    open_browser=True,
                    url=GENSPARK_AI_CHAT_URL,
                    email=email,
                    password=password,
                    content_root=root_var.get().strip(),
                )
                scraped = ((result or {}).get("dialogue_json") or "").strip()
                logged = bool((result or {}).get("logged_in"))
                mode = (result or {}).get("mode") or ""
                diag_log.log(
                    f"플로우종료 mode={mode} logged_in={logged} "
                    f"scraped_chars={len(scraped)}"
                )

                def done() -> None:
                    set_busy(False)
                    if scraped:
                        try:
                            show_json_result(scraped)
                        except ValueError as e:
                            result_text.delete("1.0", tk.END)
                            result_text.insert("1.0", scraped)
                            safe_messagebox(
                                root,
                                "showwarning",
                                "1_2 textToJson",
                                f"응답을 받았지만 JSON 검증 실패:\n{e}",
                            )
                            set_status(f"검증 실패 · 로그 {log_path}")
                            return
                        exported = export_json(scraped)
                        note = " · 로그인OK" if logged else ""
                        if exported:
                            set_status(f"변환 완료{note} → {exported}")
                            safe_messagebox(
                                root,
                                "showinfo",
                                "1_2 textToJson",
                                f"브라우저·변환 완료{note}.\n"
                                f"저장:\n{exported}\n\n진단로그:\n{log_path}",
                            )
                        else:
                            set_status(f"변환 결과 표시{note} (저장 안 됨)")
                    else:
                        set_status(f"응답 JSON을 못 찾음 · 로그 {log_path}")
                        safe_messagebox(
                            root,
                            "showwarning",
                            "1_2 textToJson",
                            "Genspark 응답에서 dialogue JSON을 찾지 못했습니다.\n"
                            "결과란에 붙여넣은 뒤 「JSON 저장」을 쓰세요.\n\n"
                            f"진단로그:\n{log_path}",
                        )

                safe_after(root, done)
            except Exception as e:
                def fail() -> None:
                    set_busy(False)
                    diag_log.log(f"오류: {e}")
                    safe_messagebox(root, "showerror", "1_2 textToJson", str(e))
                    set_status(f"실패 · 로그 {log_path}")

                safe_after(root, fail)

        set_busy(True)
        set_status("Genspark 변환 중…")
        threading.Thread(target=work, daemon=True).start()

    btn_browser = ttk.Button(act, text="브라우저 열기", command=_start_convert)
    btn_browser.pack(side=tk.LEFT, padx=(0, 6))
    btn_save = ttk.Button(act, text="JSON 저장", command=do_save_json)
    btn_save.pack(side=tk.LEFT, padx=(0, 6))

    ttk.Label(frm, textvariable=status_var).grid(
        row=10, column=0, columnspan=3, sticky="w", pady=(8, 0)
    )

    apply_root(force=True)

    def on_close() -> None:
        persist()

    bind_close(root, standalone, on_close=on_close)
    bind_hub_destroy(root, standalone)
    if standalone:
        run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
