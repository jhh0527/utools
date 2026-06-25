"""Genspark AI 이미지 → SRT_XXX.png 수집·대본 목록·미리보기 GUI."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from PIL import Image, ImageTk

from prompt2image import __version__
from prompt2image.browser_launch import GENSPARK_URL, open_genspark_in_chrome
from prompt2image.clipboard_util import copy_to_clipboard
from prompt2image.cue_match import ocr_matches_cue
from prompt2image.download_watch import DownloadWatcher
from prompt2image.guide_loader import (
    GUIDE_OPTIONS,
    guide_file_for_label,
    guide_label_for_file,
    load_image_guide,
)
from prompt2image.image_ocr import ocr_comma_words
from prompt2image.settings import (
    default_png_dir,
    default_srt_file,
    load_gui_settings,
    save_gui_settings,
)
from prompt2image.srt_cues import extract_cue_block, parse_srt_cues, read_srt_file_text
from prompt2image.srt_naming import (
    format_srt_filename,
    next_missing_cue_number,
    normalize_png_name,
    parse_srt_number,
    png_index,
)
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

_COL_NO = "no"
_COL_CUE = "cue"
_COL_FILE = "file"
_COL_IMG = "image"
_COL_MATCH = "match"

_TREE_COLS = (_COL_NO, _COL_CUE, _COL_FILE, _COL_IMG, _COL_MATCH)
_HEADINGS = {
    _COL_NO: "대본번호",
    _COL_CUE: "대본",
    _COL_FILE: "파일명",
    _COL_IMG: "이미지",
    _COL_MATCH: "OCR",
}


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _cue_summary(text: str, *, max_len: int = 80) -> str:
    one = " ".join((text or "").split())
    if len(one) <= max_len:
        return one
    return one[: max_len - 1] + "…"


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_hub_destroy,
        configure_notebook_tabs,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
        ui_alive,
    )

    cfg = load_gui_settings()
    png_default = default_png_dir()
    saved_png = cfg.get("png_dir", "")
    if saved_png:
        p = Path(saved_png).expanduser()
        if p.is_dir():
            png_default = p.resolve()

    srt_default = default_srt_file()
    saved_srt = cfg.get("srt_file", "")
    if saved_srt:
        sp = Path(saved_srt).expanduser()
        if sp.is_file():
            srt_default = sp.resolve()

    try:
        preview_w_default = int(cfg.get("preview_pane_width", "420"))
    except ValueError:
        preview_w_default = 420
    preview_w_default = max(280, min(900, preview_w_default))

    root, standalone = tk_host(container)
    if not standalone and getattr(root, "_prompt2image_gui_built", False):
        return
    if not standalone:
        setattr(root, "_prompt2image_gui_built", True)
    apply_window_chrome(
        root,
        standalone,
        title=f"2_2_srtToImage {__version__}",
        minsize=(1100, 680),
        geometry="1280x820",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    saved_guide = cfg.get("image_guide", "")
    default_guide_label = "증시·스톡브리핑 (실사)"
    if saved_guide:
        default_guide_label = guide_label_for_file(saved_guide)
        if default_guide_label == saved_guide and saved_guide not in GUIDE_OPTIONS.values():
            default_guide_label = list(GUIDE_OPTIONS.keys())[0]

    srt_var = tk.StringVar(value=str(srt_default))
    png_var = tk.StringVar(value=str(png_default))
    guide_var = tk.StringVar(value=default_guide_label)
    prompt_sel_var = tk.StringVar(value=cfg.get("genspark_prompt_selector", ""))
    status_var = tk.StringVar(
        value="SRT·PNG 폴더를 선택하세요. 브라우저: 기본 Chrome 계정"
    )

    frm = ttk.Frame(root, padding=10)
    if standalone:
        frm.grid(row=0, column=0, sticky="nsew")
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)
    else:
        frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(5, weight=1)

    def _path_row(label: str, var: tk.StringVar, row: int, *, is_dir: bool) -> None:
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w")
        rf = ttk.Frame(frm)
        rf.grid(row=row + 1, column=0, sticky="ew", pady=(0, 6))
        rf.grid_columnconfigure(0, weight=1)
        ent = ttk.Entry(rf, textvariable=var)
        ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        def pick() -> None:
            cur = var.get().strip()
            if is_dir:
                init = folder_dialog_initial(
                    Path(cur) if cur and Path(cur).is_dir() else png_default,
                )
                p = filedialog.askdirectory(
                    title=label,
                    initialdir=init,
                    parent=_dialog_parent(),
                )
            else:
                init = folder_dialog_initial(
                    Path(cur).parent if cur and Path(cur).parent.is_dir() else srt_default.parent,
                )
                p = filedialog.askopenfilename(
                    title=label,
                    initialdir=init,
                    filetypes=[("SRT", "*.srt"), ("모든 파일", "*.*")],
                    parent=_dialog_parent(),
                )
            if p:
                var.set(p)
                touch_workspace_from_path(p)
                on_paths_changed()

        ttk.Button(rf, text="찾아보기…", command=pick).grid(row=0, column=1)

    _path_row("SRT 대본", srt_var, 0, is_dir=False)
    _path_row("PNG 저장 폴더", png_var, 2, is_dir=True)

    guide_row = ttk.Frame(frm)
    guide_row.grid(row=4, column=0, sticky="ew", pady=(0, 4))
    ttk.Label(guide_row, text="이미지 지침").pack(side=tk.LEFT, padx=(0, 6))
    guide_combo = ttk.Combobox(
        guide_row,
        textvariable=guide_var,
        values=list(GUIDE_OPTIONS.keys()),
        state="readonly",
        width=28,
    )
    guide_combo.pack(side=tk.LEFT)
    ttk.Label(
        guide_row,
        text="증시·실사 채널은 「증시·스톡브리핑 (실사)」 선택",
        font=("", 8),
        foreground="#555",
    ).pack(side=tk.LEFT, padx=(8, 0))

    nb = ttk.Notebook(frm)
    configure_notebook_tabs(frm)
    nb.grid(row=5, column=0, sticky="nsew", pady=(4, 0))
    tab_genspark = ttk.Frame(nb, padding=6)
    tab_list = ttk.Frame(nb, padding=0)
    nb.add(tab_genspark, text="Genspark 입력")
    nb.add(tab_list, text="목록·미리보기")
    tab_genspark.grid_columnconfigure(0, weight=1)
    tab_genspark.grid_rowconfigure(3, weight=1)
    tab_list.grid_columnconfigure(0, weight=1)
    tab_list.grid_rowconfigure(1, weight=1)

    watcher: DownloadWatcher | None = None
    _photo: ImageTk.PhotoImage | None = None
    _ocr_pending: set[str] = set()
    _ocr_cache: dict[str, tuple[str, bool | None]] = {}
    _cues: list[tuple[int, str]] = []
    _cell_editor: tk.Widget | None = None
    _closing = False
    _auto_running = False
    _refreshing_list = False
    _progress_running = False

    def _progress_start() -> None:
        nonlocal _progress_running
        if _progress_running:
            return
        _progress_running = True
        try:
            progress.configure(mode="indeterminate")
            progress.start(12)
        except tk.TclError:
            pass

    def _progress_stop() -> None:
        nonlocal _progress_running
        if not _progress_running:
            return
        _progress_running = False
        try:
            progress.stop()
            progress.configure(mode="determinate")
            progress["value"] = 0
        except tk.TclError:
            pass

    def _row_iid(idx: int) -> str:
        return f"r{idx}"

    def _cue_at_iid(iid: str) -> tuple[int, str] | None:
        if not iid.startswith("r"):
            return None
        try:
            idx = int(iid[1:])
        except ValueError:
            return None
        if idx < 0 or idx >= len(_cues):
            return None
        return _cues[idx]

    def _ui_alive() -> bool:
        return ui_alive(root, closing=_closing)

    def _ui_after(fn) -> None:
        safe_after(root, fn, closing=_closing)

    def _dialog_parent() -> tk.Misc:
        return root.winfo_toplevel()

    def png_path() -> Path:
        p = Path(png_var.get().strip()).expanduser()
        # 저장 폴더는 항상 ".../png" 로 고정
        if p.name.lower() != "png":
            p = p / "png"
        return p

    def srt_path() -> Path:
        return Path(srt_var.get().strip()).expanduser()

    def load_cues() -> list[tuple[int, str]]:
        sp = srt_path()
        if not sp.is_file():
            return []
        try:
            return sorted(parse_srt_cues(sp), key=lambda c: int(c[0]))
        except OSError as e:
            safe_messagebox(root, "showerror", "SRT", f"대본을 읽을 수 없습니다.\n{e}")
            return []

    def _next_download_number() -> int:
        ids = [int(c[0]) for c in _cues]
        return next_missing_cue_number(ids, png_path()) if ids else 0

    def restart_watcher() -> None:
        nonlocal watcher
        if _closing:
            return
        if watcher:
            watcher.stop()
        p = png_path()
        try:
            png_var.set(str(p))
        except tk.TclError:
            pass
        p.mkdir(parents=True, exist_ok=True)
        watcher = DownloadWatcher(
            p,
            on_renamed=lambda dest: _ui_after(lambda: refresh_list(select=dest)),
            next_number=_next_download_number,
        )
        watcher.start()

    def _close_cell_editor() -> None:
        nonlocal _cell_editor
        if _cell_editor is not None:
            try:
                _cell_editor.destroy()
            except tk.TclError:
                pass
            _cell_editor = None

    def _file_path_for_cue(map_id: int) -> Path | None:
        p = png_path() / format_srt_filename(map_id)
        if p.is_file():
            return p
        return png_index(png_path()).get(map_id)

    def _update_tree_row(iid: str, map_id: int, cue_text: str) -> None:
        expected = format_srt_filename(map_id)
        fp = _file_path_for_cue(map_id)
        file_num = parse_srt_number(fp.name) if fp else None
        has_image = file_num == map_id
        fname = fp.name if fp else expected
        match_show = ""
        if has_image and fp:
            key = str(fp.resolve())
            cached = _ocr_cache.get(key)
            if cached is None:
                match_show = "…"
            elif cached[1] is True:
                match_show = "일치"
            elif cached[1] is False:
                match_show = "불일치"
        tree.item(
            iid,
            values=(
                str(map_id),
                _cue_summary(cue_text),
                fname,
                "있음" if has_image else "",
                match_show,
            ),
        )

    def refresh_list(*, select: Path | None = None) -> None:
        nonlocal _refreshing_list, _cues
        if not _ui_alive() or _refreshing_list:
            return
        _refreshing_list = True
        try:
            _close_cell_editor()
            _cues = load_cues()
            for iid in list(tree.get_children()):
                tree.delete(iid)
            if not _cues:
                status_var.set("SRT 파일을 선택하세요.")
                return
            for idx, (map_id, text) in enumerate(_cues):
                iid = _row_iid(idx)
                tree.insert("", tk.END, iid=iid)
                _update_tree_row(iid, map_id, text)
            have = sum(1 for c in _cues if _file_path_for_cue(int(c[0])) is not None)
            status_var.set(
                f"대본 {len(_cues)}개 · 이미지 {have}개 · {png_path()}"
            )
            for map_id, text in _cues:
                fp = _file_path_for_cue(map_id)
                if fp:
                    _schedule_ocr(fp, int(map_id), text)
            if select is not None:
                n = parse_srt_number(select.name)
                if n is not None:
                    for iid in tree.get_children():
                        cue = _cue_at_iid(iid)
                        if cue and int(cue[0]) == n:
                            tree.selection_set(iid)
                            tree.see(iid)
                            show_preview(select)
                            break
        finally:
            _refreshing_list = False

    def _set_text_widget(txt: tk.Text, content: str) -> None:
        txt.configure(state=tk.NORMAL)
        txt.delete("1.0", tk.END)
        txt.insert("1.0", content)
        txt.configure(state=tk.NORMAL)

    def _current_guide_file() -> str:
        label = guide_var.get().strip()
        if label in GUIDE_OPTIONS:
            return GUIDE_OPTIONS[label]
        return guide_file_for_label(label) if label else "image.stockbrief.md.txt"

    def reload_guide_text() -> None:
        fname = _current_guide_file()
        guide = load_image_guide(fname)
        if not guide.strip():
            guide = f"(md/{fname} 를 찾을 수 없습니다.)"
        _set_text_widget(guide_txt, guide)
        try:
            guide_frm.configure(text=f"이미지 지침 (md/{fname})")
        except tk.TclError:
            pass

    def reload_srt_input_full() -> None:
        sp = srt_path()
        if sp.is_file():
            try:
                _set_text_widget(srt_input_txt, read_srt_file_text(sp))
            except OSError as e:
                _set_text_widget(srt_input_txt, f"(SRT 읽기 실패: {e})")
        else:
            _set_text_widget(srt_input_txt, "")

    def set_srt_input_for_cue(map_id: int) -> None:
        sp = srt_path()
        if not sp.is_file():
            return
        block = extract_cue_block(sp, map_id)
        if block:
            _set_text_widget(srt_input_txt, block)

    def _persist_prompt_selector() -> None:
        try:
            save_gui_settings(
                png_dir=png_var.get().strip(),
                srt_file=srt_var.get().strip(),
                genspark_prompt_selector=prompt_sel_var.get().strip(),
                image_guide=_current_guide_file(),
            )
        except OSError:
            pass

    def on_guide_changed(_event=None) -> None:
        reload_guide_text()
        try:
            save_gui_settings(
                png_dir=png_var.get().strip(),
                srt_file=srt_var.get().strip(),
                genspark_prompt_selector=prompt_sel_var.get().strip(),
                image_guide=_current_guide_file(),
            )
        except OSError:
            pass
        status_var.set(f"지침 변경: md/{_current_guide_file()}")

    guide_combo.bind("<<ComboboxSelected>>", on_guide_changed)

    def on_paths_changed() -> None:
        # PNG 저장 폴더는 항상 ".../png" 로 정규화 + 없으면 생성
        try:
            p = png_path()
            p.mkdir(parents=True, exist_ok=True)
            png_var.set(str(p))
        except Exception:
            pass
        try:
            save_gui_settings(
                png_dir=png_var.get().strip(),
                srt_file=srt_var.get().strip(),
                genspark_prompt_selector=prompt_sel_var.get().strip(),
                image_guide=_current_guide_file(),
            )
        except OSError:
            pass
        reload_guide_text()
        reload_srt_input_full()
        restart_watcher()
        refresh_list()

    def copy_guide() -> None:
        text = guide_txt.get("1.0", tk.END).strip()
        if not text:
            safe_messagebox(root, "showwarning", "지침", "붙여넣을 지침 내용이 없습니다.")
            return
        copy_to_clipboard(root, text)
        status_var.set("지침을 클립보드에 복사했습니다 — Genspark 지침·설정란에 붙여넣기")

    def copy_srt_input() -> None:
        text = srt_input_txt.get("1.0", tk.END).strip()
        if not text:
            safe_messagebox(root, "showwarning", "대본", "붙여넣을 대본 내용이 없습니다.")
            return
        copy_to_clipboard(root, text)
        status_var.set("대본을 클립보드에 복사했습니다 — Genspark 입력란에 붙여넣기")

    def _auto_target_number() -> int:
        sel = tree.selection()
        if sel:
            cue = _cue_at_iid(sel[0])
            if cue:
                return int(cue[0])
        return _next_download_number()

    def pick_genspark_prompt_input() -> None:
        nonlocal _auto_running
        if _auto_running:
            return

        _progress_start()
        btn_pick_prompt.configure(state=tk.DISABLED)

        def work() -> None:
            err: Exception | None = None
            picked = ""
            try:
                from prompt2image.genspark_automation import run_pick_prompt_selector_sync

                def on_st(msg: str) -> None:
                    _ui_after(lambda m=msg: status_var.set(m))

                picked = run_pick_prompt_selector_sync(
                    png_dir=png_path(),
                    on_status=on_st,
                )
            except Exception as ex:
                err = ex

            def done() -> None:
                try:
                    btn_pick_prompt.configure(state=tk.NORMAL)
                except tk.TclError:
                    pass
                _progress_stop()
                if err:
                    safe_messagebox(root, "showerror", "입력란 지정", str(err))
                    status_var.set(f"입력란 지정 실패: {err}")
                    return
                prompt_sel_var.set(picked)
                _persist_prompt_selector()
                status_var.set(f"Genspark 입력란 지정 완료 — {picked}")

            _ui_after(done)

        status_var.set(
            "자동화 Chrome에서 Genspark 프롬프트 입력란을 클릭하세요…"
        )
        threading.Thread(target=work, daemon=True).start()

    def run_auto_genspark() -> None:
        nonlocal _auto_running
        if _auto_running:
            return
        srt_text = srt_input_txt.get("1.0", tk.END).strip()
        if not srt_text:
            safe_messagebox(
                root,
                "showwarning",
                "자동 다운로드",
                "SRT 대본 입력란을 채우거나 목록에서 행을 선택하세요.",
            )
            return
        guide = guide_txt.get("1.0", tk.END).strip()
        target = _auto_target_number()
        _auto_running = True
        btn_auto.configure(state=tk.DISABLED)
        _progress_start()

        def work() -> None:
            err: Exception | None = None
            saved: Path | None = None
            try:
                from prompt2image.genspark_automation import run_genspark_automation_sync

                def on_st(msg: str) -> None:
                    _ui_after(lambda m=msg: status_var.set(m))

                sel = prompt_sel_var.get().strip() or None
                saved = run_genspark_automation_sync(
                    guide=guide,
                    srt_text=srt_text,
                    png_dir=png_path(),
                    target_number=target,
                    on_status=on_st,
                    prompt_selector=sel,
                )
            except Exception as ex:
                err = ex

            def done() -> None:
                nonlocal _auto_running
                _auto_running = False
                try:
                    btn_auto.configure(state=tk.NORMAL)
                except tk.TclError:
                    pass
                _progress_stop()
                if err:
                    safe_messagebox(root, "showerror", "자동 다운로드", str(err))
                    status_var.set(f"자동 다운로드 실패: {err}")
                elif saved:
                    refresh_list(select=saved)
                    status_var.set(f"자동 다운로드 완료: {saved.name}")

            _ui_after(done)

        status_var.set(
            f"자동 다운로드 시작… → {format_srt_filename(target)} "
            "(열린 Chrome · GPT Image 2)"
        )
        threading.Thread(target=work, daemon=True).start()

    def open_browser() -> None:
        guide = guide_txt.get("1.0", tk.END).strip()
        copied = False
        if guide and not guide.startswith("("):
            copy_to_clipboard(root, guide)
            copied = True
        try:
            open_genspark_in_chrome(png_path())
        except Exception as e:
            safe_messagebox(root, "showerror", "브라우저", str(e))
            return
        nxt = format_srt_filename(_next_download_number())
        copy_note = "지침 복사됨 · " if copied else ""
        status_var.set(
            f"기본 Chrome 탭 열림 · {copy_note}다음 저장 {nxt} · "
            "모델 GPT Image 2 · 수동 생성·다운로드"
        )

    ttk.Label(
        tab_genspark,
        text=(
            "「브라우저 열기」: 지금 쓰는 Chrome(로그인 유지)에 Genspark ai_image 탭을 엽니다. "
            "「자동 생성·다운로드」: Chrome 보안상 일반 탭을 직접 조작할 수 없어 자동화 전용 창을 쓰며, "
            "기본 Chrome 로그인 쿠키를 복사해 로그인 상태를 맞춥니다 → GPT Image 2 → 생성·다운로드."
        ),
        wraplength=900,
        font=("", 9),
    ).grid(row=0, column=0, sticky="w", pady=(0, 6))

    gen_btns = ttk.Frame(tab_genspark)
    gen_btns.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    btn_auto = ttk.Button(
        gen_btns,
        text="자동 생성·다운로드",
        command=run_auto_genspark,
    )
    btn_auto.pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(gen_btns, text="브라우저 열기", command=open_browser).pack(
        side=tk.LEFT, padx=(0, 6)
    )
    ttk.Button(gen_btns, text="지침 복사", command=copy_guide).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(gen_btns, text="대본 복사", command=copy_srt_input).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(gen_btns, text="지침 다시 불러오기", command=reload_guide_text).pack(
        side=tk.LEFT, padx=(0, 6)
    )
    ttk.Button(gen_btns, text="SRT 전체 불러오기", command=reload_srt_input_full).pack(
        side=tk.LEFT
    )

    input_sel_frm = ttk.Frame(tab_genspark)
    input_sel_frm.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    input_sel_frm.grid_columnconfigure(1, weight=1)
    ttk.Label(input_sel_frm, text="Genspark 입력란 (CSS)").grid(
        row=0, column=0, sticky="w", padx=(0, 6)
    )
    prompt_sel_ent = ttk.Entry(input_sel_frm, textvariable=prompt_sel_var)
    prompt_sel_ent.grid(row=0, column=1, sticky="ew", padx=(0, 6))
    prompt_sel_ent.bind("<FocusOut>", lambda _e: _persist_prompt_selector())

    def clear_prompt_selector() -> None:
        prompt_sel_var.set("")
        _persist_prompt_selector()
        status_var.set("Genspark 입력란 지정을 초기화했습니다.")

    btn_pick_prompt = ttk.Button(
        input_sel_frm,
        text="브라우저에서 입력란 지정",
        command=pick_genspark_prompt_input,
    )
    btn_pick_prompt.grid(row=0, column=2, padx=(0, 6))
    ttk.Button(
        input_sel_frm,
        text="초기화",
        command=clear_prompt_selector,
    ).grid(row=0, column=3)
    ttk.Label(
        input_sel_frm,
        text="자동 탐지 실패 시 자동화 Chrome에서 프롬프트 입력칸을 클릭해 지정합니다.",
        font=("", 8),
        foreground="#555",
    ).grid(row=1, column=0, columnspan=4, sticky="w", pady=(4, 0))

    gen_paned = ttk.Panedwindow(tab_genspark, orient=tk.VERTICAL)
    gen_paned.grid(row=3, column=0, sticky="nsew")

    guide_frm = ttk.LabelFrame(gen_paned, text="이미지 지침", padding=4)
    srt_in_frm = ttk.LabelFrame(
        gen_paned,
        text="SRT 대본 입력 (목록에서 행 선택 시 해당 대본만 표시)",
        padding=4,
    )
    gen_paned.add(guide_frm, weight=2)
    gen_paned.add(srt_in_frm, weight=1)
    guide_frm.grid_columnconfigure(0, weight=1)
    guide_frm.grid_rowconfigure(0, weight=1)
    srt_in_frm.grid_columnconfigure(0, weight=1)
    srt_in_frm.grid_rowconfigure(0, weight=1)

    guide_scroll = ttk.Scrollbar(guide_frm, orient=tk.VERTICAL)
    guide_txt = tk.Text(
        guide_frm,
        height=12,
        wrap=tk.WORD,
        yscrollcommand=guide_scroll.set,
    )
    guide_scroll.config(command=guide_txt.yview)
    guide_txt.grid(row=0, column=0, sticky="nsew")
    guide_scroll.grid(row=0, column=1, sticky="ns")

    srt_in_scroll = ttk.Scrollbar(srt_in_frm, orient=tk.VERTICAL)
    srt_input_txt = tk.Text(
        srt_in_frm,
        height=8,
        wrap=tk.WORD,
        yscrollcommand=srt_in_scroll.set,
    )
    srt_in_scroll.config(command=srt_input_txt.yview)
    srt_input_txt.grid(row=0, column=0, sticky="nsew")
    srt_in_scroll.grid(row=0, column=1, sticky="ns")

    row_btns = ttk.Frame(tab_list)
    row_btns.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    ttk.Button(row_btns, text="목록 새로고침", command=refresh_list).pack(side=tk.LEFT)
    ttk.Button(row_btns, text="대본 복사", command=copy_srt_input).pack(side=tk.LEFT, padx=(6, 0))

    paned = ttk.Panedwindow(tab_list, orient=tk.HORIZONTAL)
    paned.grid(row=1, column=0, sticky="nsew")

    list_frm = ttk.LabelFrame(paned, text="대본 · 파일명 목록", padding=6)
    preview_frm = ttk.LabelFrame(paned, text="미리보기", padding=8)
    paned.add(list_frm, weight=4)
    paned.add(preview_frm, weight=2)

    list_frm.grid_columnconfigure(0, weight=1)
    list_frm.grid_rowconfigure(0, weight=1)

    tree_scroll_y = ttk.Scrollbar(list_frm, orient=tk.VERTICAL)
    tree_scroll_x = ttk.Scrollbar(list_frm, orient=tk.HORIZONTAL)
    tree = ttk.Treeview(
        list_frm,
        columns=_TREE_COLS,
        show="headings",
        selectmode="browse",
        yscrollcommand=tree_scroll_y.set,
        xscrollcommand=tree_scroll_x.set,
    )
    tree_scroll_y.config(command=tree.yview)
    tree_scroll_x.config(command=tree.xview)
    tree.grid(row=0, column=0, sticky="nsew")
    tree_scroll_y.grid(row=0, column=1, sticky="ns")
    tree_scroll_x.grid(row=1, column=0, sticky="ew")

    tree.column(_COL_NO, width=72, anchor=tk.CENTER, stretch=False)
    tree.column(_COL_CUE, width=360, anchor=tk.W)
    tree.column(_COL_FILE, width=120, anchor=tk.W)
    tree.column(_COL_IMG, width=56, anchor=tk.CENTER, stretch=False)
    tree.column(_COL_MATCH, width=64, anchor=tk.CENTER, stretch=False)
    for col in _TREE_COLS:
        tree.heading(col, text=_HEADINGS[col])

    preview_name_var = tk.StringVar(value="")
    ocr_var = tk.StringVar(value="")
    thumb_lbl = ttk.Label(preview_frm, text="행을 클릭하세요.", anchor=tk.CENTER)
    thumb_lbl.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
    ttk.Label(preview_frm, textvariable=preview_name_var).pack(anchor=tk.W, fill=tk.X)
    ttk.Label(preview_frm, text="OCR 인식 한글 (쉼표 구분)", foreground="#1565c0").pack(
        anchor=tk.W, pady=(8, 2)
    )
    ocr_lbl = ttk.Label(
        preview_frm,
        textvariable=ocr_var,
        wraplength=preview_w_default - 40,
        foreground="#333333",
    )
    ocr_lbl.pack(anchor=tk.W, fill=tk.X)

    def _update_ocr_wrap(_event: tk.Event | None = None) -> None:
        w = max(160, preview_frm.winfo_width() - 24)
        ocr_lbl.configure(wraplength=w)

    preview_frm.bind("<Configure>", _update_ocr_wrap)

    def _apply_pane_sash() -> None:
        root.update_idletasks()
        total = paned.winfo_width()
        if total < 400:
            return
        paned.sashpos(0, max(280, total - preview_w_default))

    def _schedule_ocr(path: Path, map_id: int, cue_text: str) -> None:
        key = str(path.resolve())
        if key in _ocr_pending or key in _ocr_cache:
            return
        _ocr_pending.add(key)

        def work() -> None:
            try:
                text = ocr_comma_words(path)
                ok = ocr_matches_cue(text, cue_text)
            except Exception as ex:
                text = f"(OCR 실패: {ex})"
                ok = False

            def done() -> None:
                _ocr_pending.discard(key)
                _ocr_cache[key] = (text, ok)
                for iid in tree.get_children():
                    cue = _cue_at_iid(iid)
                    if not cue:
                        continue
                    mid, ctext = cue
                    fp = _file_path_for_cue(mid)
                    if fp and str(fp.resolve()) == key:
                        _update_tree_row(iid, mid, ctext)
                sel = tree.selection()
                if sel:
                    cue = _cue_at_iid(sel[0])
                    fp_sel = _file_path_for_cue(cue[0]) if cue else None
                    if (
                        fp_sel
                        and str(fp_sel.resolve()) == key
                        and preview_name_var.get() == path.name
                    ):
                        ocr_var.set(text)

            _ui_after(done)

        threading.Thread(target=work, daemon=True).start()

    def show_preview(path: Path) -> None:
        nonlocal _photo
        preview_name_var.set(path.name)
        key = str(path.resolve())
        cached = _ocr_cache.get(key)
        ocr_var.set(cached[0] if cached else "OCR 인식 중…")
        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                w = max(200, preview_frm.winfo_width() - 32)
                h = max(200, int(paned.winfo_height() * 0.55))
                im.thumbnail((w, h), Image.Resampling.LANCZOS)
                _photo = ImageTk.PhotoImage(im)
            thumb_lbl.configure(image=_photo, text="")
        except OSError as e:
            thumb_lbl.configure(image="", text=f"미리보기 실패: {e}")
            _photo = None
        if cached is None and key not in _ocr_pending:
            cue_text = ""
            map_id = 0
            sel = tree.selection()
            if sel:
                cue = _cue_at_iid(sel[0])
                if cue:
                    map_id, cue_text = cue
            if cue_text:
                _schedule_ocr(path, map_id, cue_text)

    def on_tree_select(_e=None) -> None:
        sel = tree.selection()
        if not sel:
            return
        cue = _cue_at_iid(sel[0])
        if not cue:
            return
        map_id, _ = cue
        set_srt_input_for_cue(map_id)
        nxt = format_srt_filename(map_id)
        if not _file_path_for_cue(map_id):
            status_var.set(
                f"대본 {map_id} — Genspark에 대본 붙여넣기 · 다음 다운로드 권장: {nxt}"
            )
        fp = _file_path_for_cue(map_id)
        if fp:
            show_preview(fp)

    tree.bind("<<TreeviewSelect>>", on_tree_select)

    def _rename_cue_file(map_id: int, new_name: str) -> str | None:
        norm = normalize_png_name(new_name)
        if norm is None:
            return "파일명은 SRT_XXX.png 형식이어야 합니다."
        src = _file_path_for_cue(map_id)
        if src is None or not src.is_file():
            return "변경할 이미지 파일이 없습니다."
        dest = png_path() / norm
        if src.resolve() == dest.resolve():
            return None
        if dest.exists():
            return f"이미 있습니다: {norm}"
        try:
            src.rename(dest)
        except OSError as e:
            return str(e)
        old_key = str(src.resolve())
        _ocr_cache.pop(old_key, None)
        _ocr_pending.discard(old_key)
        return None

    def _start_filename_edit(iid: str) -> None:
        _close_cell_editor()
        cue = _cue_at_iid(iid)
        if not cue:
            return
        map_id, _ = cue
        bbox = tree.bbox(iid, _COL_FILE)
        if not bbox:
            return
        x, y, w, h = bbox
        vals = tree.item(iid, "values")
        cur = vals[2] if len(vals) > 2 else format_srt_filename(map_id)

        ent = ttk.Entry(tree)
        nonlocal _cell_editor
        _cell_editor = ent
        ent.place(x=x, y=y, width=w, height=h)
        ent.insert(0, cur)
        ent.select_range(0, tk.END)
        ent.focus_set()

        def commit() -> None:
            val = ent.get().strip()
            _close_cell_editor()
            err = _rename_cue_file(map_id, val)
            if err:
                safe_messagebox(root, "showwarning", "파일명", err)
            norm = normalize_png_name(val)
            refresh_list(select=(png_path() / norm) if norm else None)

        def cancel() -> None:
            _close_cell_editor()

        ent.bind("<Return>", lambda _e: commit())
        ent.bind("<Escape>", lambda _e: cancel())
        ent.bind("<FocusOut>", lambda _e: commit())

    def on_tree_double_click(event: tk.Event) -> None:
        if tree.identify_region(event.x, event.y) != "cell":
            return
        iid = tree.identify_row(event.y)
        col = tree.identify_column(event.x)
        if not iid or col != f"#{_TREE_COLS.index(_COL_FILE) + 1}":
            return
        _start_filename_edit(iid)

    tree.bind("<Double-1>", on_tree_double_click, add="+")

    ttk.Label(
        tab_list,
        text="파일명 더블클릭 수정(즉시 저장) · 대본번호=파일명 숫자 일치 시 이미지 있음 · OCR 불일치 표시",
        font=("", 8),
    ).grid(row=2, column=0, sticky="w", pady=(4, 0))

    # 상태바 (메시지 + 진행바)
    status_frm = ttk.Frame(frm)
    status_frm.grid(row=6, column=0, sticky="ew", pady=(6, 0))
    status_frm.grid_columnconfigure(0, weight=1)
    ttk.Label(status_frm, textvariable=status_var).grid(row=0, column=0, sticky="w")
    progress = ttk.Progressbar(status_frm, mode="determinate", length=220)
    progress.grid(row=0, column=1, sticky="e", padx=(10, 0))

    def _persist_settings() -> None:
        try:
            save_gui_settings(
                png_dir=png_var.get().strip(),
                srt_file=srt_var.get().strip(),
                preview_pane_width=max(280, paned.winfo_width() - paned.sashpos(0)),
                genspark_prompt_selector=prompt_sel_var.get().strip(),
                image_guide=_current_guide_file(),
            )
        except (OSError, tk.TclError):
            pass

    def on_close() -> None:
        nonlocal _closing, watcher
        if _closing:
            return
        _closing = True
        _close_cell_editor()
        _ocr_pending.clear()
        if watcher:
            watcher.stop()
            watcher = None
        _persist_settings()

    bind_close(root, standalone, on_close)
    if not standalone:
        bind_hub_destroy(root, on_close)

    reload_guide_text()
    reload_srt_input_full()
    restart_watcher()
    refresh_list()
    root.after(120, _apply_pane_sash)
    run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
