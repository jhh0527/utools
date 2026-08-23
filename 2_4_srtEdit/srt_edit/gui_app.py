# -*- coding: utf-8 -*-
"""2_4_srtEdit GUI — 루트/tts·mp3 + 모듈 md → Genspark SRT 보정."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, scrolledtext, ttk

from srt_edit import __version__
from srt_edit import diag_log
from srt_edit.credentials import load_credentials, save_credentials
from srt_edit.genspark_chat import (
    has_playwright,
    run_correct_flow,
)
from srt_edit.paths import (
    GENSPARK_AI_CHAT_URL,
    default_correct_command,
    ensure_layout,
    list_md_files,
    list_srt_files,
    list_tts_files,
    module_md_dir,
    pick_latest,
    pick_source_srt,
    write_new_srt,
)
from srt_edit.script_io import (
    pick_tts_json,
    read_script_text,
    resolve_tts_json,
    script_plaintext_for_attach,
    strip_elevenlabs_tags,
)
from srt_edit.settings import (
    default_root_dir,
    folder_dialog_initial,
    load_gui_settings,
    module_dist_dir,
    save_gui_settings,
)
from srt_edit.srt_align import correct_srt_with_script
from srt_edit.srt_diff import (
    changed_line_ranges,
    extract_srt_payload,
    parse_srt_cues,
    validate_corrected_against_original,
)
from wisdom_workspace import touch_workspace_from_path

_YELLOW = "#FFF59D"


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
    if not standalone and getattr(root, "_srt_edit_gui_built", False):
        return
    if not standalone:
        setattr(root, "_srt_edit_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_4 srtEdit {__version__}",
        minsize=(780, 620),
        geometry="920x820",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    cred_email, cred_pw = load_credentials()
    root_var = tk.StringVar(value=cfg.get("root_dir") or str(default_root_dir()))
    srt_var = tk.StringVar(value=cfg.get("srt_file") or "")
    tts_var = tk.StringVar(value=cfg.get("tts_file") or "")
    md_var = tk.StringVar(value=cfg.get("md_file") or "")
    email_var = tk.StringVar(value=cfg.get("email") or cred_email or "")
    pw_var = tk.StringVar(value=cred_pw or "")
    status_var = tk.StringVar(
        value="루트(tts/mp3) · Genspark 보정 · new.srt"
    )
    prog_var = tk.DoubleVar(value=0.0)
    busy = {"v": False}
    browser_ready = {"v": False}
    _last_root = {"v": root_var.get().strip()}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(1, weight=1)
    frm.grid_rowconfigure(7, weight=1)
    frm.grid_rowconfigure(8, weight=2)
    frm.grid_rowconfigure(10, weight=1)

    def profile_dir() -> Path:
        base = module_dist_dir()
        base.mkdir(parents=True, exist_ok=True)
        return base / ".genspark_srt_edit_profile"

    def _diag_dir() -> Path:
        root_raw = root_var.get().strip()
        if root_raw:
            try:
                return ensure_layout(root_raw)["mp3"]
            except OSError:
                pass
        d = module_dist_dir() / "logs"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def persist() -> None:
        save_gui_settings(
            root_dir=root_var.get().strip(),
            srt_file=srt_var.get().strip(),
            tts_file=tts_var.get().strip(),
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
                "2_4 srtEdit",
                "Genspark 로그인 이메일을 입력하세요.",
            )
            return None
        if not password:
            safe_messagebox(
                root,
                "showwarning",
                "2_4 srtEdit",
                "Genspark 로그인 비밀번호를 입력하세요.",
            )
            return None
        return email, password

    def set_status(msg: str) -> None:
        status_var.set(msg)

    def set_progress(pct: float, msg: str = "") -> None:
        prog_var.set(max(0.0, min(100.0, float(pct))))
        if msg:
            status_var.set(msg)

    def set_busy(v: bool) -> None:
        busy["v"] = v
        st = tk.DISABLED if v else tk.NORMAL
        for b in (
            btn_root,
            btn_srt,
            btn_tts,
            btn_md,
            btn_browser,
            btn_compare,
        ):
            try:
                b.configure(state=st)
            except tk.TclError:
                pass

    def _path_under_root(path: Path | None, root: Path) -> bool:
        if path is None:
            return False
        try:
            path.expanduser().resolve().relative_to(root.expanduser().resolve())
            return True
        except (ValueError, OSError):
            return False

    def refresh_files(*, auto_pick: bool = True, force: bool = False) -> None:
        """경로 갱신. ``force`` 시 루트 밖·구 경로 SRT/TTS를 새 루트 기준으로 교체."""
        r = Path(root_var.get().strip() or ".").expanduser()
        ensure_layout(r)
        srts = list_srt_files(r)
        tts = list_tts_files(r)
        md = list_md_files(r)
        if auto_pick:
            cur_srt = Path(srt_var.get()) if srt_var.get().strip() else None
            need_srt = (
                force
                or cur_srt is None
                or not cur_srt.is_file()
                or not _path_under_root(cur_srt, r)
                or cur_srt.parent.name.casefold() == "stt"
                or cur_srt.name.casefold() == "new.srt"
            )
            if need_srt:
                picked = pick_source_srt(srts)
                if picked is not None:
                    srt_var.set(str(picked))
                elif force:
                    srt_var.set("")

            cur_tts = Path(tts_var.get()) if tts_var.get().strip() else None
            need_tts = (
                force
                or cur_tts is None
                or not cur_tts.is_file()
                or not _path_under_root(cur_tts, r)
            )
            richest = pick_tts_json(tts)
            if need_tts:
                if richest is not None:
                    tts_var.set(str(richest))
                else:
                    p = pick_latest(tts)
                    if p:
                        tts_var.set(str(p))
                    elif force:
                        tts_var.set("")
            elif cur_tts is not None and cur_tts.is_file():
                # txt 가 잡혀 있으면 같은 stem 의 json 으로 교체
                resolved = resolve_tts_json(cur_tts, root=r)
                if (
                    resolved is not None
                    and resolved.is_file()
                    and resolved.suffix.lower() == ".json"
                    and resolved != cur_tts
                ):
                    tts_var.set(str(resolved))

            # 모듈 md 우선 (루트 종속 아님). 없거나 _MEI·구 경로면 교체
            p = pick_latest(md)
            if p is not None:
                cur_md = Path(md_var.get()) if md_var.get().strip() else None
                cur_s = str(cur_md) if cur_md else ""
                need_md = (
                    force
                    or cur_md is None
                    or not cur_md.is_file()
                    or "_MEI" in cur_s
                    or "2_4_srtEdit" not in cur_s.replace("\\", "/")
                )
                if need_md:
                    md_var.set(str(p))
        _sync_command_default()
        set_status(
            f"mp3(srt) {len(srts)} · tts {len(tts)} · md {len(md)}  → {r}"
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

    def _sync_command_default() -> None:
        cur = cmd_text.get("1.0", tk.END).strip()
        saved = (cfg.get("command") or "").strip()
        srt_p = Path(srt_var.get()) if srt_var.get() else None
        tts_p = Path(tts_var.get()) if tts_var.get() else None
        md_p = Path(md_var.get()) if md_var.get() else None
        if not (
            srt_p
            and tts_p
            and md_p
            and srt_p.is_file()
            and tts_p.is_file()
            and md_p.is_file()
        ):
            return
        fresh = default_correct_command(
            srt_name=srt_p.name, tts_name=tts_p.name, md_name=md_p.name
        )
        if not cur or cur == saved or "첨부한" in cur:
            cmd_text.delete("1.0", tk.END)
            cmd_text.insert("1.0", fresh)

    ttk.Label(frm, text="루트 폴더", width=12).grid(row=0, column=0, sticky="w")
    root_ent = ttk.Entry(frm, textvariable=root_var)
    root_ent.grid(row=0, column=1, sticky="ew", padx=4)

    def pick_root() -> None:
        d = filedialog.askdirectory(
            parent=root,
            title="루트 폴더 (하위 tts / mp3)",
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
    bind_path_entry_dnd(root_ent, root_var, mode="dir", on_set=on_root_drop)
    root_ent.bind("<FocusOut>", on_root_focus_out)
    root_ent.bind("<Return>", lambda _e: on_root_focus_out())
    btn_root = ttk.Button(frm, text="찾기", command=pick_root, width=8)
    btn_root.grid(row=0, column=2, padx=(4, 0))

    def _on_file_path_set(_path: str) -> None:
        _sync_command_default()
        persist()

    def pick_srt() -> None:
        r = Path(root_var.get().strip() or ".").expanduser()
        mp3 = r / "mp3"
        init = folder_dialog_initial(
            Path(srt_var.get()).parent
            if srt_var.get().strip()
            else (mp3 if mp3.is_dir() else r)
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="SRT 파일 (mp3/)",
            initialdir=init,
            filetypes=[("SRT", "*.srt"), ("모든 파일", "*.*")],
        )
        if p:
            srt_var.set(p)
            _on_file_path_set(p)

    def pick_tts() -> None:
        r = Path(root_var.get().strip() or ".").expanduser()
        tts_dir = r / "tts"
        init = folder_dialog_initial(
            Path(tts_var.get()).parent
            if tts_var.get().strip()
            else (tts_dir if tts_dir.is_dir() else r)
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="TTS 대본 (tts/)",
            initialdir=init,
            filetypes=[
                ("대본", "*.txt;*.md;*.json;*.srt"),
                ("모든 파일", "*.*"),
            ],
        )
        if p:
            tts_var.set(p)
            _on_file_path_set(p)

    def pick_md() -> None:
        md_dir = module_md_dir()
        md_dir.mkdir(parents=True, exist_ok=True)
        init = folder_dialog_initial(
            Path(md_var.get()).parent if md_var.get().strip() else md_dir
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="MD 지침",
            initialdir=init,
            filetypes=[("지침", "*.md;*.txt"), ("모든 파일", "*.*")],
        )
        if p:
            md_var.set(p)
            _on_file_path_set(p)

    ttk.Label(frm, text="SRT (mp3/)", width=12).grid(
        row=1, column=0, sticky="w", pady=(6, 0)
    )
    srt_ent = ttk.Entry(frm, textvariable=srt_var)
    srt_ent.grid(row=1, column=1, sticky="ew", padx=4, pady=(6, 0))
    btn_srt = ttk.Button(frm, text="찾기", command=pick_srt, width=8)
    btn_srt.grid(row=1, column=2, padx=(4, 0), pady=(6, 0))
    bind_path_entry_dnd(
        srt_ent, srt_var, mode="file", extensions=(".srt",), on_set=_on_file_path_set
    )
    bind_path_row_dnd(
        srt_ent, frm, srt_var, mode="file", extensions=(".srt",), on_set=_on_file_path_set
    )

    ttk.Label(frm, text="TTS 대본", width=12).grid(
        row=2, column=0, sticky="w", pady=(6, 0)
    )
    tts_ent = ttk.Entry(frm, textvariable=tts_var)
    tts_ent.grid(row=2, column=1, sticky="ew", padx=4, pady=(6, 0))
    btn_tts = ttk.Button(frm, text="찾기", command=pick_tts, width=8)
    btn_tts.grid(row=2, column=2, padx=(4, 0), pady=(6, 0))
    bind_path_entry_dnd(
        tts_ent,
        tts_var,
        mode="file",
        extensions=(".txt", ".md", ".json", ".srt"),
        on_set=_on_file_path_set,
    )
    bind_path_row_dnd(
        tts_ent,
        frm,
        tts_var,
        mode="file",
        extensions=(".txt", ".md", ".json", ".srt"),
        on_set=_on_file_path_set,
    )

    ttk.Label(frm, text="MD 지침", width=12).grid(
        row=3, column=0, sticky="w", pady=(6, 0)
    )
    md_ent = ttk.Entry(frm, textvariable=md_var)
    md_ent.grid(row=3, column=1, sticky="ew", padx=4, pady=(6, 0))
    btn_md = ttk.Button(frm, text="찾기", command=pick_md, width=8)
    btn_md.grid(row=3, column=2, padx=(4, 0), pady=(6, 0))
    bind_path_entry_dnd(
        md_ent, md_var, mode="file", extensions=(".md", ".txt"), on_set=_on_file_path_set
    )
    bind_path_row_dnd(
        md_ent, frm, md_var, mode="file", extensions=(".md", ".txt"), on_set=_on_file_path_set
    )

    ttk.Label(frm, text="이메일", width=12).grid(row=4, column=0, sticky="w", pady=(6, 0))
    ttk.Entry(frm, textvariable=email_var).grid(
        row=4, column=1, sticky="ew", padx=4, pady=(6, 0)
    )
    ttk.Label(frm, text="비밀번호", width=12).grid(
        row=5, column=0, sticky="w", pady=(6, 0)
    )
    ttk.Entry(frm, textvariable=pw_var, show="•").grid(
        row=5, column=1, sticky="ew", padx=4, pady=(6, 0)
    )

    tip = ttk.Label(
        frm,
        text="브라우저 열기=로그인·보정·new.srt 자동 · 실패 시에만 「비교 표시」",
        foreground="#555",
    )
    tip.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))

    cmd_fr = ttk.LabelFrame(frm, text="보정 명령", padding=4)
    cmd_fr.grid(row=7, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    cmd_fr.grid_columnconfigure(0, weight=1)
    cmd_fr.grid_rowconfigure(0, weight=1)
    cmd_text = scrolledtext.ScrolledText(cmd_fr, wrap=tk.WORD, height=4)
    cmd_text.grid(row=0, column=0, sticky="nsew")
    if cfg.get("command"):
        cmd_text.insert("1.0", cfg["command"])

    res_fr = ttk.LabelFrame(
        frm, text="보정 결과 SRT (수정된 줄 = 노란 배경)", padding=4
    )
    res_fr.grid(row=8, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    res_fr.grid_columnconfigure(0, weight=1)
    res_fr.grid_rowconfigure(0, weight=1)
    result_text = scrolledtext.ScrolledText(res_fr, wrap=tk.WORD, height=12)
    result_text.grid(row=0, column=0, sticky="nsew")
    result_text.tag_configure("changed", background=_YELLOW)

    log_fr = ttk.LabelFrame(frm, text="진단 로그 (원인 분석)", padding=4)
    log_fr.grid(row=10, column=0, columnspan=3, sticky="nsew", pady=(8, 0))
    log_fr.grid_columnconfigure(0, weight=1)
    log_fr.grid_rowconfigure(0, weight=1)
    log_text = scrolledtext.ScrolledText(log_fr, wrap=tk.WORD, height=7)
    log_text.grid(row=0, column=0, sticky="nsew")

    def begin_diag(title: str) -> Path:
        log_text.delete("1.0", tk.END)
        path = diag_log.start_session(
            _diag_dir() / "srt_edit_diag.log", title=title
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

    def _read_original_srt() -> str:
        p = Path(srt_var.get().strip()) if srt_var.get().strip() else None
        if p is None or not p.is_file():
            return ""
        try:
            return p.read_text(encoding="utf-8-sig")
        except OSError:
            try:
                return p.read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""

    def _read_script_text() -> str:
        """tts/xx.json text 필드 평문 (선택 경로가 txt여도 json 우선)."""
        p = Path(tts_var.get().strip()) if tts_var.get().strip() else None
        root_raw = root_var.get().strip()
        resolved = resolve_tts_json(
            p, root=Path(root_raw) if root_raw else None
        )
        if resolved is None or not resolved.is_file():
            return ""
        return read_script_text(resolved)

    def _apply_script_compare(body: str) -> str:
        """tts/xx.json 의 text 원문과 비교해 큐 본문을 맞춘 뒤 new.srt 후보로 씀."""
        script = _read_script_text()
        if not script.strip() or not body.strip():
            return body
        src = resolve_tts_json(
            Path(tts_var.get().strip()) if tts_var.get().strip() else None,
            root=Path(root_var.get().strip()) if root_var.get().strip() else None,
        )
        fixed, n = correct_srt_with_script(body, script)
        diag_log.log(
            f"대본비교 xx.json={src.name if src else '-'} "
            f"변경큐={n} script_chars={len(script)}"
        )
        return fixed

    def show_corrected_with_highlight(corrected: str) -> int:
        """보정본을 넣고 원본과 다른 본문 줄에 노란 태그. 변경 cue 수 반환."""
        orig = _read_original_srt()
        cleaned = _strip_tags_in_srt_body(
            extract_srt_payload(
                corrected, original=orig, log_detail=False
            )
            or corrected
        )
        cleaned = _apply_script_compare(cleaned)
        body, ranges = changed_line_ranges(orig, cleaned)
        result_text.delete("1.0", tk.END)
        result_text.insert("1.0", body)
        result_text.tag_remove("changed", "1.0", tk.END)
        for a, b in ranges:
            result_text.tag_add("changed", f"{a}.0", f"{b}.end")
        return len(ranges)

    def _strip_tags_in_srt_body(body: str) -> str:
        """큐 본문에서 ElevenLabs ``[...]`` 태그 제거."""
        from srt_edit.srt_diff import parse_srt_cues

        cues = parse_srt_cues(body)
        if not cues:
            return strip_elevenlabs_tags(body)
        blocks: list[str] = []
        for c in cues:
            blocks.append(
                f"{c.index}\n{c.timing}\n{strip_elevenlabs_tags(c.text)}".rstrip()
                + "\n"
            )
        out = "\n".join(blocks)
        return out if out.endswith("\n") else out + "\n"

    def export_new_srt(source: str) -> Path | None:
        """start~end 추출 → xx.txt 대본 비교 보정 → mp3/new.srt."""
        orig = _read_original_srt()
        diag_log.log(
            f"저장검사 원본chars={len(orig)} 원본큐={len(parse_srt_cues(orig))} "
            f"입력chars={len(source or '')} "
            f"head={diag_log.preview(source or '')}"
        )
        body = extract_srt_payload(source, original=orig)
        body = _strip_tags_in_srt_body(body)
        body = _apply_script_compare(body)
        if not body.strip() or "-->" not in body:
            diag_log.log("저장건너뜀 — 추출본문에 --> 없음")
            return None
        ok, reason = validate_corrected_against_original(orig, body)
        if not ok:
            diag_log.log(f"저장거부 — {reason}")
            lp = diag_log.log_path()
            extra = f"\n\n진단로그:\n{lp}" if lp else ""
            safe_messagebox(
                root,
                "showwarning",
                "2_4 srtEdit",
                "new.srt 저장을 건너뛰었습니다.\n" + reason + extra,
            )
            return None
        root_raw = root_var.get().strip()
        if not root_raw:
            diag_log.log("저장실패 — 루트 폴더 없음")
            return None
        dest = write_new_srt(root_raw, body)
        diag_log.log(
            f"new.srt 저장OK → {dest} 큐={len(parse_srt_cues(body))} "
            f"bytes={dest.stat().st_size if dest.is_file() else '?'}"
        )
        return dest

    def _resolve_script_path(selected: Path) -> Path:
        """tts/xx.json 의 text 필드를 원문으로 사용 (txt 선택 시에도 json 우선)."""
        root_raw = root_var.get().strip()
        resolved = resolve_tts_json(
            selected, root=Path(root_raw) if root_raw else None
        )
        return resolved if resolved is not None else selected

    def _script_text_for_correct(selected: Path) -> tuple[Path, str]:
        resolved = _resolve_script_path(selected)
        return resolved, read_script_text(resolved)

    def do_compare_paste() -> None:
        begin_diag("비교 표시")
        raw = result_text.get("1.0", tk.END)
        if not raw.strip():
            # 클립보드 시도
            try:
                raw = root.clipboard_get()
            except tk.TclError:
                raw = ""
        if not raw.strip():
            safe_messagebox(
                root,
                "showwarning",
                "2_4 srtEdit",
                "보정 결과 SRT를 아래 칸에 붙여넣거나,\n"
                "클립보드에 복사한 뒤 「비교 표시」를 누르세요.",
            )
            return
        if not _read_original_srt():
            safe_messagebox(
                root, "showwarning", "2_4 srtEdit", "원본 SRT 파일을 선택하세요."
            )
            return
        diag_log.log(f"비교표시 입력chars={len(raw)}")
        n = show_corrected_with_highlight(raw)
        exported = export_new_srt(raw)
        lp = diag_log.log_path()
        if exported:
            set_status(f"비교 완료 — 수정 {n}블록 · new.srt → {exported}")
        else:
            set_status(
                f"비교 완료 — 수정 {n}블록 (저장 안 됨) · 로그 {lp}"
                if lp
                else f"비교 완료 — 수정된 자막 블록 {n}개 (노란 표시)"
            )

    act = ttk.Frame(frm)
    act.grid(row=9, column=0, columnspan=3, sticky="ew", pady=(10, 0))

    def _prepare_genspark_correct() -> (
        tuple[str, str, Path, Path, Path, str, Path] | None
    ):
        """계정·SRT·대본·MD·명령 준비. 실패 시 None."""
        acc = _account()
        if acc is None:
            return None
        email, password = acc
        srt = Path(srt_var.get().strip())
        tts = Path(tts_var.get().strip())
        md = Path(md_var.get().strip())
        missing = [
            n
            for n, p in (("SRT", srt), ("TTS", tts), ("MD", md))
            if not p.is_file()
        ]
        if missing:
            safe_messagebox(
                root,
                "showwarning",
                "2_4 srtEdit",
                "파일이 없습니다: "
                + ", ".join(missing)
                + "\n루트/mp3 · tts · 모듈 md 를 확인하세요.",
            )
            return None
        if not has_playwright():
            safe_messagebox(
                root, "showerror", "2_4 srtEdit", "Playwright가 필요합니다."
            )
            return None
        cmd = cmd_text.get("1.0", tk.END).strip()
        persist()
        script_src, _ = _script_text_for_correct(tts)
        tts_attach = script_plaintext_for_attach(
            script_src, work_dir=Path(root_var.get().strip()) / "tts"
        )
        if script_src != tts:
            tts_var.set(str(script_src))
        if tts_attach.name not in cmd or (script_src != tts and "첨부한" in cmd):
            cmd = default_correct_command(
                srt_name=srt.name, tts_name=tts_attach.name, md_name=md.name
            )
            cmd_text.delete("1.0", tk.END)
            cmd_text.insert("1.0", cmd)
        return email, password, srt, tts_attach, md, cmd, script_src

    def _start_genspark_correct() -> None:
        """브라우저 재시작 → 로그인 → 첨부·보정 → new.srt."""
        if busy["v"]:
            return
        prep = _prepare_genspark_correct()
        if prep is None:
            return
        email, password, srt, tts_attach, md, cmd, script_src = prep
        log_path = begin_diag("브라우저 열기")
        diag_log.log(
            f"준비 srt={srt} tts={tts_attach} md={md} "
            f"대본원본={script_src.name}"
        )

        def work() -> None:
            try:
                browser_ready["v"] = False
                result = run_correct_flow(
                    srt_path=srt,
                    tts_path=tts_attach,
                    md_path=md,
                    profile_dir=profile_dir(),
                    command=cmd,
                    open_browser=True,
                    url=GENSPARK_AI_CHAT_URL,
                    email=email,
                    password=password,
                    on_progress=lambda m, p: safe_after(
                        root, lambda msg=m, pct=p: set_progress(pct, msg)
                    ),
                )
                browser_ready["v"] = True
                mode = (result or {}).get("mode") or "attach"
                scraped = ((result or {}).get("corrected_srt") or "").strip()
                logged = bool((result or {}).get("logged_in"))
                diag_log.log(
                    f"플로우종료 mode={mode} logged_in={logged} "
                    f"scraped_chars={len(scraped)}"
                )

                def done() -> None:
                    set_busy(False)
                    if scraped:
                        n = show_corrected_with_highlight(scraped)
                        exported = export_new_srt(scraped)
                        login_note = " · 로그인OK" if logged else ""
                        if exported:
                            set_progress(
                                100.0,
                                f"보정 완료{login_note} — 수정 {n}블록 · new.srt → {exported}",
                            )
                            safe_messagebox(
                                root,
                                "showinfo",
                                "2_4 srtEdit",
                                f"브라우저·로그인·보정까지 완료했습니다.\n"
                                f"원본과 다른 {n}곳을 노란색으로 표시했습니다.\n"
                                f"대본: {script_src.name}\n"
                                f"mp3/new.srt 저장:\n{exported}\n\n"
                                f"진단로그:\n{log_path}",
                            )
                        else:
                            set_progress(
                                100.0,
                                f"보정 결과 표시{login_note} — 수정 {n}블록 "
                                f"(저장 안 됨) · 로그 {log_path}",
                            )
                            safe_messagebox(
                                root,
                                "showinfo",
                                "2_4 srtEdit",
                                f"Genspark 응답에서 SRT를 가져와\n"
                                f"원본과 다른 {n}곳을 노란색으로 표시했습니다.\n"
                                f"(new.srt 저장은 검증에서 건너뜀)\n\n"
                                f"진단로그:\n{log_path}",
                            )
                        return
                    set_progress(
                        100.0,
                        f"자동 추출 실패 — 붙여넣기 후 「비교 표시」 · 로그 {log_path}",
                    )
                    safe_messagebox(
                        root,
                        "showwarning",
                        "2_4 srtEdit",
                        "Genspark 응답에서 보정 SRT를\n"
                        "프로그램이 자동으로 못 가져왔습니다.\n\n"
                        "응답 전체를 복사 → 아래 칸에 붙여넣기 → 「비교 표시」\n"
                        "하면 new.srt 가 저장됩니다.\n"
                        "(start~end 사이 본문, 또는 원본과 같은 마지막 큐까지 있으면 됩니다)\n\n"
                        f"진단로그:\n{log_path}\n"
                        f"원문덤프: {_diag_dir() / 'srt_edit_last_raw.txt'}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)
                diag_log.log(f"오류: {err}")

                def fail() -> None:
                    set_busy(False)
                    set_progress(0.0, f"오류: {err} · 로그 {log_path}")
                    safe_messagebox(
                        root,
                        "showerror",
                        "2_4 srtEdit",
                        f"{err}\n\n진단로그:\n{log_path}",
                    )

                safe_after(root, fail)

        set_busy(True)
        set_progress(0.0, f"브라우저·보정 시작… · 로그 {log_path}")
        threading.Thread(target=work, daemon=True).start()

    def do_browser() -> None:
        """브라우저 열기 = ChromeDebug 재시작부터 new.srt 까지 일괄."""
        _start_genspark_correct()

    btn_browser = ttk.Button(act, text="브라우저 열기", command=do_browser)
    btn_browser.pack(side=tk.LEFT, padx=(0, 8))
    btn_compare = ttk.Button(act, text="비교 표시", command=do_compare_paste)
    btn_compare.pack(side=tk.LEFT, padx=(0, 8))

    prog_fr = ttk.Frame(frm)
    prog_fr.grid(row=11, column=0, columnspan=3, sticky="ew", pady=(10, 0))
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

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    # 저장된 SRT/TTS가 다른 장(루트 밖)이면 현재 루트 기준으로 맞춤
    apply_root(force=True)

    run_mainloop(root, standalone)
