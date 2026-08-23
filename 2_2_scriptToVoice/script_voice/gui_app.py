# -*- coding: utf-8 -*-
"""2_2_scriptToVoice GUI — dialogue JSON / [N] 단락 → 루트/mp3 · 병합(텀)."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, scrolledtext, ttk

from script_voice import __version__
from script_voice.dialogue import (
    check_speakers_against_voices,
    format_dialogue_for_textarea,
    load_dialogue_json,
)
from script_voice.parser import parse_numbered_paragraphs
from script_voice.pipeline import (
    DEFAULT_GAP_SEC,
    convert_dialogue_json_to_mp3s,
    convert_script_to_mp3s,
    discover_part_mp3s,
    merge_part_mp3s,
    parse_line_range,
)
from script_voice.settings import (
    default_dialogue_json,
    ensure_root_layout,
    folder_dialog_initial,
    load_gui_settings,
    load_settings,
    migrate_root_from_saved,
    mp3_dir,
    resolve_preset_config,
    save_gui_settings,
    set_config_path_override,
    tts_dir,
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
    if not standalone and getattr(root, "_script_voice_gui_built", False):
        return
    if not standalone:
        setattr(root, "_script_voice_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_2 scriptToVoice {__version__}",
        minsize=(720, 520),
        geometry="880x640",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    root_default = migrate_root_from_saved(cfg)
    _saved_mp3 = (cfg.get("mp3_dir") or cfg.get("tts_dir") or "").strip()
    if _saved_mp3 and Path(_saved_mp3).name.casefold() == "mp3":
        mp3_default = _saved_mp3
    else:
        mp3_default = str(mp3_dir(root_default))
    # 구 기본 0.5 → 새 기본 1초
    _gap_saved = (cfg.get("gap_sec") or "").strip()
    if not _gap_saved or _gap_saved in {"0.5", "0.50"}:
        gap_default = str(int(DEFAULT_GAP_SEC) if DEFAULT_GAP_SEC == int(DEFAULT_GAP_SEC) else DEFAULT_GAP_SEC)
    else:
        gap_default = _gap_saved
    script_default = cfg.get("script_text") or ""
    dialogue_default = (cfg.get("dialogue_json") or "").strip()
    range_default = (cfg.get("range_spec") or "").strip()
    cfg_path = resolve_preset_config(cfg.get("config_file"))
    set_config_path_override(cfg_path)

    root_var = tk.StringVar(value=root_default)
    mp3_var = tk.StringVar(value=mp3_default)
    gap_var = tk.StringVar(value=gap_default)
    cfg_var = tk.StringVar(value=str(cfg_path))
    dialogue_var = tk.StringVar(value=dialogue_default)
    range_var = tk.StringVar(value=range_default)
    status_var = tk.StringVar(
        value="루트/tts dialogue JSON → mp3/ (01.mp3+01.txt) · 구간 재합성 · 병합"
    )
    prog_var = tk.DoubleVar(value=0.0)
    busy = {"v": False}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(2, weight=1)

    def persist() -> None:
        save_gui_settings(
            root_dir=root_var.get().strip(),
            mp3_path=mp3_var.get().strip(),
            config_file=cfg_var.get().strip(),
            dialogue_json=dialogue_var.get().strip(),
            script_text=text.get("1.0", tk.END),
            gap_sec=gap_var.get().strip() or str(DEFAULT_GAP_SEC),
            range_spec=range_var.get().strip(),
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
        for b in (
            btn_convert,
            btn_json,
            btn_range,
            btn_merge,
            btn_root,
            btn_cfg,
            btn_dialogue,
            btn_check_speakers,
            btn_refresh,
        ):
            try:
                b.configure(state=st)
            except tk.TclError:
                pass

    def gap_sec() -> float:
        try:
            g = float(gap_var.get().strip() or DEFAULT_GAP_SEC)
        except ValueError:
            g = DEFAULT_GAP_SEC
        return max(0.0, min(5.0, g))

    def apply_root(*, force: bool = True) -> Path:
        raw = root_var.get().strip()
        if not raw:
            raise ValueError("루트 폴더가 비어 있습니다.")
        r = Path(raw).expanduser()
        t = ensure_root_layout(r)
        try:
            mp3_ent.configure(state="normal")
        except (tk.TclError, NameError):
            pass
        mp3_var.set(str(t))
        try:
            mp3_ent.configure(state="readonly")
        except (tk.TclError, NameError):
            pass

        td = tts_dir(r)
        dj = default_dialogue_json(r)
        cur = dialogue_var.get().strip()
        update_dj = bool(force) or not cur
        if not update_dj and cur:
            try:
                cur_p = Path(cur).expanduser().resolve()
                update_dj = cur_p.parent.resolve() != td.resolve()
            except OSError:
                update_dj = True
        if update_dj:
            dialogue_var.set(str(dj.resolve()) if dj.exists() else str(dj))
            if dj.is_file():
                try:
                    show_dialogue_in_textarea(dj)
                except NameError:
                    pass

        if force:
            touch_workspace_from_path(str(r))
        persist()
        set_status(f"루트 → mp3: {t} · tts JSON: {Path(dialogue_var.get()).name}")
        return t

    def out_dir() -> Path:
        t = mp3_var.get().strip()
        if t:
            p = Path(t)
            p.mkdir(parents=True, exist_ok=True)
            return p
        return apply_root(force=False)

    def reload_api() -> None:
        p = resolve_preset_config(cfg_var.get())
        cfg_var.set(str(p))
        set_config_path_override(p)
        return load_settings()

    path_fr = ttk.LabelFrame(frm, text="경로 · API", padding=8)
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    path_fr.grid_columnconfigure(1, weight=1)

    ttk.Label(path_fr, text="루트 폴더", width=12).grid(row=0, column=0, sticky="w")
    root_ent = ttk.Entry(path_fr, textvariable=root_var)
    root_ent.grid(row=0, column=1, sticky="ew", padx=4)

    def pick_root() -> None:
        try:
            init = folder_dialog_initial(
                Path(root_var.get().strip()) if root_var.get().strip() else None
            )
            d = filedialog.askdirectory(
                parent=root,
                title="루트 폴더 (하위 mp3에 음성 저장)",
                initialdir=init,
            )
        except Exception as e:
            safe_messagebox(root, "showerror", "2_2 scriptToVoice", f"폴더 선택 오류:\n{e}")
            return
        if d:
            root_var.set(d)
            try:
                apply_root(force=True)
            except Exception as e:
                safe_messagebox(root, "showerror", "2_2 scriptToVoice", str(e))

    def on_root_drop(_path: str) -> None:
        try:
            apply_root(force=True)
        except Exception as e:
            safe_messagebox(root, "showerror", "2_2 scriptToVoice", str(e))

    bind_path_row_dnd(
        root_ent, path_fr, root_var, mode="dir", on_set=on_root_drop
    )

    btn_root = ttk.Button(path_fr, text="찾기", command=pick_root, width=8)
    btn_root.grid(row=0, column=2, padx=(4, 0))

    ttk.Label(path_fr, text="mp3 폴더", width=12).grid(row=1, column=0, sticky="w", pady=(4, 0))
    mp3_ent = ttk.Entry(path_fr, textvariable=mp3_var, state="readonly")
    mp3_ent.grid(row=1, column=1, sticky="ew", padx=4, pady=(4, 0))

    ttk.Label(path_fr, text="API 설정", width=12).grid(row=2, column=0, sticky="w", pady=(4, 0))
    cfg_ent = ttk.Entry(path_fr, textvariable=cfg_var)
    cfg_ent.grid(row=2, column=1, sticky="ew", padx=4, pady=(4, 0))

    def pick_cfg() -> None:
        init = folder_dialog_initial(
            Path(cfg_var.get()).parent if cfg_var.get().strip() else None
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="elsub_config JSON (API 키 · model_id)",
            initialdir=init,
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if p:
            cfg_var.set(p)
            reload_api()
            persist()
            set_status(f"설정: {Path(p).name}")

    btn_cfg = ttk.Button(path_fr, text="찾기", command=pick_cfg, width=8)
    btn_cfg.grid(row=2, column=2, padx=(4, 0), pady=(4, 0))

    ttk.Label(path_fr, text="dialogue JSON", width=12).grid(
        row=3, column=0, sticky="w", pady=(4, 0)
    )
    dialogue_ent = ttk.Entry(path_fr, textvariable=dialogue_var)
    dialogue_ent.grid(row=3, column=1, sticky="ew", padx=4, pady=(4, 0))

    def pick_dialogue() -> None:
        raw_root = root_var.get().strip()
        init_dir = None
        if dialogue_var.get().strip():
            init_dir = Path(dialogue_var.get().strip()).expanduser().parent
        elif raw_root:
            init_dir = tts_dir(raw_root)
        init = folder_dialog_initial(init_dir)
        p = filedialog.askopenfilename(
            parent=root,
            title="dialogue JSON (voices + inputs)",
            initialdir=init,
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if p:
            dialogue_var.set(p)
            persist()
            show_dialogue_in_textarea(p)

    btn_dialogue = ttk.Button(path_fr, text="찾기", command=pick_dialogue, width=8)
    btn_dialogue.grid(row=3, column=2, padx=(4, 0), pady=(4, 0))
    bind_path_entry_dnd(
        dialogue_ent,
        dialogue_var,
        mode="file",
        extensions=(".json",),
        on_set=lambda p: show_dialogue_in_textarea(p),
    )

    ttk.Label(path_fr, text="병합 텀(초)", width=12).grid(row=4, column=0, sticky="w", pady=(4, 0))
    gap_ent = ttk.Entry(path_fr, textvariable=gap_var, width=8)
    gap_ent.grid(row=4, column=1, sticky="w", padx=4, pady=(4, 0))

    ttk.Label(path_fr, text="구간 (from~to)", width=12).grid(
        row=5, column=0, sticky="w", pady=(4, 0)
    )
    range_ent = ttk.Entry(path_fr, textvariable=range_var, width=16)
    range_ent.grid(row=5, column=1, sticky="w", padx=4, pady=(4, 0))
    ttk.Label(
        path_fr,
        text="예: 7 · 7~ (한 줄) · 1~5",
        foreground="#666",
    ).grid(row=5, column=2, sticky="w", padx=(4, 0), pady=(4, 0))

    tip = ttk.Label(
        frm,
        text="JSON → 루트/mp3 (01.mp3 + 01.txt + lines.json) · 구간 재합성 · 병합 · API 키만 elsub_config",
        foreground="#555",
    )
    tip.grid(row=1, column=0, sticky="w", pady=(0, 4))

    text_fr = ttk.LabelFrame(
        frm,
        text="대본 미리보기 (JSON 줄번호 [n] · [N] 변환 시에도 사용)",
        padding=4,
    )
    text_fr.grid(row=2, column=0, sticky="nsew")
    text_fr.grid_columnconfigure(0, weight=1)
    text_fr.grid_rowconfigure(1, weight=1)

    search_fr = ttk.Frame(text_fr)
    search_fr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    search_fr.grid_columnconfigure(1, weight=1)
    search_var = tk.StringVar(value="")
    ttk.Label(search_fr, text="검색").grid(row=0, column=0, sticky="w")
    search_ent = ttk.Entry(search_fr, textvariable=search_var)
    search_ent.grid(row=0, column=1, sticky="ew", padx=4)
    search_status = tk.StringVar(value="")
    ttk.Label(search_fr, textvariable=search_status, foreground="#555").grid(
        row=0, column=4, sticky="e", padx=(8, 0)
    )

    text = scrolledtext.ScrolledText(text_fr, wrap=tk.WORD, height=18)
    text.grid(row=1, column=0, sticky="nsew")
    text.tag_configure("search_hit", background="#ffe08a")
    if script_default:
        text.insert("1.0", script_default)

    def _clear_search_tags() -> None:
        try:
            text.tag_remove("search_hit", "1.0", tk.END)
        except tk.TclError:
            pass

    def find_in_textarea(*, backward: bool = False) -> None:
        needle = search_var.get()
        if not needle:
            search_status.set("")
            _clear_search_tags()
            set_status("검색어를 입력하세요.")
            return
        _clear_search_tags()
        start = text.index(tk.INSERT)
        if backward:
            pos = text.search(needle, start, stopindex="1.0", backwards=True)
            if not pos:
                pos = text.search(needle, tk.END, stopindex="1.0", backwards=True)
        else:
            # 현재 선택/커서 다음부터
            try:
                if text.tag_ranges(tk.SEL):
                    start = text.index(tk.SEL_LAST)
            except tk.TclError:
                pass
            pos = text.search(needle, start, stopindex=tk.END)
            if not pos:
                pos = text.search(needle, "1.0", stopindex=tk.END)
        if not pos:
            search_status.set("없음")
            set_status(f"검색 결과 없음: {needle}")
            return
        end = f"{pos}+{len(needle)}c"
        text.tag_add("search_hit", pos, end)
        text.mark_set(tk.INSERT, end)
        text.see(pos)
        # 전체 일치 개수
        count = 0
        idx = "1.0"
        while True:
            idx = text.search(needle, idx, stopindex=tk.END)
            if not idx:
                break
            count += 1
            idx = f"{idx}+{len(needle)}c"
        search_status.set(f"{count}건")
        set_status(f"검색: {needle} — {count}건")

    ttk.Button(
        search_fr, text="다음", width=6, command=lambda: find_in_textarea(backward=False)
    ).grid(row=0, column=2, padx=(4, 0))
    ttk.Button(
        search_fr, text="이전", width=6, command=lambda: find_in_textarea(backward=True)
    ).grid(row=0, column=3, padx=(4, 0))

    def _on_search_return(_e: object | None = None) -> str:
        find_in_textarea(backward=False)
        return "break"

    def _focus_search(_e: object | None = None) -> str:
        search_ent.focus_set()
        search_ent.selection_range(0, tk.END)
        return "break"

    search_ent.bind("<Return>", _on_search_return)
    root.bind("<Control-f>", _focus_search)
    root.bind("<F3>", lambda _e: (find_in_textarea(backward=False), "break")[1])
    root.bind("<Shift-F3>", lambda _e: (find_in_textarea(backward=True), "break")[1])

    def show_dialogue_in_textarea(path: str | Path) -> None:
        """dialogue JSON → textarea 에 ``[1] speaker | text`` 줄번호 표시."""
        raw = str(path or "").strip()
        if not raw:
            return
        p = Path(raw).expanduser()
        if not p.is_file():
            set_status(f"JSON 없음: {p}")
            return
        try:
            lines = load_dialogue_json(p)
            preview = format_dialogue_for_textarea(lines)
        except Exception as e:
            set_status(f"JSON 미리보기 실패: {e}")
            safe_messagebox(root, "showerror", "2_2 scriptToVoice", str(e))
            return
        text.delete("1.0", tk.END)
        text.insert("1.0", preview)
        dialogue_var.set(str(p.resolve()) if p.exists() else raw)
        persist()
        set_status(f"JSON: {p.name} — {len(lines)}줄 (본문에 줄번호 표시)")

    def refresh_settings() -> None:
        """저장된 GUI·API 설정을 다시 불러온다."""
        if busy["v"]:
            return
        try:
            fresh = load_gui_settings()
            root_default = migrate_root_from_saved(fresh)
            if root_default:
                root_var.set(root_default)
            _saved_mp3 = (fresh.get("mp3_dir") or fresh.get("tts_dir") or "").strip()
            if _saved_mp3 and Path(_saved_mp3).name.casefold() == "mp3":
                mp3_var.set(_saved_mp3)
            elif root_var.get().strip():
                mp3_var.set(str(mp3_dir(root_var.get().strip())))
            _gap = (fresh.get("gap_sec") or "").strip()
            if not _gap or _gap in {"0.5", "0.50"}:
                gap_var.set(
                    str(
                        int(DEFAULT_GAP_SEC)
                        if DEFAULT_GAP_SEC == int(DEFAULT_GAP_SEC)
                        else DEFAULT_GAP_SEC
                    )
                )
            else:
                gap_var.set(_gap)
            if fresh.get("dialogue_json"):
                dialogue_var.set(fresh["dialogue_json"])
            range_var.set((fresh.get("range_spec") or "").strip())
            cfg_path = resolve_preset_config(fresh.get("config_file"))
            cfg_var.set(str(cfg_path))
            set_config_path_override(cfg_path)
            reload_api()
            if root_var.get().strip():
                apply_root(force=False)
            dj = dialogue_var.get().strip()
            if dj and Path(dj).expanduser().is_file():
                show_dialogue_in_textarea(dj)
            elif fresh.get("script_text"):
                text.delete("1.0", tk.END)
                text.insert("1.0", fresh["script_text"])
            set_status(f"설정 다시 불러옴 · {Path(cfg_var.get()).name}")
        except Exception as e:
            safe_messagebox(root, "showerror", "2_2 scriptToVoice", str(e))

    act = ttk.Frame(frm)
    act.grid(row=3, column=0, sticky="ew", pady=(8, 0))

    def on_root_focus_out(_e: object | None = None) -> None:
        if root_var.get().strip():
            try:
                apply_root(force=False)
            except Exception:
                pass

    root_ent.bind("<FocusOut>", on_root_focus_out)
    root_ent.bind("<Return>", lambda _e: on_root_focus_out())

    def _run_json_convert(
        *,
        range_spec: str,
        require_range: bool,
        auto_merge: bool,
    ) -> None:
        if busy["v"]:
            return
        jp = dialogue_var.get().strip()
        if not jp or not Path(jp).expanduser().is_file():
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                "dialogue JSON 파일을 지정하세요.\n"
                "예: 루트/tts/….json\n"
                '(voices_file + inputs[].speaker / text)',
            )
            return
        if not root_var.get().strip():
            safe_messagebox(root, "showwarning", "2_2 scriptToVoice", "루트 폴더를 지정하세요.")
            return
        try:
            lines = load_dialogue_json(jp)
        except Exception as e:
            safe_messagebox(root, "showerror", "2_2 scriptToVoice", str(e))
            return
        spec = (range_spec or "").strip()
        if require_range and not spec:
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                "구간을 입력하세요.\n예: 7 또는 7~ (한 줄) · 1~5 (구간)",
            )
            return
        try:
            lo, hi = parse_line_range(spec, total=len(lines))
        except Exception as e:
            safe_messagebox(root, "showerror", "2_2 scriptToVoice", str(e))
            return
        out = out_dir()
        s = reload_api()
        if not s.elevenlabs_api_key:
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                "elsub_config에 elevenlabs_api_key 가 필요합니다.\n"
                f"(현재: {cfg_var.get()})\n"
                "화자 voice_id 는 JSON voices 맵을 사용합니다.",
            )
            return
        persist()
        g = gap_sec()
        n_target = hi - lo + 1

        def work() -> None:
            try:
                paths, merged = convert_dialogue_json_to_mp3s(
                    jp,
                    out,
                    api_key=s.elevenlabs_api_key,
                    model_id=s.model_id,
                    gap_sec=g,
                    auto_merge=auto_merge,
                    range_spec=spec,
                    on_progress=lambda m, p: safe_after(
                        root, lambda msg=m, pct=p: set_progress(pct, msg)
                    ),
                )

                def done() -> None:
                    set_busy(False)
                    range_note = f"{lo}~{hi}" if spec else f"1~{len(lines)}"
                    names = ", ".join(p.name for p in paths[:8])
                    if len(paths) > 8:
                        names += f" … (+{len(paths) - 8})"
                    if merged:
                        set_progress(
                            100.0,
                            f"JSON 완료 — {range_note} {len(paths)}줄 → {merged.name}",
                        )
                        safe_messagebox(
                            root,
                            "showinfo",
                            "2_2 scriptToVoice",
                            f"JSON 구간 {range_note} ({len(paths)}줄) 합성 + 병합(텀 {g:.2f}s)\n"
                            f"→ {merged}\n\n"
                            f"재생성: {names}\n"
                            f"폴더: {out}",
                        )
                    else:
                        set_progress(
                            100.0,
                            f"구간 재합성 완료 — {range_note} {len(paths)}개 → {out}",
                        )
                        safe_messagebox(
                            root,
                            "showinfo",
                            "2_2 scriptToVoice",
                            f"구간 {range_note} MP3 재생성 ({len(paths)}개)\n"
                            f"{names}\n\n"
                            f"폴더: {out}\n"
                            f"(전체 병합은 「병합」 버튼)",
                        )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 scriptToVoice", err)

                safe_after(root, fail)

        set_busy(True)
        if auto_merge:
            set_progress(
                0.0,
                f"JSON {lo}~{hi} ({n_target}줄) 변환+병합 · 텀 {g:.2f}s → {out}",
            )
        else:
            set_progress(
                0.0,
                f"구간 재합성 {lo}~{hi} ({n_target}줄) → {out}",
            )
        threading.Thread(target=work, daemon=True).start()

    def do_convert_json() -> None:
        # 전체 합성 + 병합
        _run_json_convert(range_spec="", require_range=False, auto_merge=True)

    def do_convert_range() -> None:
        # 해당 구간 NN.mp3 만 재생성 (병합은 별도)
        _run_json_convert(
            range_spec=range_var.get(),
            require_range=True,
            auto_merge=False,
        )

    def do_convert() -> None:
        if busy["v"]:
            return
        script = text.get("1.0", tk.END)
        paras = parse_numbered_paragraphs(script)
        if not paras:
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                "단락이 없습니다.\n예:\n[1]\n첫 단락\n\n[2]\n둘째 단락\n\n"
                "또는 dialogue JSON 으로 「JSON 변환」을 사용하세요.",
            )
            return
        if not root_var.get().strip():
            safe_messagebox(root, "showwarning", "2_2 scriptToVoice", "루트 폴더를 지정하세요.")
            return
        out = out_dir()
        s = reload_api()
        if not s.elevenlabs_api_key or not s.voice_id:
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                "elsub_config에 elevenlabs_api_key / voice_id 가 필요합니다.\n"
                f"(현재: {cfg_var.get()})",
            )
            return
        persist()

        def work() -> None:
            try:
                paths = convert_script_to_mp3s(
                    script,
                    out,
                    api_key=s.elevenlabs_api_key,
                    voice_id=s.voice_id,
                    model_id=s.model_id,
                    on_progress=lambda m, p: safe_after(
                        root, lambda msg=m, pct=p: set_progress(pct, msg)
                    ),
                )

                def done() -> None:
                    set_busy(False)
                    set_progress(100.0, f"변환 완료 — {len(paths)}개 → {out}")
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_2 scriptToVoice",
                        f"{len(paths)}개 MP3 생성\n{out}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 scriptToVoice", err)

                safe_after(root, fail)

        set_busy(True)
        set_progress(0.0, f"변환 시작 — {len(paras)}단락 → {out}")
        threading.Thread(target=work, daemon=True).start()

    def do_merge() -> None:
        if busy["v"]:
            return
        if not root_var.get().strip():
            safe_messagebox(root, "showwarning", "2_2 scriptToVoice", "루트 폴더를 지정하세요.")
            return
        out = out_dir()
        parts = discover_part_mp3s(out)
        if not parts:
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                f"01.mp3 … 파일이 없습니다.\n"
                f"{out}\n\n"
                "「JSON 변환+병합」으로 다시 생성하세요.",
            )
            return
        persist()
        g = gap_sec()

        def work() -> None:
            try:
                dest = merge_part_mp3s(
                    out,
                    gap_sec=g,
                    on_progress=lambda m, p: safe_after(
                        root, lambda msg=m, pct=p: set_progress(pct, msg)
                    ),
                )

                def done() -> None:
                    set_busy(False)
                    set_progress(100.0, f"병합 완료 → {dest}")
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_2 scriptToVoice",
                        f"{len(parts)}개 + 텀 {g:.2f}s\n→ {dest}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 scriptToVoice", err)

                safe_after(root, fail)

        set_busy(True)
        set_progress(0.0, f"병합 — {len(parts)}개 · 텀 {g:.2f}s")
        threading.Thread(target=work, daemon=True).start()

    def do_check_speakers() -> None:
        jp = dialogue_var.get().strip()
        if not jp or not Path(jp).expanduser().is_file():
            safe_messagebox(
                root,
                "showwarning",
                "2_2 scriptToVoice",
                "dialogue JSON 파일을 먼저 지정하세요.",
            )
            return
        try:
            result = check_speakers_against_voices(jp)
        except Exception as e:
            safe_messagebox(root, "showerror", "화자 체크", str(e))
            return

        voices_label = (
            str(result.voices_path) if result.voices_path else "(본문 voices / 경로 없음)"
        )
        if result.missing or result.empty_speaker_lines:
            parts: list[str] = []
            if result.missing:
                parts.append(
                    "voices 에 없는 화자:\n  · "
                    + "\n  · ".join(result.missing)
                )
            if result.empty_speaker_lines:
                parts.append(
                    f"speaker 비어 있는 줄: {result.empty_speaker_lines}개"
                )
            parts.append(f"\nvoices: {voices_label}")
            if result.voices_keys:
                parts.append("등록된 키: " + ", ".join(result.voices_keys))
            set_status(f"화자 누락 {len(result.missing)}명")
            safe_messagebox(root, "showwarning", "화자 체크", "\n".join(parts))
            return

        set_status(
            f"화자 체크 OK — {len(result.speakers_in_script)}명 "
            f"({', '.join(result.speakers_in_script)})"
        )
        safe_messagebox(
            root,
            "showinfo",
            "화자 체크",
            "대본 화자가 모두 voices 에 있습니다.\n\n"
            f"화자: {', '.join(result.speakers_in_script)}\n"
            f"voices: {voices_label}",
        )

    btn_check_speakers = ttk.Button(act, text="화자 체크", command=do_check_speakers)
    btn_check_speakers.pack(side=tk.LEFT, padx=(0, 8))
    btn_refresh = ttk.Button(act, text="새로고침", command=refresh_settings)
    btn_refresh.pack(side=tk.LEFT, padx=(0, 8))
    btn_json = ttk.Button(act, text="JSON 변환+병합", command=do_convert_json)
    btn_json.pack(side=tk.LEFT, padx=(0, 8))
    btn_range = ttk.Button(act, text="구간 재합성", command=do_convert_range)
    btn_range.pack(side=tk.LEFT, padx=(0, 8))
    btn_convert = ttk.Button(act, text="대본 변환 ([N])", command=do_convert)
    btn_convert.pack(side=tk.LEFT, padx=(0, 8))
    btn_merge = ttk.Button(act, text="병합 (all.mp3)", command=do_merge)
    btn_merge.pack(side=tk.LEFT, padx=(0, 8))

    prog_fr = ttk.Frame(frm)
    prog_fr.grid(row=4, column=0, sticky="ew", pady=(10, 0))
    prog_fr.grid_columnconfigure(0, weight=1)
    prog_bar = ttk.Progressbar(
        prog_fr,
        maximum=100,
        mode="determinate",
        variable=prog_var,
    )
    prog_bar.grid(row=0, column=0, sticky="ew")
    prog_lbl = ttk.Label(prog_fr, textvariable=status_var)
    prog_lbl.grid(row=1, column=0, sticky="ew", pady=(4, 0))

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    def _boot() -> None:
        if root_var.get().strip():
            apply_root(force=False)
        jp = dialogue_var.get().strip()
        if jp and Path(jp).expanduser().is_file():
            show_dialogue_in_textarea(jp)

    root.after(100, _boot)
    run_mainloop(root, standalone)
