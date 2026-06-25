# -*- coding: utf-8 -*-
"""SRT ↔ PNG 글자 매칭 → SRT_XXX.png 이름 변경 GUI."""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import threading
import traceback
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from png_rename import __version__
from png_rename.naming import srt_png_name
from png_rename.paths import (
    default_download_dir,
    default_png_dir,
    default_srt_file,
    resolve_initial_download_dir,
    resolve_initial_png_dir,
    resolve_initial_srt,
)
from png_rename.srt_parse import parse_srt_cues, search_srt_cues
from png_rename.rename import (
    MatchPreview,
    RenameResult,
    RenameSkip,
    ScanCancelledError,
    apply_match_renames,
    apply_ocr_to_row,
    apply_srt_filename_normalizations,
    build_srt_centric_skeleton,
    ensure_all_cue_rows,
    filename_matches_script_number,
    find_srt_filename_normalizations,
    iter_png_files,
    remap_all_rows_from_filenames,
    scan_srt_centric_matches,
)
from png_rename.text_norm import (
    collect_ocr_mapping_candidates,
    cue_ids_for_word,
    format_ocr_mapping_display,
    normalize_text,
    ocr_words_in_cue_text,
    split_ocr_words_for_mapping,
)
from png_rename.settings import (
    load_download_image_inputs,
    load_gui_settings,
    load_manual_overrides,
    save_download_image_inputs,
    save_gui_settings,
    save_manual_overrides,
)
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

_COL_SEL = "sel"
_COL_CURRENT = "current"
_COL_WORD_SRT = "word_srt"
_COL_MATCH = "match_ok"
_COL_MATCH_REASON = "match_reason"
_COL_APPLY = "apply_map"
_COL_SRT = "srt_no"
_COL_CUE = "cue"
_COL_STATUS = "status"
_COL_DOWNLOAD = "download_img"
_THUMB_MAX = 560
_APPLY_NEIGHBOR_ROWS = 5
_THUMB_SIZE_MIN = 80
_THUMB_SIZE_MAX = 1200
_VIEWER_SCREEN_RATIO = 0.92
_SRT_NUM_IN_NAME = re.compile(r"(?:^|[^0-9])srt[-_ ]?0*(\d+)(?:[^0-9]|$)", re.IGNORECASE)
_OCR_MATCH_BG = "#fff59d"
_SKIP_NO_SOURCE = "__skip_no_source__"


def _center_modal_toplevel(win: tk.Toplevel, parent: tk.Misc) -> None:
    """부모 최상위 창(듀얼 모니터 포함) 기준 화면 정중앙에 모달 배치."""
    host = parent.winfo_toplevel()
    win.update_idletasks()
    host.update_idletasks()
    ww = max(win.winfo_width(), win.winfo_reqwidth(), 1)
    wh = max(win.winfo_height(), win.winfo_reqheight(), 1)
    hx = host.winfo_rootx()
    hy = host.winfo_rooty()
    hw = max(host.winfo_width(), 1)
    hh = max(host.winfo_height(), 1)
    x = hx + max(0, (hw - ww) // 2)
    y = hy + max(0, (hh - wh) // 2)
    win.geometry(f"+{x}+{y}")
    win.focus_force()


def _ocr_preview_tokens(ocr_preview: str) -> list[str]:
    return [p.strip() for p in (ocr_preview or "").split(",") if p.strip()]


def _ocr_token_matches_cue(word: str, cue_text: str) -> bool:
    if not word or not (cue_text or "").strip():
        return False
    norm_cue = normalize_text(cue_text)
    if not norm_cue:
        return False
    nw = normalize_text(word)
    if len(nw) >= 2 and nw in norm_cue:
        return True
    for run in re.finditer(r"[가-힣]{2,}|[A-Za-z0-9]{2,}", word):
        if normalize_text(run.group(0)) in norm_cue:
            return True
    return False


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def main(
    *,
    container: tk.Misc | None = None,
    initial_srt: Path | None = None,
    initial_png_dir: Path | None = None,
) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_hub_destroy,
        run_mainloop,
        safe_after,
        tk_host,
    )
    if initial_srt is None and initial_png_dir is None and len(sys.argv) > 1:
        p = argparse.ArgumentParser(add_help=False)
        p.add_argument("--srt", type=Path, default=None)
        p.add_argument("--png-dir", type=Path, default=None)
        ns, _ = p.parse_known_args()
        initial_srt = ns.srt
        initial_png_dir = ns.png_dir

    cfg = load_gui_settings()
    srt_default = resolve_initial_srt(initial_srt, cfg.get("srt_file"))
    png_default = resolve_initial_png_dir(initial_png_dir, cfg.get("png_dir"))
    download_default = resolve_initial_download_dir(None, cfg.get("download_dir"))
    thumb_size = [_THUMB_MAX]
    try:
        thumb_size[0] = int(cfg.get("preview_thumb_size", str(_THUMB_MAX)))
    except ValueError:
        pass
    thumb_size[0] = max(_THUMB_SIZE_MIN, min(_THUMB_SIZE_MAX, thumb_size[0]))

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"3_1_pngFileName {__version__}",
        minsize=(1200, 640),
        geometry="1320x720",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    srt_var = tk.StringVar(value=str(srt_default))
    png_var = tk.StringVar(value=str(png_default))
    download_var = tk.StringVar(value=str(download_default))
    recursive_var = tk.BooleanVar(value=False)
    skip_already_named = True
    target_count_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="")
    _search_win: tk.Toplevel | None = None
    manual_overrides: dict[str, dict] = load_manual_overrides()
    download_image_inputs: dict[str, str] = load_download_image_inputs()
    srt_name_choices: list[str] = []
    srt_number_choices: list[str] = []
    srt_cue_map: dict[int, str] = {}
    _filter_detached: set[str] = set()

    rows_by_iid: dict[str, MatchPreview] = {}
    selected_iids: set[str] = set()
    selected_row_ids: set[int] = set()
    _all_rows_cache: list[MatchPreview] = []
    _ocr_pending: set[int] = set()
    _ocr_cache_keys: set[str] = set()
    _rename_source_by_row: dict[int, Path] = {}
    _thumb_photo: tk.PhotoImage | None = None
    _preview_path: Path | None = None
    _preview_ocr: str = ""
    _ocr_apply_source_iid: str | None = None
    _ocr_apply_srt_numbers: set[int] = set()
    _last_sel_iid_for_apply: str | None = None

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    browse_widgets: list[tk.Widget] = []
    action_widgets: list[tk.Widget] = []

    def row_file(
        label: str,
        var: tk.StringVar,
        row: int,
        *,
        is_dir: bool,
        filetypes: list[tuple[str, str]] | None = None,
    ) -> None:
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=(0, 4))
        rf = ttk.Frame(frm)
        rf.grid(row=row + 1, column=0, sticky="ew", pady=(0, 8))
        rf.grid_columnconfigure(0, weight=1)
        ent = ttk.Entry(rf, textvariable=var)
        ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        def pick() -> None:
            cur = var.get().strip()
            if is_dir:
                init = folder_dialog_initial(
                    Path(cur) if cur and Path(cur).is_dir() else default_png_dir(),
                )
                p = filedialog.askdirectory(title=label, initialdir=init)
            else:
                init = folder_dialog_initial(
                    Path(cur).parent if cur and Path(cur).parent.is_dir() else default_srt_file().parent,
                )
                ft = filetypes or [("SRT", "*.srt"), ("모든 파일", "*.*")]
                p = filedialog.askopenfilename(
                    title=label,
                    initialdir=init,
                    filetypes=ft,
                )
            if p:
                touch_workspace_from_path(p)
                var.set(p)
                refresh_count()
                persist()

        btn = ttk.Button(rf, text="찾아보기…", command=pick)
        btn.grid(row=0, column=1)
        browse_widgets.extend([ent, btn])

    def refresh_count() -> None:
        png = Path(png_var.get().strip())
        if not png.is_dir():
            target_count_var.set("(폴더 없음)")
            return
        try:
            n = len(iter_png_files(png, recursive=bool(recursive_var.get())))
        except OSError:
            target_count_var.set("(오류)")
            return
        sub = "하위 포함" if recursive_var.get() else "현재 폴더만"
        target_count_var.set(f"PNG {n}개 ({sub})")

    def clear_table() -> None:
        rows_by_iid.clear()
        selected_iids.clear()
        selected_row_ids.clear()
        _all_rows_cache.clear()
        _ocr_pending.clear()
        _ocr_cache_keys.clear()
        _rename_source_by_row.clear()
        _filter_detached.clear()
        for iid in tree.get_children():
            tree.delete(iid)
        clear_preview()
        clear_keyword_filter()

    def clear_preview() -> None:
        nonlocal _thumb_photo, _preview_path, _preview_ocr
        _thumb_photo = None
        _preview_path = None
        _preview_ocr = ""
        thumb_img_lbl.configure(image="", text="(미리보기 없음)")
        preview_name_var.set("")
        preview_ocr_var.set("")
        preview_cue_var.set("")
        _fill_preview_ocr_text("", "")

    def _format_ocr_display(row: MatchPreview) -> str:
        text = (row.ocr_preview or "").strip()
        if text:
            n = len(_ocr_preview_tokens(text))
            return f"{text}  ({n}개 단어)"
        return "(인식된 단어 없음 — 이미지에 글자가 없거나 OCR 인식 실패)"

    def _fill_preview_ocr_text(ocr_preview: str, cue_text: str) -> None:
        preview_ocr_txt.config(state=tk.NORMAL)
        preview_ocr_txt.delete("1.0", tk.END)
        tokens = _ocr_preview_tokens(ocr_preview)
        if not tokens:
            preview_ocr_txt.insert(
                tk.END,
                "(인식된 단어 없음 — 이미지에 글자가 없거나 OCR 인식 실패)",
                "empty",
            )
        else:
            matched_set = set()
            _, matched_list = ocr_words_in_cue_text(ocr_preview, cue_text or "")
            for m in matched_list:
                matched_set.add(m.strip())
            for i, word in enumerate(tokens):
                if i > 0:
                    preview_ocr_txt.insert(tk.END, ", ", "sep")
                tag = (
                    "match"
                    if word in matched_set or _ocr_token_matches_cue(word, cue_text)
                    else "normal"
                )
                preview_ocr_txt.insert(tk.END, word, tag)
        preview_ocr_txt.config(state=tk.DISABLED)

    def open_large_viewer(
        path: Path | None,
        *,
        title_extra: str = "",
        ocr_words: str = "",
    ) -> None:
        if path is None or not path.is_file():
            messagebox.showwarning("미리보기", "표시할 이미지 파일이 없습니다.")
            return
        try:
            from PIL import Image, ImageTk
        except ImportError:
            messagebox.showerror("미리보기", "Pillow 가 필요합니다.")
            return

        win = tk.Toplevel(root)
        win.title(path.name + (f" — {title_extra}" if title_extra else ""))
        win.transient(root)
        frm_img = ttk.Frame(win, padding=8)
        frm_img.pack(fill=tk.BOTH, expand=True)

        try:
            with Image.open(path) as im:
                im = im.convert("RGB")
                iw, ih = im.size
                max_w = max(400, int(root.winfo_screenwidth() * _VIEWER_SCREEN_RATIO))
                max_h = max(300, int(root.winfo_screenheight() * _VIEWER_SCREEN_RATIO))
                scale = min(max_w / iw, max_h / ih)
                nw = max(1, int(iw * scale))
                nh = max(1, int(ih * scale))
                if (nw, nh) != (iw, ih):
                    im = im.resize((nw, nh), Image.Resampling.LANCZOS)
                photo = ImageTk.PhotoImage(im)
        except OSError as e:
            win.destroy()
            messagebox.showerror("미리보기", f"이미지를 열 수 없습니다.\n{e}")
            return

        lbl = tk.Label(frm_img, image=photo, cursor="hand2")
        lbl.image = photo
        lbl.pack()
        win._viewer_photo = photo  # type: ignore[attr-defined]

        ttk.Label(frm_img, text=f"{path.name}  ({iw}×{ih})", wraplength=max_w).pack(
            pady=(6, 0)
        )
        ocr_show = (ocr_words or "").strip().replace("\n", " ")
        if ocr_show:
            ttk.Label(
                frm_img,
                text=f"OCR 식별 단어: {ocr_show}",
                wraplength=max_w,
                foreground="#1565c0",
            ).pack(anchor=tk.W, pady=(6, 0))
        ttk.Label(frm_img, text="더블클릭 또는 Esc 로 닫기", foreground="#666666").pack(
            pady=(4, 0)
        )

        def close(_event: tk.Event | None = None) -> None:
            try:
                win.destroy()
            except tk.TclError:
                pass

        win.bind("<Escape>", close)
        lbl.bind("<Double-1>", close)
        win.protocol("WM_DELETE_WINDOW", close)
        win.update_idletasks()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")

    def _preview_image_path(row: MatchPreview) -> Path:
        """미리보기 = 현재파일명(대본번호와 일치하는 파일)."""
        path = _current_file_path(row)
        if path is not None:
            return path
        if row.srt_number >= 0:
            return _png_parent(row) / srt_png_name(row.srt_number)
        return row.source

    def show_preview_for_iid(iid: str | None) -> None:
        nonlocal _thumb_photo, _preview_path, _preview_ocr
        if not iid or iid not in rows_by_iid:
            clear_preview()
            return
        row = rows_by_iid[iid]
        current_name = _mapped_current_display(row)
        path = _current_file_path(row)
        _preview_path = path
        ocr = row.ocr_preview.strip().replace("\n", " ")
        _preview_ocr = ocr
        if current_name:
            preview_name_var.set(current_name)
        else:
            preview_name_var.set("")
        _fill_preview_ocr_text(row.ocr_preview, row.cue_text)
        cue = row.cue_text.strip()
        word_cue = row.word_cue_text.strip()
        word_no = (
            str(row.word_srt_number) if row.word_srt_number >= 0 else "—"
        )
        parts: list[str] = []
        if word_cue:
            parts.append(f"[단어 발생 · {word_no}번] {word_cue}")
        if cue:
            parts.append(f"[매칭 대본 · {row.srt_number}번] {cue}" if row.srt_number >= 0 else f"[매칭 대본] {cue}")
        preview_cue_var.set("\n\n".join(parts) if parts else row.status)

        if path is None or not path.is_file():
            _thumb_photo = None
            thumb_img_lbl.configure(image="", text="파일 없음")
            return

        try:
            from PIL import Image, ImageTk

            with Image.open(path) as im:
                im = im.convert("RGB")
                im.thumbnail(
                    (thumb_size[0], thumb_size[0]),
                    Image.Resampling.LANCZOS,
                )
                _thumb_photo = ImageTk.PhotoImage(im)
            thumb_img_lbl.configure(image=_thumb_photo, text="")
        except OSError as e:
            _thumb_photo = None
            thumb_img_lbl.configure(image="", text=f"이미지 열기 실패\n{e}")

    def _sel_mark(on: bool) -> str:
        return "☑" if on else "☐"

    def _sync_cue_text(row: MatchPreview) -> None:
        if row.srt_number < 0:
            return
        cue = srt_cue_map.get(int(row.srt_number))
        if cue is None:
            row.cue_text = f"(대본 {row.srt_number}번 — SRT 미등록)"
            return
        row.cue_text = cue.strip().replace("\n", " ")

    def _png_parent(row: MatchPreview) -> Path:
        if row.source.is_file():
            return row.source.parent
        if row.srt_number >= 0:
            return row.source.parent
        return row.source.parent

    def _expected_srt_filename(row: MatchPreview) -> str | None:
        if row.srt_number < 0:
            return None
        return srt_png_name(row.srt_number)

    def _current_file_path(row: MatchPreview) -> Path | None:
        """행에 연결된 실제 PNG (근접 매핑 파일명 포함)."""
        if row.source.is_file():
            return row.source
        if row.srt_number >= 0:
            expected = _png_parent(row) / srt_png_name(row.srt_number)
            return expected if expected.is_file() else None
        return None

    def _sync_row_source_from_disk(row: MatchPreview) -> None:
        """``row.source`` 를 대본번호에 맞는 실제 파일 경로에 맞춤."""
        base = _png_parent(row)
        if row.srt_number >= 0:
            expected = base / srt_png_name(row.srt_number)
            if expected.is_file():
                row.source = expected
            elif row.source.is_file():
                pass  # 번호와 다른 이름의 실제 파일 유지(저장 시 rename 가능)
            else:
                row.source = expected
            return
        if row.source.is_file():
            return

    def _resolve_rename_source(row: MatchPreview) -> Path | None:
        """이름 변경할 원본 PNG 경로."""
        if row.source.is_file():
            return row.source
        path = _current_file_path(row)
        if path is not None and path.is_file():
            return path
        return None

    def _normalize_target_name(raw: str) -> str | None:
        raw = (raw or "").strip()
        if not raw or raw == "—":
            return None
        parsed = _target_from_filename(raw)
        if parsed is not None:
            return parsed[1]
        return None

    def _prepare_row_for_rename(row: MatchPreview) -> str | None:
        """저장 전 행 준비. 실패 시 오류 메시지."""
        tgt = _normalize_target_name(row.target_name)
        if tgt is None:
            raw = (row.target_name or "").strip()
            stem = Path(raw).name
            if stem.lower().endswith(".png") and stem not in ("", "—"):
                tgt = stem
            else:
                return "현재파일명이 SRT_XXX.png 형식이 아닙니다"
        src = _rename_source_by_row.pop(id(row), None)
        if src is None or not src.is_file():
            src = _resolve_rename_source(row)
        if src is None:
            row.target_name = tgt
            n = _name_srt_num(tgt)
            if n is not None:
                row.srt_number = n
                _sync_cue_text(row)
            row.can_rename = False
            return _SKIP_NO_SOURCE
        try:
            if src.resolve() == (src.parent / tgt).resolve():
                return "이미 해당 파일명입니다"
        except OSError:
            pass
        dst = src.parent / tgt
        if dst.exists():
            try:
                if dst.resolve() != src.resolve():
                    return f"대상 파일 존재: {tgt}"
            except OSError:
                return f"대상 파일 존재: {tgt}"
        row.source = src
        row.target_name = tgt
        n = _name_srt_num(tgt)
        if n is not None:
            row.srt_number = n
            _sync_cue_text(row)
        row.can_rename = True
        return None

    def _rename_row_filename_now(row: MatchPreview, iid: str) -> bool:
        """현재파일명 편집 즉시 디스크 rename (콤보·② 저장 없음)."""
        err = _prepare_row_for_rename(row)
        if err == "이미 해당 파일명입니다":
            row.status = "이미 해당 파일명 (변경 없음)"
            _sync_row_match_fields(row)
            _refresh_row_display(iid, row)
            status_var.set("파일명이 이미 동일합니다.")
            return True
        if err == _SKIP_NO_SOURCE:
            row.status = f"변경 지정: {row.target_name} (저장 대기)"
            _sync_row_match_fields(row)
            _refresh_row_display(iid, row)
            _save_row_override(row)
            status_var.set(f"변경 지정: {row.target_name} (저장 대기)")
            return True
        if err:
            messagebox.showwarning("저장 실패", err)
            return False
        try:
            results, skips = apply_match_renames([row], manual=True)
        except Exception as e:
            messagebox.showerror("저장 실패", str(e))
            return False
        if skips and not results:
            messagebox.showwarning("저장 실패", skips[0].reason)
            return False
        if not results:
            return False
        _apply_rename_to_row(row, results[0])
        _sync_row_match_fields(row)
        row.status = f"즉시 저장 완료: {row.target_name}"
        try:
            _ocr_cache_keys.discard(_ocr_cache_key(results[0].source))
        except OSError:
            pass
        _ocr_cache_keys.add(_ocr_cache_key(results[0].target))
        _rename_source_by_row.pop(id(row), None)
        _save_row_override(row)
        refresh_count()
        reload_table(
            status_msg=f"파일명 즉시 저장: {results[0].target.name}",
            quiet=True,
        )
        return True

    def _auto_resolve_row_mapping_for_save(row: MatchPreview) -> str | None:
        """② 저장 시 OCR 매핑 콤보 없이 번호 확정. 사용자가 지정한 target_name 우선."""
        norm_tgt = _normalize_target_name(row.target_name)
        if norm_tgt is not None:
            row.target_name = norm_tgt
            n = _name_srt_num(norm_tgt)
            if n is not None:
                row.srt_number = n
                _sync_cue_text(row)
            return None

        candidates = _mapping_candidates_for_row(row)
        if not candidates:
            return None
        if row.srt_number in candidates:
            row.target_name = srt_png_name(row.srt_number)
            return None
        if len(candidates) == 1:
            row.srt_number = candidates[0]
            _sync_cue_text(row)
            row.target_name = srt_png_name(row.srt_number)
            return None
        if row.srt_number >= 0 and row.srt_number in srt_cue_map:
            row.target_name = srt_png_name(row.srt_number)
            return None
        row.srt_number = candidates[0]
        _sync_cue_text(row)
        row.target_name = srt_png_name(row.srt_number)
        return None

    def _sync_row_match_fields(row: MatchPreview) -> None:
        cues = sorted(((int(k), v) for k, v in srt_cue_map.items()), key=lambda c: c[0])
        if (row.ocr_preview or "").strip():
            row.match_reason = format_ocr_mapping_display(row.ocr_preview, cues)
        elif not (row.match_reason or "").strip():
            row.match_reason = "—"
        pending = _pending_target_name(row)
        if pending:
            n_tgt = _name_srt_num(pending)
            row.matched = n_tgt is not None and n_tgt == row.srt_number
        else:
            row.matched = filename_matches_script_number(row)

    def _mapping_candidates_for_row(row: MatchPreview) -> list[int]:
        cues = sorted(((int(k), v) for k, v in srt_cue_map.items()), key=lambda c: c[0])
        return collect_ocr_mapping_candidates(row.ocr_preview, cues)

    def _mapping_popup_row_items(row: MatchPreview) -> list[tuple[str, int, str]]:
        cues = sorted(((int(k), v) for k, v in srt_cue_map.items()), key=lambda c: c[0])
        cue_map_local = {int(k): v for k, v in srt_cue_map.items()}
        words = split_ocr_words_for_mapping(row.ocr_preview, cues)
        rows_local: list[tuple[str, int, str]] = []
        seen: set[tuple[str, int]] = set()
        for w in words:
            for mid in cue_ids_for_word(w, cues):
                key = (w, mid)
                if key in seen:
                    continue
                seen.add(key)
                cue_one = (cue_map_local.get(mid, "") or "").strip().replace("\n", " ")
                rows_local.append((w, mid, cue_one))
        rows_local.sort(key=lambda item: item[1])
        return rows_local

    def _open_mapping_popup_for_row(iid: str) -> None:
        row = rows_by_iid.get(iid)
        if row is None:
            return
        if not (row.ocr_preview or "").strip():
            schedule_row_ocr(iid)
            status_var.set("OCR 인식 후 매핑 팝업을 여세요. 잠시 후 다시 클릭하세요.")
            return
        candidates = _mapping_candidates_for_row(row)
        if not candidates:
            messagebox.showinfo("OCR 매핑", "매핑 가능한 대본 번호가 없습니다.")
            return
        rows_local = _mapping_popup_row_items(row)
        if not rows_local:
            messagebox.showinfo("OCR 매핑", "매핑 가능한 대본 번호가 없습니다.")
            return
        _set_ocr_apply_context(iid, {mid for _w, mid, _c in rows_local})
        picked = _choose_mapping_candidate_with_words(
            row, candidates, iid, rows_local
        )
        if picked is None:
            return
        status_var.set(f"OCR매핑 적용값 설정: 대본 {picked}번 (저장 대기)")

    def _ensure_row_mapping_selected(row: MatchPreview) -> str | None:
        """다중 OCR 매핑 번호면 저장 전 선택. 취소·미선택 시 오류 메시지."""
        candidates = _mapping_candidates_for_row(row)
        if len(candidates) <= 1:
            if len(candidates) == 1:
                if row.srt_number != candidates[0]:
                    row.srt_number = candidates[0]
                    _sync_cue_text(row)
                if not (row.target_name or "").strip() or row.target_name == "—":
                    row.target_name = srt_png_name(row.srt_number)
            return None
        tgt = (row.target_name or "").strip()
        if row.srt_number in candidates and tgt not in ("", "—"):
            return None
        picked = _choose_mapping_candidate(
            candidates,
            row.srt_number if row.srt_number in candidates else candidates[0],
        )
        if picked is None:
            return "OCR 매핑 번호를 선택하지 않았습니다"
        row.srt_number = picked
        _sync_cue_text(row)
        row.target_name = srt_png_name(row.srt_number)
        _sync_row_match_fields(row)
        return None

    def _pending_target_name(row: MatchPreview) -> str | None:
        tgt = (row.target_name or "").strip()
        if tgt in ("", "—"):
            return None
        return tgt

    def _disk_file_name(row: MatchPreview) -> str:
        path = _current_file_path(row)
        if path is None or not path.is_file():
            return ""
        return path.name

    def _mapped_current_display(row: MatchPreview) -> str:
        """현재파일명: 디스크 이름 + 저장 대기 목표."""
        disk = _disk_file_name(row)
        pending = _pending_target_name(row)
        if pending and disk and pending != disk:
            return f"{disk} → {pending}"
        if pending:
            return pending
        return disk

    def _edit_current_filename_value(row: MatchPreview) -> str:
        pending = _pending_target_name(row)
        if pending:
            return pending
        return _disk_file_name(row)

    def _download_img_key(row: MatchPreview) -> str:
        if row.srt_number >= 0:
            return str(row.srt_number)
        try:
            return _override_key(row.source)
        except OSError:
            return str(id(row))

    def _download_img_display(row: MatchPreview) -> str:
        return download_image_inputs.get(_download_img_key(row), "")

    def _target_filename_for_download(row: MatchPreview) -> str | None:
        pending = _pending_target_name(row)
        if pending:
            return pending
        if row.srt_number >= 0:
            return srt_png_name(row.srt_number)
        disk = _disk_file_name(row)
        if disk:
            norm = _normalize_target_name(disk)
            return norm or disk
        return None

    def _find_download_source(name: str) -> Path | None:
        dl = Path(download_var.get().strip())
        if not dl.is_dir():
            return None
        raw = name.strip()
        if not raw:
            return None
        direct = dl / raw
        if direct.is_file():
            return direct
        stem = Path(raw).stem
        if stem and stem != raw:
            for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
                cand = dl / f"{stem}{ext}"
                if cand.is_file():
                    return cand
        if not Path(raw).suffix:
            for ext in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"):
                cand = dl / f"{raw}{ext}"
                if cand.is_file():
                    return cand
        low = raw.lower()
        try:
            for child in dl.iterdir():
                if child.is_file() and child.name.lower() == low:
                    return child
        except OSError:
            return None
        return None

    def _copy_download_image_to_row(row: MatchPreview, source_name: str) -> str | None:
        """다운로드 폴더 이미지 → PNG 폴더(현재파일명). 성공 시 None, 실패 시 메시지."""
        png = Path(png_var.get().strip())
        if not png.is_dir():
            return f"PNG 폴더가 없습니다: {png}"
        dl = Path(download_var.get().strip())
        if not dl.is_dir():
            return f"다운로드 폴더가 없습니다: {dl}"
        src = _find_download_source(source_name)
        if src is None:
            return f"다운로드 폴더에 파일이 없습니다: {source_name}"
        tgt_name = _target_filename_for_download(row)
        if not tgt_name:
            return "현재파일명(대본번호·SRT_XXX.png)을 먼저 지정하세요."
        dest = png / tgt_name
        try:
            if dest.exists() and dest.resolve() != src.resolve():
                dest.unlink()
            shutil.copy2(src, dest)
        except OSError as e:
            return str(e)
        row.source = dest
        row.target_name = tgt_name
        n = _name_srt_num(tgt_name)
        if n is not None:
            row.srt_number = n
            _sync_cue_text(row)
        row.can_rename = True
        row.status = f"다운로드 복사: {tgt_name}"
        _sync_row_match_fields(row)
        return None

    def _row_show_apply_button(row: MatchPreview) -> bool:
        """OCR·대본 일치, OCR매핑 팝업 대본번호, 선택 행 ±5 이웃이면 적용 표시."""
        row_iid = str(id(row))
        sel = tree.selection()
        if sel and sel[0] in rows_by_iid:
            kids = list(tree.get_children(""))
            if row_iid in kids and sel[0] in kids:
                sel_idx = kids.index(sel[0])
                row_idx = kids.index(row_iid)
                if (
                    row_iid != sel[0]
                    and abs(row_idx - sel_idx) <= _APPLY_NEIGHBOR_ROWS
                ):
                    return True
        if (
            _ocr_apply_source_iid
            and row_iid != _ocr_apply_source_iid
            and row.srt_number in _ocr_apply_srt_numbers
        ):
            return True
        ocr = (row.ocr_preview or "").strip()
        cue = (row.cue_text or "").strip()
        if not ocr or not cue:
            return False
        in_cue, _matched = ocr_words_in_cue_text(ocr, cue)
        return in_cue

    def _insert_row(row: MatchPreview, *, default_checked: bool) -> None:
        iid = str(id(row))
        rows_by_iid[iid] = row
        checked = default_checked or id(row) in selected_row_ids
        if checked:
            selected_iids.add(iid)
            selected_row_ids.add(id(row))
        _sync_cue_text(row)
        _sync_row_match_fields(row)
        srt_disp = str(row.srt_number) if row.srt_number >= 0 else "—"
        cue_disp = (row.cue_text or "—")[:160]
        current_disp = _mapped_current_display(row)
        map_disp = (row.match_reason or "—")[:160]
        apply_disp = "적용" if _row_show_apply_button(row) else ""
        download_disp = _download_img_display(row)[:80]
        tags: tuple[str, ...] = ()
        if not row.can_rename and not row.ocr_preview:
            tags = ("muted",)
        elif filename_matches_script_number(row):
            tags = ("matched",)
        else:
            tags = ("unmatched",)
        tree.insert(
            "",
            tk.END,
            iid=iid,
            values=(
                _sel_mark(checked),
                srt_disp,
                cue_disp,
                current_disp,
                apply_disp,
                row.match_label,
                row.status,
                download_disp,
                map_disp,
            ),
            tags=tags,
        )

    def _update_sel_cell(iid: str) -> None:
        row = rows_by_iid.get(iid)
        vals = list(tree.item(iid, "values"))
        vals[0] = _sel_mark(row is not None and id(row) in selected_row_ids)
        tree.item(iid, values=vals)

    def toggle_iid(iid: str) -> None:
        if iid not in rows_by_iid:
            return
        row = rows_by_iid[iid]
        rid = id(row)
        if rid in selected_row_ids:
            selected_row_ids.discard(rid)
            selected_iids.discard(iid)
        else:
            selected_row_ids.add(rid)
            selected_iids.add(iid)
        _update_sel_cell(iid)

    def set_all_checked(checked: bool) -> None:
        for iid, row in rows_by_iid.items():
            rid = id(row)
            if checked:
                selected_row_ids.add(rid)
                selected_iids.add(iid)
            else:
                selected_row_ids.discard(rid)
                selected_iids.discard(iid)
            _update_sel_cell(iid)

    def set_all_matched(checked: bool) -> None:
        for iid, row in rows_by_iid.items():
            if not row.can_rename:
                continue
            rid = id(row)
            if checked:
                selected_row_ids.add(rid)
                selected_iids.add(iid)
            else:
                selected_row_ids.discard(rid)
                selected_iids.discard(iid)
            _update_sel_cell(iid)

    def _collect_delete_targets() -> list[MatchPreview]:
        """☑ 체크(모든 페이지) + 현재 페이지에서 클릭한 줄."""
        seen: set[Path] = set()
        out: list[MatchPreview] = []
        for row in _all_rows_cache:
            if id(row) not in selected_row_ids:
                continue
            path = _current_file_path(row)
            if path is None or path in seen:
                continue
            seen.add(path)
            out.append(row)
        for iid in tree.selection():
            row = rows_by_iid.get(iid)
            if row is None:
                continue
            path = _current_file_path(row)
            if path is None or path in seen:
                continue
            seen.add(path)
            out.append(row)
        return out

    row_file("대본 SRT 파일", srt_var, 0, is_dir=False)
    row_file("PNG 폴더 (이름 변경 위치)", png_var, 2, is_dir=True)

    ttk.Label(frm, text="다운로드 폴더").grid(row=4, column=0, sticky="w", pady=(0, 4))
    download_rf = ttk.Frame(frm)
    download_rf.grid(row=5, column=0, sticky="ew", pady=(0, 8))
    download_rf.grid_columnconfigure(0, weight=1)
    download_ent = ttk.Entry(download_rf, textvariable=download_var)
    download_ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))

    def pick_download_dir() -> None:
        cur = download_var.get().strip()
        init = folder_dialog_initial(
            Path(cur) if cur and Path(cur).is_dir() else default_download_dir(),
        )
        p = filedialog.askdirectory(title="다운로드 폴더", initialdir=init)
        if p:
            download_var.set(p)
            persist()

    btn_dl = ttk.Button(download_rf, text="찾아보기…", command=pick_download_dir)
    btn_dl.grid(row=0, column=1)
    browse_widgets.extend([download_ent, btn_dl])

    ttk.Label(
        frm,
        text="OCR매핑 번호 클릭 → 매핑 · 적용=선택 행 저장 · 다운로드이미지 입력+Enter=PNG 복사 · 썸네일·현재파일명 더블클릭.",
    ).grid(row=6, column=0, sticky="w", pady=(0, 6))

    frm.grid_columnconfigure(0, weight=1)

    row_target = ttk.Frame(frm)
    row_target.grid(row=7, column=0, sticky="ew", pady=(0, 6))
    ttk.Label(row_target, text="대상:").pack(side=tk.LEFT)
    ttk.Label(row_target, textvariable=target_count_var).pack(side=tk.LEFT, padx=(6, 12))
    ttk.Button(row_target, text="PNG 개수 확인", command=refresh_count).pack(side=tk.LEFT)

    opts = ttk.Frame(frm)
    opts.grid(row=8, column=0, sticky="ew", pady=(0, 6))
    ttk.Checkbutton(
        opts, text="하위 폴더 포함", variable=recursive_var, command=refresh_count
    ).pack(side=tk.LEFT)

    table_frm = ttk.Frame(frm)
    table_frm.grid(row=10, column=0, sticky="nsew", pady=(0, 6))
    frm.grid_rowconfigure(10, weight=1)
    table_frm.grid_columnconfigure(0, weight=1)
    table_frm.grid_rowconfigure(0, weight=1)

    _default_preview_w = 580
    try:
        _default_preview_w = int(cfg.get("preview_pane_width", "580"))
    except ValueError:
        pass
    _default_preview_w = max(240, min(1200, _default_preview_w))
    preview_pane_width = [_default_preview_w]

    table_body = ttk.Frame(table_frm)
    table_body.grid(row=0, column=0, sticky="nsew")
    table_body.grid_columnconfigure(0, weight=1)
    table_body.grid_columnconfigure(1, weight=0, minsize=preview_pane_width[0])
    table_body.grid_rowconfigure(0, weight=1)

    list_frm = ttk.Frame(table_body)
    preview_frm = ttk.Frame(table_body, padding=8)
    list_frm.grid(row=0, column=0, sticky="nsew")
    preview_frm.grid(row=0, column=1, sticky="nsew")

    list_frm.grid_columnconfigure(0, weight=1)
    list_frm.grid_rowconfigure(0, weight=1)

    ttk.Label(preview_frm, text="미리보기").pack(anchor=tk.W, pady=(0, 4))

    preview_name_var = tk.StringVar(value="")
    preview_ocr_var = tk.StringVar(value="")
    preview_cue_var = tk.StringVar(value="")
    thumb_size_var = tk.IntVar(value=thumb_size[0])
    thumb_ctrl = ttk.Frame(preview_frm)
    thumb_ctrl.pack(anchor=tk.W, fill=tk.X, pady=(0, 4))
    ttk.Label(thumb_ctrl, text="썸네일 크기(px)").pack(side=tk.LEFT)

    def _apply_thumb_size_from_ui() -> None:
        try:
            n = int(thumb_size_var.get())
        except (tk.TclError, ValueError):
            return
        n = max(_THUMB_SIZE_MIN, min(_THUMB_SIZE_MAX, n))
        if thumb_size[0] == n:
            return
        thumb_size[0] = n
        thumb_size_var.set(n)
        persist()
        sel = tree.selection()
        if sel and sel[0] in rows_by_iid:
            show_preview_for_iid(sel[0])

    thumb_spin = ttk.Spinbox(
        thumb_ctrl,
        from_=_THUMB_SIZE_MIN,
        to=_THUMB_SIZE_MAX,
        increment=20,
        width=6,
        textvariable=thumb_size_var,
        command=_apply_thumb_size_from_ui,
    )
    thumb_spin.pack(side=tk.LEFT, padx=(6, 0))
    ttk.Button(
        thumb_ctrl, text="적용", width=5, command=_apply_thumb_size_from_ui
    ).pack(side=tk.LEFT, padx=(4, 0))
    thumb_img_lbl = ttk.Label(preview_frm, text="행을 클릭하세요.", anchor=tk.CENTER)
    thumb_img_lbl.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
    preview_name_lbl = ttk.Label(preview_frm, textvariable=preview_name_var)
    preview_name_lbl.pack(anchor=tk.W, fill=tk.X)
    ttk.Label(preview_frm, text="OCR 조합 단어 (정확도 순 · 노란=대본 일치)", foreground="#1565c0").pack(
        anchor=tk.W, fill=tk.X, pady=(6, 0)
    )
    preview_ocr_txt = tk.Text(
        preview_frm,
        height=4,
        wrap=tk.WORD,
        font=("", 9),
        relief=tk.FLAT,
        borderwidth=1,
        highlightthickness=1,
        state=tk.DISABLED,
        cursor="arrow",
    )
    preview_ocr_txt.tag_configure("match", background=_OCR_MATCH_BG)
    preview_ocr_txt.tag_configure("normal", foreground="#1565c0")
    preview_ocr_txt.tag_configure("empty", foreground="#888888")
    preview_ocr_txt.tag_configure("sep", foreground="#1565c0")
    preview_ocr_txt.pack(anchor=tk.W, fill=tk.X)
    preview_cue_lbl = ttk.Label(
        preview_frm,
        textvariable=preview_cue_var,
        foreground="#444444",
    )
    preview_cue_lbl.pack(anchor=tk.W, fill=tk.X, pady=(8, 0))

    def _update_preview_wrap(_event: tk.Event | None = None) -> None:
        w = max(120, preview_frm.winfo_width() - 20)
        preview_name_lbl.configure(wraplength=w)
        preview_cue_lbl.configure(wraplength=w)

    preview_frm.bind("<Configure>", _update_preview_wrap)

    def _apply_preview_pane_width() -> None:
        w = max(240, min(1200, preview_pane_width[0]))
        preview_pane_width[0] = w
        table_body.grid_columnconfigure(1, minsize=w)

    def _preview_pane_width() -> int:
        try:
            return max(240, int(preview_frm.winfo_width()))
        except (tk.TclError, ValueError):
            return preview_pane_width[0]

    cols = (
        _COL_SEL,
        _COL_SRT,
        _COL_CUE,
        _COL_CURRENT,
        _COL_APPLY,
        _COL_MATCH,
        _COL_STATUS,
        _COL_DOWNLOAD,
        _COL_MATCH_REASON,
    )
    _heading_labels = {
        _COL_SEL: "선택",
        _COL_SRT: "대본 번호",
        _COL_CUE: "대본 내용",
        _COL_CURRENT: "현재 파일명",
        _COL_MATCH: "매칭여부",
        _COL_MATCH_REASON: "OCR매핑 번호",
        _COL_APPLY: "적용",
        _COL_STATUS: "상태",
        _COL_DOWNLOAD: "다운로드이미지",
    }
    _sort_col: str | None = None
    _sort_rev = False

    _tree_row_px = 22

    tree = ttk.Treeview(
        list_frm,
        columns=cols,
        show="headings",
        selectmode="browse",
        height=14,
    )

    def _name_srt_num(name: str) -> int | None:
        m = _SRT_NUM_IN_NAME.search(name)
        if not m:
            return None
        try:
            return int(m.group(1))
        except ValueError:
            return None

    def _row_name_key(row: MatchPreview) -> str:
        path = _current_file_path(row)
        return path.name.lower() if path is not None else row.source.name.lower()

    def _row_sort_key(row: MatchPreview, col: str):
        if col == _COL_SEL:
            return (0 if id(row) in selected_row_ids else 1, _row_name_key(row))
        if col == _COL_SRT:
            n = row.srt_number
            return (n < 0, n if n >= 0 else 0, _row_name_key(row))
        if col == _COL_CUE:
            return (row.cue_text.lower(), _row_name_key(row))
        if col == _COL_CURRENT:
            cur = _mapped_current_display(row)
            return (cur == "", cur.lower(), _row_name_key(row))
        if col == _COL_MATCH:
            order = {"일치": 0, "불일치": 1, "—": 2}
            return (order.get(row.match_label, 9), _row_name_key(row))
        if col == _COL_MATCH_REASON:
            return ((row.match_reason or "").lower(), _row_name_key(row))
        if col == _COL_APPLY:
            return (0 if _row_show_apply_button(row) else 1, _row_name_key(row))
        if col == _COL_STATUS:
            return (row.status.lower(), _row_name_key(row))
        if col == _COL_DOWNLOAD:
            return (_download_img_display(row).lower(), _row_name_key(row))
        return (_row_name_key(row),)

    def _refresh_headings() -> None:
        for c in cols:
            label = _heading_labels[c]
            if c == _COL_SRT:
                label += " ▲"
            elif c == _sort_col:
                label += " ▼" if _sort_rev else " ▲"
            tree.heading(c, text=label, command=lambda col=c: sort_by_column(col))

    def sort_by_column(col: str) -> None:
        nonlocal _sort_col, _sort_rev
        if not _all_rows_cache:
            return
        if col == _COL_SRT:
            _sort_col = _COL_SRT
            _sort_rev = False
            _all_rows_cache.sort(
                key=lambda r: (r.srt_number < 0, r.srt_number if r.srt_number >= 0 else 0)
            )
        else:
            if _sort_col == col:
                _sort_rev = not _sort_rev
            else:
                _sort_col = col
                _sort_rev = False
            _all_rows_cache.sort(
                key=lambda row: _row_sort_key(row, col),
                reverse=_sort_rev,
            )
        show_all_rows(select_first=False)
        _refresh_headings()

    _refresh_headings()

    tree.column(_COL_SEL, width=44, anchor=tk.CENTER, stretch=False)
    tree.column(_COL_SRT, width=68, anchor=tk.CENTER, stretch=False)
    tree.column(_COL_CUE, width=300, anchor=tk.W, stretch=True)
    tree.column(_COL_CURRENT, width=140, anchor=tk.W)
    tree.column(_COL_APPLY, width=64, anchor=tk.CENTER, stretch=False)
    tree.column(_COL_MATCH, width=60, anchor=tk.CENTER, stretch=False)
    tree.column(_COL_STATUS, width=120, anchor=tk.W)
    tree.column(_COL_DOWNLOAD, width=140, anchor=tk.W)
    tree.column(_COL_MATCH_REASON, width=220, anchor=tk.W)

    vsb = ttk.Scrollbar(list_frm, orient=tk.VERTICAL, command=tree.yview)
    hsb = ttk.Scrollbar(list_frm, orient=tk.HORIZONTAL, command=tree.xview)

    def _sync_tree_height(_event: tk.Event | None = None) -> None:
        try:
            if _event is not None and _event.widget is not list_frm:
                return
            available = list_frm.winfo_height()
            if available <= 1:
                return
            hsb_reserve = hsb.winfo_height() if hsb.winfo_ismapped() else 0
            rows = max(3, (available - hsb_reserve - 2) // _tree_row_px)
            if int(tree.cget("height")) != rows:
                tree.configure(height=rows)
        except tk.TclError:
            pass

    def _tree_xscroll(first: str, last: str) -> None:
        f, l = float(first), float(last)
        if f <= 0.0 and l >= 1.0:
            hsb.grid_remove()
        else:
            hsb.grid(row=1, column=0, sticky="ew")
        hsb.set(first, last)
        root.after_idle(_sync_tree_height)

    tree.configure(yscrollcommand=vsb.set, xscrollcommand=_tree_xscroll)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    hsb.grid_remove()
    list_frm.bind("<Configure>", _sync_tree_height)
    root.after_idle(_sync_tree_height)

    def show_all_rows(*, select_first: bool = True) -> None:
        """캐시된 전체 대본 행을 목록에 표시."""
        for iid in tree.get_children():
            tree.delete(iid)
        rows_by_iid.clear()
        selected_iids.clear()
        if not _all_rows_cache:
            clear_preview()
            return
        for row in _all_rows_cache:
            _insert_row(row, default_checked=False)
        if not select_first:
            return
        kids = tree.get_children("")
        if kids:
            first = kids[0]
            tree.selection_set(first)
            tree.focus(first)
            tree.see(first)
            show_preview_for_iid(first)
        else:
            clear_preview()

    def _paths_same(a: Path, b: Path) -> bool:
        try:
            return a.resolve() == b.resolve()
        except OSError:
            return a == b

    def _migrate_manual_override(old_src: Path, new_src: Path) -> None:
        old_k = _override_key(old_src)
        new_k = _override_key(new_src)
        if old_k == new_k:
            return
        if old_k in manual_overrides:
            manual_overrides[new_k] = manual_overrides.pop(old_k)
            try:
                save_manual_overrides(manual_overrides)
            except OSError:
                pass

    def _apply_rename_to_row(row: MatchPreview, r: RenameResult) -> None:
        old_src = row.source
        row.source = r.target
        row.target_name = r.target.name
        n = _name_srt_num(r.target.name)
        if n is not None:
            row.srt_number = n
            _sync_cue_text(row)
        row.can_rename = False
        row.status = "이름 변경 완료"
        _migrate_manual_override(old_src, r.target)
        _sync_row_source_from_disk(row)

    def _apply_rename_results(
        results: list[RenameResult],
        pending: list[MatchPreview],
    ) -> None:
        matched_rows: set[int] = set()
        for row in pending:
            for r in results:
                if not _paths_same(row.source, r.source):
                    continue
                _apply_rename_to_row(row, r)
                matched_rows.add(id(row))
                break
        for r in results:
            for row in _all_rows_cache:
                if id(row) in matched_rows:
                    continue
                if not _paths_same(row.source, r.source):
                    continue
                _apply_rename_to_row(row, r)
                matched_rows.add(id(row))
                break

    def _purge_stale_rows_after_rename(results: list[RenameResult]) -> None:
        """이름 변경된 이전 경로·파일명을 가리키는 중복 행 제거."""
        if not results:
            return
        old_sources = [r.source for r in results]
        kept: list[MatchPreview] = []
        for row in _all_rows_cache:
            drop = False
            for old in old_sources:
                if _paths_same(row.source, old):
                    drop = True
                    break
                if (
                    row.srt_number < 0
                    and row.source.name == old.name
                    and not row.source.is_file()
                ):
                    drop = True
                    break
            if drop:
                selected_row_ids.discard(id(row))
                for old in old_sources:
                    if _paths_same(row.source, old) or row.source.name == old.name:
                        try:
                            _ocr_cache_keys.discard(_ocr_cache_key(old))
                        except OSError:
                            pass
                        manual_overrides.pop(_override_key(old), None)
                        break
                continue
            kept.append(row)
        if len(kept) != len(_all_rows_cache):
            try:
                save_manual_overrides(manual_overrides)
            except OSError:
                pass
        _all_rows_cache[:] = kept

    def reload_table(*, status_msg: str | None = None, quiet: bool = False) -> None:
        """파일명 저장·변경 후 그리드 조회 데이터를 디스크 기준으로 새로고침."""
        nonlocal _last_sel_iid_for_apply
        sel_srt: int | None = None
        sel = tree.selection()
        if sel and sel[0] in rows_by_iid:
            r = rows_by_iid[sel[0]]
            if r.srt_number >= 0:
                sel_srt = r.srt_number
        srt = Path(srt_var.get().strip())
        png = Path(png_var.get().strip())
        reloaded = False
        if srt.is_file() and png.is_dir():
            try:
                _refresh_srt_name_choices()
                skel = build_srt_centric_skeleton(
                    srt,
                    png,
                    recursive=bool(recursive_var.get()),
                )
                for row in skel:
                    _apply_row_override(row)
                selected_row_ids.clear()
                _ocr_pending.clear()
                _ocr_cache_keys.clear()
                _all_rows_cache[:] = skel
                _remap_rows_from_filenames()
                _sort_tree_by_srt_asc(refresh_heading=True)
                reloaded = True
            except Exception as e:
                traceback.print_exc()
                if not quiet:
                    messagebox.showerror("새로고침", str(e))
                    status_var.set(f"새로고침 오류: {e}")
        if not reloaded:
            png = Path(png_var.get().strip())
            if srt_cue_map and png.is_dir():
                ensure_all_cue_rows(_all_rows_cache, srt_cue_map, png)
            for row in _all_rows_cache:
                _sync_cue_text(row)
                _sync_row_source_from_disk(row)
            _remap_rows_from_filenames()
            show_all_rows(select_first=sel_srt is None)
        if sel_srt is not None:
            for iid in tree.get_children():
                row = rows_by_iid.get(iid)
                if row and row.srt_number == sel_srt:
                    tree.selection_set(iid)
                    tree.see(iid)
                    show_preview_for_iid(iid)
                    _last_sel_iid_for_apply = iid
                    _refresh_apply_neighbor_columns(None, iid)
                    break
        if status_msg is not None:
            status_var.set(status_msg)
        elif reloaded and not quiet:
            status_var.set("")
        root.update_idletasks()

    tree.tag_configure("muted", foreground="#888888")
    tree.tag_configure("matched", foreground="#1565c0")
    tree.tag_configure("unmatched", foreground="#c62828")

    def _ocr_cache_key(path: Path) -> str:
        try:
            st = path.stat()
            return f"{path.resolve()}:{st.st_mtime_ns}"
        except OSError:
            return str(path)

    def _used_srt_numbers(exclude_row: MatchPreview | None = None) -> set[int]:
        ex = id(exclude_row) if exclude_row is not None else None
        return {
            r.srt_number
            for r in _all_rows_cache
            if r.srt_number >= 0 and id(r) != ex
        }

    def schedule_row_ocr(iid: str) -> None:
        """행 클릭 시 해당 이미지 OCR 후 목록 컬럼 갱신."""
        row = rows_by_iid.get(iid)
        if row is None:
            return
        path = _current_file_path(row)
        if path is None:
            return
        if path.stem.lower() in ("thumbnail_youtube", "thumbnail"):
            return

        row.source = path
        cache_key = _ocr_cache_key(path)
        rid = id(row)
        if rid in _ocr_pending:
            return
        pending_status = row.status in (
            "조회 대기",
            "미배정·조회 대기",
            "이미지 없음",
            "",
        )
        if (
            cache_key in _ocr_cache_keys
            and (row.ocr_preview or "").strip()
            and not pending_status
        ):
            return

        _ocr_pending.add(rid)
        status_var.set(f"OCR 인식 중… {path.name}")

        def work() -> None:
            err: Exception | None = None
            try:
                srt = Path(srt_var.get().strip())
                if not srt.is_file():
                    raise FileNotFoundError(f"SRT 없음: {srt}")
                from png_rename.ocr import ensure_tesseract_cmd

                ensure_tesseract_cmd()
                cues = parse_srt_cues(srt)
                apply_ocr_to_row(
                    row,
                    cues,
                    skip_already_named=skip_already_named,
                    used_numbers=_used_srt_numbers(row),
                    prefer_slot=row.srt_number if row.srt_number >= 0 else None,
                )
            except ScanCancelledError as e:
                err = e
            except Exception as e:
                err = e
                traceback.print_exc()

            def ui() -> None:
                _ocr_pending.discard(rid)
                if err is not None:
                    row.status = f"OCR 실패: {err}"
                    row.ocr_preview = ""
                else:
                    _ocr_cache_keys.add(cache_key)
                if iid in rows_by_iid and rows_by_iid[iid] is row:
                    _remap_rows_from_filenames()
                    _sync_row_match_fields(row)
                    _refresh_row_display(iid, row)
                    show_preview_for_iid(iid)
                if not _ocr_pending:
                    status_var.set(f"OCR 완료 · 전체 {len(_all_rows_cache)}행")

            safe_after(root, ui)

        threading.Thread(target=work, daemon=True).start()

    def _needs_row_ocr(row: MatchPreview) -> bool:
        if (row.ocr_preview or "").strip():
            return False
        if id(row) in _ocr_pending:
            return False
        path = _current_file_path(row)
        if path is None or not path.is_file():
            return False
        if path.stem.lower() in ("thumbnail_youtube", "thumbnail"):
            return False
        return True

    def on_tree_click(event: tk.Event) -> None:
        region = tree.identify_region(event.x, event.y)
        iid = tree.identify_row(event.y)
        if not iid or iid not in rows_by_iid:
            return
        prev_sel = tree.selection()
        prev_iid = prev_sel[0] if prev_sel else None
        if region == "cell":
            col = tree.identify_column(event.x)
            try:
                cidx = int(col.lstrip("#")) - 1
            except ValueError:
                cidx = -1
            if 0 <= cidx < len(cols) and cols[cidx] == _COL_MATCH_REASON:
                tree.selection_set(iid)
                tree.focus(iid)
                _open_mapping_popup_for_row(iid)
                return
            if 0 <= cidx < len(cols) and cols[cidx] == _COL_APPLY:
                _apply_filename_from_apply_row(iid, prev_iid)
                return "break"
        tree.selection_set(iid)
        tree.focus(iid)
        if region == "cell" and tree.identify_column(event.x) == "#1":
            toggle_iid(iid)
        show_preview_for_iid(iid)
        row = rows_by_iid.get(iid)
        if row is not None and _needs_row_ocr(row):
            schedule_row_ocr(iid)

    def on_tree_select(_event: tk.Event | None = None) -> None:
        nonlocal _last_sel_iid_for_apply
        prev_iid = _last_sel_iid_for_apply
        sel = tree.selection()
        if sel and sel[0] in rows_by_iid:
            iid = sel[0]
            show_preview_for_iid(iid)
            row = rows_by_iid.get(iid)
            if row is not None and _needs_row_ocr(row):
                schedule_row_ocr(iid)
            _last_sel_iid_for_apply = iid
            _refresh_apply_neighbor_columns(prev_iid, iid)
        else:
            _last_sel_iid_for_apply = None
            _refresh_apply_neighbor_columns(prev_iid, None)

    def _remap_rows_from_filenames() -> None:
        if srt_cue_map:
            remap_all_rows_from_filenames(_all_rows_cache, srt_cue_map)

    def _apply_filename_from_apply_row(apply_iid: str, target_iid: str | None) -> None:
        """적용 행의 현재파일명으로 선택 행 파일명 즉시 변경·저장."""
        apply_row = rows_by_iid.get(apply_iid)
        if apply_row is None or not _row_show_apply_button(apply_row):
            return
        if not target_iid or target_iid not in rows_by_iid:
            messagebox.showinfo("적용", "현재파일명을 바꿀 행을 먼저 선택하세요.")
            return
        if target_iid == apply_iid:
            messagebox.showinfo("적용", "다른 행을 선택한 뒤 적용하세요.")
            return

        target_row = rows_by_iid[target_iid]
        name = _edit_current_filename_value(apply_row)
        if not name:
            messagebox.showinfo("적용", "적용할 파일명이 없습니다.")
            return
        norm = _normalize_target_name(name)
        if norm is not None:
            applied_name = norm
            target_row.target_name = norm
            n = _name_srt_num(norm)
            if n is not None:
                target_row.srt_number = n
                _sync_cue_text(target_row)
        else:
            applied_name = Path(name.strip()).name
            if not applied_name.lower().endswith(".png"):
                messagebox.showinfo(
                    "적용",
                    "적용할 파일명이 .png 형식이 아닙니다.",
                )
                return
            target_row.target_name = applied_name

        src = _resolve_rename_source(target_row)
        if src is None or not src.is_file():
            apply_src = _resolve_rename_source(apply_row)
            if apply_src is None and _ocr_apply_source_iid:
                ocr_row = rows_by_iid.get(_ocr_apply_source_iid)
                if ocr_row is not None:
                    apply_src = _resolve_rename_source(ocr_row)
            if apply_src is not None and apply_src.is_file():
                try:
                    _rename_source_by_row[id(target_row)] = apply_src.resolve()
                except OSError:
                    _rename_source_by_row[id(target_row)] = apply_src
                src = apply_src
        elif src.name != applied_name:
            try:
                _rename_source_by_row[id(target_row)] = src.resolve()
            except OSError:
                _rename_source_by_row[id(target_row)] = src

        if src is None or not src.is_file():
            messagebox.showinfo("적용", "저장할 PNG 파일이 없습니다.")
            return
        target_row.can_rename = bool(src.name != applied_name)
        if not _rename_row_filename_now(target_row, target_iid):
            return
        refresh_count()
        reload_table(
            status_msg=f"적용 저장: {applied_name}",
            quiet=True,
        )
        if target_iid in rows_by_iid:
            tree.selection_set(target_iid)
            tree.focus(target_iid)
            tree.see(target_iid)
            show_preview_for_iid(target_iid)
        status_var.set(
            f"적용: 선택 행 → {applied_name} (원본: {_edit_current_filename_value(apply_row)})"
        )

    def _choose_mapping_candidate(candidates: list[int], current: int) -> int | None:
        win = tk.Toplevel(root)
        win.title("OCR 매핑 번호 선택")
        win.transient(root)
        win.grab_set()
        picked: dict[str, int | None] = {"value": None}

        frm_local = ttk.Frame(win, padding=10)
        frm_local.pack(fill=tk.BOTH, expand=True)
        ttk.Label(frm_local, text="매핑 번호를 선택하세요.").pack(anchor=tk.W)
        vals = [str(n) for n in candidates]
        cb = ttk.Combobox(frm_local, values=vals, state="readonly", width=12)
        cb.pack(anchor=tk.W, pady=(6, 8))
        cb.set(str(current if current in candidates else candidates[0]))
        cb.focus_set()

        btns = ttk.Frame(frm_local)
        btns.pack(anchor=tk.E)

        def ok() -> None:
            try:
                picked["value"] = int(cb.get().strip())
            except ValueError:
                picked["value"] = None
            win.destroy()

        def cancel() -> None:
            picked["value"] = None
            win.destroy()

        ttk.Button(btns, text="확인", command=ok, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="취소", command=cancel, width=8).pack(side=tk.LEFT)
        cb.bind("<Return>", lambda _e: ok())
        cb.bind("<Escape>", lambda _e: cancel())
        win.protocol("WM_DELETE_WINDOW", cancel)
        _center_modal_toplevel(win, root)
        root.wait_window(win)
        return picked["value"] if isinstance(picked["value"], int) else None

    def _choose_mapping_candidate_with_words(
        row: MatchPreview,
        candidates: list[int],
        iid: str,
        rows_local: list[tuple[str, int, str]],
    ) -> int | None:
        cue_map_local = {int(k): v for k, v in srt_cue_map.items()}

        if not rows_local:
            return None

        win = tk.Toplevel(root)
        win.title("OCR 매핑 선택")
        win.transient(root)
        win.grab_set()
        picked: dict[str, int | None] = {"value": None}

        frm_local = ttk.Frame(win, padding=10)
        frm_local.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frm_local,
            text="OCR 단어·대본번호·문장을 클릭하면 부모 목록의 파일명이 즉시 바뀝니다 (확인·더블클릭도 가능).",
        ).pack(anchor=tk.W)

        list_frm = ttk.Frame(frm_local)
        list_frm.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        list_frm.grid_columnconfigure(0, weight=1)
        list_frm.grid_rowconfigure(0, weight=1)

        tv = ttk.Treeview(
            list_frm,
            columns=("word", "no", "cue"),
            show="headings",
            height=12,
            selectmode="browse",
        )
        tv.heading("word", text="OCR 단어")
        tv.heading("no", text="대본번호")
        tv.heading("cue", text="대본 문장")
        tv.column("word", width=120, anchor=tk.W, stretch=False)
        tv.column("no", width=72, anchor=tk.CENTER, stretch=False)
        tv.column("cue", width=360, anchor=tk.W, stretch=True)
        vsb = ttk.Scrollbar(list_frm, orient=tk.VERTICAL, command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        sort_state: dict[str, bool] = {"word": False, "no": False, "cue": False}

        def _sort_popup_rows(col: str) -> None:
            reverse = not sort_state.get(col, False)
            sort_state[col] = reverse
            for key in sort_state:
                if key != col:
                    sort_state[key] = False
            items = list(tv.get_children(""))

            def key_of(iid_item: str):
                vals = tv.item(iid_item, "values")
                if col == "no":
                    try:
                        return int(vals[1])
                    except (ValueError, TypeError, IndexError):
                        return -1
                if col == "word":
                    return (vals[0] if vals else "").lower()
                return (vals[2] if len(vals) > 2 else "").lower()

            items.sort(key=key_of, reverse=reverse)
            for idx, iid_item in enumerate(items):
                tv.move(iid_item, "", idx)
            arrow = "▼" if reverse else "▲"
            tv.heading("word", text=f"OCR 단어{' ' + arrow if col == 'word' else ''}")
            tv.heading("no", text=f"대본번호{' ' + arrow if col == 'no' else ''}")
            tv.heading("cue", text=f"대본 문장{' ' + arrow if col == 'cue' else ''}")

        tv.heading("word", command=lambda: _sort_popup_rows("word"))
        tv.heading("no", command=lambda: _sort_popup_rows("no"))
        tv.heading("cue", command=lambda: _sort_popup_rows("cue"))
        tv.heading("no", text="대본번호 ▲")

        default_iid = ""
        default_no = row.srt_number if row.srt_number in candidates else rows_local[0][1]
        for i, (word, mid, cue) in enumerate(rows_local):
            iid_local = f"{mid}:{i}"
            tv.insert(
                "",
                tk.END,
                iid=iid_local,
                values=(word, str(mid), cue[:180] if cue else "—"),
            )
            if mid == default_no and not default_iid:
                default_iid = iid_local
        if default_iid:
            tv.selection_set(default_iid)
            tv.focus(default_iid)
            tv.see(default_iid)

        btns = ttk.Frame(frm_local)
        btns.pack(anchor=tk.E)

        def apply_pick(*, close_win: bool) -> bool:
            sel = tv.selection()
            if not sel:
                return False
            try:
                n = int(str(sel[0]).split(":", 1)[0])
            except ValueError:
                return False
            _apply_script_number_to_row(row, n)
            row.status = f"OCR매핑 선택: {n}번 (저장 대기)"
            _refresh_row_display(iid, row)
            show_preview_for_iid(iid)
            _save_row_override(row)
            status_var.set(
                f"OCR매핑 적용: 대본 {n}번 → {row.target_name} (저장 대기)"
            )
            picked["value"] = n
            if close_win:
                win.destroy()
            return True

        def ok() -> None:
            if not apply_pick(close_win=True):
                picked["value"] = None
                win.destroy()

        def cancel() -> None:
            picked["value"] = None
            win.destroy()

        def on_mapping_row_pick(_event: tk.Event) -> None:
            if tv.identify_region(_event.x, _event.y) != "cell":
                return
            iid_local = tv.identify_row(_event.y)
            if not iid_local:
                return
            tv.selection_set(iid_local)
            tv.focus(iid_local)
            apply_pick(close_win=True)

        ttk.Button(btns, text="확인", command=ok, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="취소", command=cancel, width=8).pack(side=tk.LEFT)
        tv.bind("<ButtonRelease-1>", on_mapping_row_pick)
        tv.bind("<Double-1>", lambda _e: ok())
        tv.bind("<Return>", lambda _e: ok())
        win.bind("<Escape>", lambda _e: cancel())
        win.protocol("WM_DELETE_WINDOW", cancel)
        _center_modal_toplevel(win, root)
        root.wait_window(win)
        return picked["value"] if isinstance(picked["value"], int) else None

    def _sort_tree_by_srt_asc(*, refresh_heading: bool = True) -> None:
        """대본번호 오름차순으로 전체 목록 정렬."""
        nonlocal _sort_col, _sort_rev
        if not _all_rows_cache:
            return
        _sort_col = _COL_SRT
        _sort_rev = False
        _all_rows_cache.sort(
            key=lambda r: (r.srt_number < 0, r.srt_number if r.srt_number >= 0 else 0)
        )
        show_all_rows(select_first=False)
        if refresh_heading:
            _refresh_headings()

    tree.bind("<Button-1>", on_tree_click, add="+")
    tree.bind("<<TreeviewSelect>>", on_tree_select)

    _apply_col_hand_cursor = [False]

    def on_tree_motion(event: tk.Event) -> None:
        region = tree.identify_region(event.x, event.y)
        show_hand = False
        if region == "cell":
            col = tree.identify_column(event.x)
            try:
                cidx = int(col.lstrip("#")) - 1
            except ValueError:
                cidx = -1
            iid = tree.identify_row(event.y)
            if (
                0 <= cidx < len(cols)
                and cols[cidx] == _COL_APPLY
                and iid
                and iid in rows_by_iid
            ):
                row = rows_by_iid[iid]
                if row is not None and _row_show_apply_button(row):
                    if tree.set(iid, _COL_APPLY) == "적용":
                        show_hand = True
        if show_hand:
            if not _apply_col_hand_cursor[0]:
                tree.configure(cursor="hand2")
                _apply_col_hand_cursor[0] = True
        elif _apply_col_hand_cursor[0]:
            tree.configure(cursor="")
            _apply_col_hand_cursor[0] = False

    def on_tree_leave(_event: tk.Event) -> None:
        if _apply_col_hand_cursor[0]:
            tree.configure(cursor="")
            _apply_col_hand_cursor[0] = False

    tree.bind("<Motion>", on_tree_motion, add="+")
    tree.bind("<Leave>", on_tree_leave, add="+")

    def _refresh_srt_name_choices() -> None:
        nonlocal srt_name_choices, srt_number_choices, srt_cue_map
        srt = Path(srt_var.get().strip())
        if not srt.is_file():
            srt_name_choices = []
            srt_number_choices = []
            srt_cue_map = {}
            return
        try:
            cues = sorted(parse_srt_cues(srt), key=lambda c: int(c[0]))
            srt_name_choices = [srt_png_name(mid) for mid, _ in cues]
            srt_number_choices = [str(int(mid)) for mid, _ in cues]
            srt_cue_map = {
                int(mid): (txt or "").strip().replace("\n", " ")
                for mid, txt in cues
            }
        except OSError:
            srt_name_choices = []
            srt_number_choices = []
            srt_cue_map = {}

    def _target_from_filename(name: str) -> tuple[int, str] | None:
        n = _name_srt_num(name)
        if n is None:
            return None
        return n, srt_png_name(n)

    # ---- 대본 번호 지정 · 셀 편집 ----
    _cell_editor: tk.Widget | None = None

    def _apply_script_number_to_row(row: MatchPreview, n: int) -> bool:
        """대본 번호 → ``SRT_XXX.png`` 목표명·rename 원본 경로 확정."""
        old_src = _resolve_rename_source(row)
        row.srt_number = n
        _sync_cue_text(row)
        tgt_name = srt_png_name(n)
        row.target_name = tgt_name
        if old_src is not None and old_src.is_file():
            try:
                if old_src.resolve().name != tgt_name:
                    _rename_source_by_row[id(row)] = old_src.resolve()
            except OSError:
                _rename_source_by_row[id(row)] = old_src
        src = _rename_source_by_row.get(id(row))
        if src is None:
            src = _resolve_rename_source(row)
        row.can_rename = bool(src and src.is_file() and src.name != tgt_name)
        _sync_row_match_fields(row)
        return row.can_rename

    def _commit_script_number(row: MatchPreview, val: str, iid: str) -> bool:
        """대본 번호 지정 후 가능하면 즉시 파일명 변경."""
        if not _assign_srt_number(row, val):
            return False
        if row.can_rename:
            _rename_row_filename_now(row, iid)
        else:
            _refresh_row_display(iid, row)
            show_preview_for_iid(iid)
            _save_row_override(row)
        return True

    def _assign_srt_number(row: MatchPreview, val: str) -> bool:
        val = val.strip()
        if not val or val == "—":
            row.srt_number = -1
            row.matched = False
            row.can_rename = False
            row.status = "대본번호 해제"
            _rename_source_by_row.pop(id(row), None)
            return True
        try:
            n = int(val)
        except ValueError:
            messagebox.showwarning("입력", "대본 번호는 숫자여야 합니다.")
            return False
        _apply_script_number_to_row(row, n)
        row.status = f"변경 지정: {row.target_name} (저장 대기)"
        return True

    def _open_script_picker_for_row(iid: str) -> None:
        row = rows_by_iid.get(iid)
        if row is None:
            return
        _refresh_srt_name_choices()
        if not srt_cue_map:
            messagebox.showinfo("대본 번호", "SRT 파일을 먼저 지정하세요.")
            return

        cues = sorted(srt_cue_map.items(), key=lambda c: c[0])
        win = tk.Toplevel(root)
        win.title("대본 번호 선택")
        win.transient(root)
        win.grab_set()
        win.minsize(480, 360)
        picked: dict[str, int | None] = {"value": None}

        frm_local = ttk.Frame(win, padding=10)
        frm_local.pack(fill=tk.BOTH, expand=True)
        ttk.Label(
            frm_local,
            text="대본 번호·문장을 클릭하면 파일명이 즉시 변경됩니다 (확인·더블클릭도 가능).",
        ).pack(anchor=tk.W)

        list_frm = ttk.Frame(frm_local)
        list_frm.pack(fill=tk.BOTH, expand=True, pady=(6, 8))
        list_frm.grid_columnconfigure(0, weight=1)
        list_frm.grid_rowconfigure(0, weight=1)

        tv = ttk.Treeview(
            list_frm,
            columns=("no", "cue"),
            show="headings",
            height=12,
            selectmode="browse",
        )
        tv.heading("no", text="대본번호")
        tv.heading("cue", text="대본 문장")
        tv.column("no", width=72, anchor=tk.CENTER, stretch=False)
        tv.column("cue", width=380, anchor=tk.W, stretch=True)
        vsb = ttk.Scrollbar(list_frm, orient=tk.VERTICAL, command=tv.yview)
        tv.configure(yscrollcommand=vsb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")

        sort_state: dict[str, bool] = {"no": False}

        def _sort_script_rows(col: str) -> None:
            reverse = not sort_state.get(col, False)
            sort_state[col] = reverse
            for key in sort_state:
                if key != col:
                    sort_state[key] = False
            items = list(tv.get_children(""))

            def key_of(iid_item: str):
                vals = tv.item(iid_item, "values")
                if col == "no":
                    try:
                        return int(vals[0])
                    except (ValueError, TypeError, IndexError):
                        return -1
                return (vals[1] if len(vals) > 1 else "").lower()

            items.sort(key=key_of, reverse=reverse)
            for idx, iid_item in enumerate(items):
                tv.move(iid_item, "", idx)
            arrow = "▼" if reverse else "▲"
            tv.heading("no", text=f"대본번호{' ' + arrow if col == 'no' else ''}")
            tv.heading("cue", text=f"대본 문장{' ' + arrow if col == 'cue' else ''}")

        tv.heading("no", command=lambda: _sort_script_rows("no"))
        tv.heading("cue", command=lambda: _sort_script_rows("cue"))
        tv.heading("no", text="대본번호 ▲")

        default_iid = ""
        for mid, cue in cues:
            iid_local = f"n{mid}"
            tv.insert("", tk.END, iid=iid_local, values=(str(mid), cue[:200] if cue else "—"))
            if mid == row.srt_number:
                default_iid = iid_local
        if not default_iid and cues:
            default_iid = f"n{cues[0][0]}"
        if default_iid:
            tv.selection_set(default_iid)
            tv.focus(default_iid)
            tv.see(default_iid)

        btns = ttk.Frame(frm_local)
        btns.pack(anchor=tk.E)

        def apply_pick(*, close_win: bool) -> bool:
            sel = tv.selection()
            if not sel:
                return False
            try:
                n = int(tv.item(sel[0], "values")[0])
            except (ValueError, TypeError, IndexError):
                return False
            val = "—" if n == -1 else str(n)
            if not _commit_script_number(row, val, iid):
                return False
            picked["value"] = n
            status_var.set(
                f"파일명 변경: {row.target_name}"
                if row.status.startswith("즉시 저장")
                else (
                    f"대본 {row.srt_number}번 지정 → {row.target_name}"
                    if row.srt_number >= 0
                    else "대본번호 해제"
                )
            )
            if close_win:
                win.destroy()
            return True

        def ok() -> None:
            apply_pick(close_win=True)

        def cancel() -> None:
            picked["value"] = None
            win.destroy()

        def release_pick() -> None:
            if _commit_script_number(row, "—", iid):
                picked["value"] = -1
                status_var.set("대본번호 해제")
                win.destroy()

        def on_script_row_pick(_event: tk.Event) -> None:
            if tv.identify_region(_event.x, _event.y) != "cell":
                return
            iid_local = tv.identify_row(_event.y)
            if not iid_local:
                return
            tv.selection_set(iid_local)
            tv.focus(iid_local)
            apply_pick(close_win=True)

        ttk.Button(btns, text="확인", command=ok, width=8).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btns, text="취소", command=cancel, width=8).pack(side=tk.LEFT)
        ttk.Button(btns, text="해제", command=release_pick, width=8).pack(
            side=tk.LEFT, padx=(8, 0)
        )
        tv.bind("<ButtonRelease-1>", on_script_row_pick)
        tv.bind("<Double-1>", lambda _e: ok())
        tv.bind("<Return>", lambda _e: ok())
        win.bind("<Escape>", lambda _e: cancel())
        win.protocol("WM_DELETE_WINDOW", cancel)
        _center_modal_toplevel(win, root)
        root.wait_window(win)
        return

    def _close_cell_editor() -> None:
        nonlocal _cell_editor
        if _cell_editor is None:
            return
        try:
            _cell_editor.destroy()
        except tk.TclError:
            pass
        _cell_editor = None

    def _start_cell_edit(iid: str, col_id: str) -> None:
        nonlocal _cell_editor
        if iid not in rows_by_iid:
            return
        row = rows_by_iid[iid]

        editable = {_COL_SRT, _COL_CURRENT, _COL_CUE, _COL_DOWNLOAD}
        if col_id not in editable:
            return

        bbox = tree.bbox(iid, column=col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        if w <= 6 or h <= 6:
            return

        _close_cell_editor()

        def finish_edit(*, skip_source_sync: bool = False) -> None:
            if not skip_source_sync:
                _sync_row_source_from_disk(row)
            _refresh_row_display(iid, row)
            show_preview_for_iid(iid)
            _save_row_override(row)

        def commit_entry(val: str) -> None:
            if col_id == _COL_SRT:
                _close_cell_editor()
                _commit_script_number(row, val, iid)
                return
            elif col_id == _COL_CURRENT:
                if not val or val == "—":
                    row.target_name = "—"
                    row.can_rename = False
                    row.status = "현재파일명 없음"
                else:
                    norm = _normalize_target_name(val)
                    if norm is None:
                        messagebox.showwarning(
                            "입력",
                            "현재 파일명은 SRT_XXX.png 형식이어야 합니다.\n"
                            "예: SRT_007.png",
                        )
                        return
                    row.target_name = norm
                    n = _name_srt_num(norm)
                    if n is not None:
                        row.srt_number = n
                        _sync_cue_text(row)
                    src = _resolve_rename_source(row)
                    if src is not None and src.is_file():
                        _rename_source_by_row[id(row)] = src
                    if src is None:
                        row.can_rename = False
                        row.status = f"변경 지정: {row.target_name} (저장 대기)"
                        _close_cell_editor()
                        finish_edit()
                        return
                    _close_cell_editor()
                    if _rename_row_filename_now(row, iid):
                        finish_edit(skip_source_sync=True)
                    return
            elif col_id == _COL_CUE:
                row.cue_text = val
            elif col_id == _COL_DOWNLOAD:
                key = _download_img_key(row)
                if val:
                    download_image_inputs[key] = val
                else:
                    download_image_inputs.pop(key, None)
                try:
                    save_download_image_inputs(download_image_inputs)
                except OSError:
                    pass
                err = _copy_download_image_to_row(row, val) if val else None
                _close_cell_editor()
                if err:
                    messagebox.showwarning("다운로드 복사", err)
                    _refresh_row_display(iid, row)
                    return
                if val:
                    _save_row_override(row)
                    reload_table(
                        status_msg=f"다운로드 복사: {row.target_name}",
                        quiet=True,
                    )
                    if iid in rows_by_iid:
                        tree.selection_set(iid)
                        show_preview_for_iid(iid)
                else:
                    finish_edit()
                return
            finish_edit()
            _close_cell_editor()

        def cancel() -> None:
            _close_cell_editor()

        if col_id == _COL_SRT:
            _refresh_srt_name_choices()
            cur = "" if row.srt_number < 0 else str(row.srt_number)
            values = list(srt_number_choices)
            if cur and cur not in values:
                values = [cur, *values]
            if "—" not in values:
                values = ["—", *values]

            cb = ttk.Combobox(tree, values=values, state="readonly", width=8)
            _cell_editor = cb
            cb.place(x=x, y=y, width=max(w, 72), height=h)
            cb.set(cur or "—")
            cb.focus_set()
            cb.event_generate("<Down>")

            def commit_srt_combo(_event: tk.Event | None = None) -> None:
                val = cb.get()
                _close_cell_editor()
                _commit_script_number(row, val, iid)

            cb.bind("<<ComboboxSelected>>", commit_srt_combo)
            cb.bind("<Return>", commit_srt_combo)
            cb.bind("<Escape>", lambda _e: cancel())
            return

        if col_id == _COL_CURRENT:
            cur_val = _edit_current_filename_value(row)
        elif col_id == _COL_CUE:
            cur_val = row.cue_text or ""
        elif col_id == _COL_DOWNLOAD:
            cur_val = _download_img_display(row)
        else:
            cur_val = ""

        ent = ttk.Entry(tree)
        _cell_editor = ent
        ent.place(x=x, y=y, width=w, height=h)
        ent.insert(0, cur_val)
        ent.select_range(0, tk.END)
        ent.focus_set()
        if col_id == _COL_DOWNLOAD:

            def save_download_draft() -> None:
                draft = ent.get().strip()
                key = _download_img_key(row)
                if draft:
                    download_image_inputs[key] = draft
                else:
                    download_image_inputs.pop(key, None)
                try:
                    save_download_image_inputs(download_image_inputs)
                except OSError:
                    pass
                _close_cell_editor()
                _refresh_row_display(iid, row)

            ent.bind("<Return>", lambda _e: commit_entry(ent.get().strip()))
            ent.bind("<Escape>", lambda _e: cancel())
            ent.bind("<FocusOut>", lambda _e: save_download_draft())
            return

        ent.bind("<Return>", lambda _e: commit_entry(ent.get().strip()))
        ent.bind("<Escape>", lambda _e: cancel())
        ent.bind("<FocusOut>", lambda _e: commit_entry(ent.get().strip()))

    def on_tree_cell_double_click(event: tk.Event) -> None:
        # 셀을 더블클릭하면 편집 우선
        if tree.identify_region(event.x, event.y) != "cell":
            return
        iid = tree.identify_row(event.y)
        if not iid:
            return
        col = tree.identify_column(event.x)  # "#1"...
        try:
            idx = int(col.lstrip("#")) - 1
        except ValueError:
            return
        if idx < 0 or idx >= len(cols):
            return
        col_id = cols[idx]
        if col_id == _COL_SEL:
            return
        if col_id == _COL_MATCH_REASON:
            _open_mapping_popup_for_row(iid)
            return
        _start_cell_edit(iid, col_id)

    tree.bind("<Double-1>", on_tree_cell_double_click, add="+")

    def _row_matches_keyword(row: MatchPreview, kw: str, srt_ids: set[int]) -> bool:
        if kw in (row.ocr_preview or "").lower():
            return True
        if kw in (row.cue_text or "").lower():
            return True
        if row.srt_number in srt_ids or row.word_srt_number in srt_ids:
            return True
        return False

    def clear_keyword_filter() -> None:
        for iid in list(_filter_detached):
            try:
                tree.reattach(iid, "", tk.END)
            except tk.TclError:
                pass
        _filter_detached.clear()
        visible = len(tree.get_children())
        if rows_by_iid:
            status_var.set(f"목록 {visible}개 표시 (필터 해제)")

    def _jump_to_srt_number(map_id: int) -> bool:
        for iid in tree.get_children():
            row = rows_by_iid.get(iid)
            if row and (row.srt_number == map_id or row.word_srt_number == map_id):
                tree.selection_set(iid)
                tree.see(iid)
                show_preview_for_iid(iid)
                root.lift()
                return True
        return False

    def _refresh_row_display(iid: str, row: MatchPreview) -> None:
        _sync_cue_text(row)
        _sync_row_match_fields(row)
        srt_disp = str(row.srt_number) if row.srt_number >= 0 else "—"
        cue_disp = (row.cue_text or "—")[:160]
        current_disp = _mapped_current_display(row)
        map_disp = (row.match_reason or "—")[:160]
        apply_disp = "적용" if _row_show_apply_button(row) else ""
        download_disp = _download_img_display(row)[:80]
        tags: tuple[str, ...] = ()
        if not row.can_rename and not row.ocr_preview:
            tags = ("muted",)
        elif filename_matches_script_number(row):
            tags = ("matched",)
        else:
            tags = ("unmatched",)

        tree.item(
            iid,
            values=(
                _sel_mark(id(row) in selected_row_ids),
                srt_disp,
                cue_disp,
                current_disp,
                apply_disp,
                row.match_label,
                row.status,
                download_disp,
                map_disp,
            ),
            tags=tags,
        )

    def _refresh_apply_neighbor_columns(
        prev_iid: str | None,
        new_iid: str | None,
    ) -> None:
        kids = list(tree.get_children(""))
        to_refresh: set[str] = set()
        for anchor in (prev_iid, new_iid):
            if not anchor or anchor not in kids:
                continue
            si = kids.index(anchor)
            for d in range(-_APPLY_NEIGHBOR_ROWS, _APPLY_NEIGHBOR_ROWS + 1):
                j = si + d
                if 0 <= j < len(kids):
                    to_refresh.add(kids[j])
        for iid in to_refresh:
            row = rows_by_iid.get(iid)
            if row is not None:
                _refresh_row_display(iid, row)

    def _set_ocr_apply_context(source_iid: str, srt_numbers: set[int]) -> None:
        nonlocal _ocr_apply_source_iid, _ocr_apply_srt_numbers
        _ocr_apply_source_iid = source_iid
        _ocr_apply_srt_numbers = set(srt_numbers)
        for rid, r in rows_by_iid.items():
            _refresh_row_display(rid, r)

    def _override_key(path: Path) -> str:
        try:
            return str(path.resolve())
        except OSError:
            return str(path)

    def _save_row_override(row: MatchPreview) -> None:
        k = _override_key(row.source)
        manual_overrides[k] = {
            "srt_number": int(row.srt_number) if row.srt_number >= 0 else -1,
            "target_name": row.target_name,
            "cue_text": row.cue_text,
            "word_srt_number": int(row.word_srt_number) if row.word_srt_number >= 0 else -1,
            "word_cue_text": row.word_cue_text,
            "status": row.status,
            "match_reason": row.match_reason,
        }
        try:
            save_manual_overrides(manual_overrides)
        except OSError:
            pass

    def _apply_row_override(row: MatchPreview) -> None:
        ov = manual_overrides.get(_override_key(row.source))
        if not isinstance(ov, dict):
            return
        try:
            srt_no = int(ov.get("srt_number", row.srt_number))
        except (TypeError, ValueError):
            srt_no = row.srt_number
        if srt_no >= 0:
            row.srt_number = srt_no
            row.target_name = str(ov.get("target_name") or srt_png_name(srt_no))
            cue = str(ov.get("cue_text") or "").strip()
            if cue:
                row.cue_text = cue
            row.matched = True
            row.can_rename = True
            row.status = str(ov.get("status") or f"수동 저장: {row.target_name}")
            row.match_reason = str(ov.get("match_reason") or "수동 저장")
        try:
            wno = int(ov.get("word_srt_number", row.word_srt_number))
            row.word_srt_number = wno
        except (TypeError, ValueError):
            pass
        wcue = str(ov.get("word_cue_text") or "").strip()
        if wcue:
            row.word_cue_text = wcue

    def open_keyword_search_window() -> None:
        nonlocal _search_win
        if _search_win is not None and _search_win.winfo_exists():
            _search_win.lift()
            _search_win.focus_force()
            return

        win = tk.Toplevel(root)
        _search_win = win
        win.title("대본·OCR 키워드 검색")
        win.transient(root)
        win.geometry("780x520")
        win.minsize(520, 360)

        kw_var = tk.StringVar(value="")
        ocr_kw_var = tk.StringVar(value="")
        win_status = tk.StringVar(value="대본·OCR 키워드를 입력하고 [검색]을 누르세요.")

        outer = ttk.Frame(win, padding=10)
        outer.pack(fill=tk.BOTH, expand=True)
        outer.grid_columnconfigure(1, weight=1)
        outer.grid_rowconfigure(3, weight=1)

        ttk.Label(outer, text="대본 키워드").grid(
            row=0, column=0, sticky="w", padx=(0, 8)
        )
        kw_ent = ttk.Entry(outer, textvariable=kw_var, width=40)
        kw_ent.grid(row=0, column=1, sticky="ew", padx=(0, 8))
        kw_ent.focus_set()

        ttk.Label(outer, text="OCR 검색").grid(
            row=1, column=0, sticky="w", padx=(0, 8), pady=(6, 0)
        )
        ocr_ent = ttk.Entry(outer, textvariable=ocr_kw_var, width=40)
        ocr_ent.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=(6, 0))

        btn_row = ttk.Frame(outer)
        btn_row.grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 6))

        list_frm = ttk.LabelFrame(
            outer,
            text="검색 결과 (더블클릭 → 부모 목록에서 해당 대본 행)",
            padding=6,
        )
        list_frm.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(0, 6))
        list_frm.grid_columnconfigure(0, weight=1)
        list_frm.grid_rowconfigure(0, weight=1)

        hits_lb = tk.Listbox(list_frm, font=(fam, sz))
        hits_vsb = ttk.Scrollbar(list_frm, orient=tk.VERTICAL, command=hits_lb.yview)
        hits_lb.configure(yscrollcommand=hits_vsb.set)
        hits_lb.grid(row=0, column=0, sticky="nsew")
        hits_vsb.grid(row=0, column=1, sticky="ns")

        hits_by_id: dict[int, str] = {}

        ttk.Label(outer, textvariable=win_status, foreground="#444444").grid(
            row=4, column=0, columnspan=2, sticky="w"
        )

        def _fill_hits(lines: list[tuple[int, str]]) -> None:
            hits_lb.delete(0, tk.END)
            hits_by_id.clear()
            for map_id, text in lines[:800]:
                hits_by_id[int(map_id)] = text
                line = text.replace("\n", " ").strip()
                hits_lb.insert(tk.END, f"{map_id:4d}  |  {line[:240]}")

        def _parse_hit_line(line: str) -> int | None:
            try:
                return int(line.split("|", 1)[0].strip())
            except ValueError:
                return None

        def do_search() -> None:
            kw = kw_var.get().strip()
            ocr_kw = ocr_kw_var.get().strip()
            if not kw and not ocr_kw:
                messagebox.showinfo(
                    "검색",
                    "대본 키워드 또는 OCR 검색어를 입력하세요.",
                    parent=win,
                )
                return
            lines: list[tuple[int, str]] = []
            seen_ids: set[int] = set()

            if kw:
                srt = Path(srt_var.get().strip())
                if not srt.is_file():
                    messagebox.showerror(
                        "SRT", f"대본 파일이 없습니다:\n{srt}", parent=win
                    )
                    return
                try:
                    for map_id, text in search_srt_cues(srt, kw):
                        mid = int(map_id)
                        if mid not in seen_ids:
                            seen_ids.add(mid)
                            lines.append((mid, f"[대본] {text}"))
                except OSError as e:
                    messagebox.showerror("대본 검색", str(e), parent=win)
                    return

            if ocr_kw:
                okw = ocr_kw.lower()
                for row in _all_rows_cache:
                    if row.srt_number < 0:
                        continue
                    blob = " ".join(
                        (
                            row.ocr_preview or "",
                            row.word_cue_text or "",
                            row.match_reason or "",
                        )
                    ).lower()
                    if okw not in blob:
                        continue
                    mid = row.srt_number
                    if mid in seen_ids:
                        continue
                    seen_ids.add(mid)
                    ocr_bit = (row.ocr_preview or "—")[:120]
                    lines.append((mid, f"[OCR] {ocr_bit}"))

            lines.sort(key=lambda h: int(h[0]))
            if not lines:
                _fill_hits([])
                win_status.set("검색 결과가 없습니다.")
                return
            _fill_hits(lines)
            win_status.set(f"검색 {len(lines)}건 (대본·OCR)")

        def on_hit_double(_event: tk.Event | None = None) -> None:
            sel = hits_lb.curselection()
            if not sel:
                return
            num = _parse_hit_line(hits_lb.get(sel[0]))
            if num is None:
                return
            chosen = tree.selection()
            if not chosen:
                messagebox.showinfo(
                    "번호 지정",
                    "부모창에서 번호를 지정할 PNG 행을 먼저 선택하세요.\n"
                    "(목록에서 한 줄 클릭 후 다시 더블클릭)",
                    parent=win,
                )
                return
            iid = chosen[0]
            row = rows_by_iid.get(iid)
            if row is None:
                return

            if _commit_script_number(row, str(num), iid):
                status_var.set(f"대본 {num}번 → {srt_png_name(num)}")
                on_close()

        def on_close() -> None:
            nonlocal _search_win
            _search_win = None
            win.destroy()

        ttk.Button(btn_row, text="검색", command=do_search, width=10).pack(
            side=tk.LEFT, padx=(0, 6)
        )
        ttk.Button(btn_row, text="닫기", command=on_close, width=8).pack(side=tk.LEFT)

        hits_lb.bind("<Double-1>", on_hit_double)
        kw_ent.bind("<Return>", lambda _e: do_search())
        ocr_ent.bind("<Return>", lambda _e: do_search())
        win.protocol("WM_DELETE_WINDOW", on_close)

    root.after(200, _apply_preview_pane_width)
    root.after(250, _update_preview_wrap)

    def on_thumb_double_click(_event: tk.Event) -> None:
        if _preview_path is not None:
            open_large_viewer(_preview_path, ocr_words=_preview_ocr)

    thumb_img_lbl.bind("<Double-1>", on_thumb_double_click)

    sel_btns = ttk.Frame(frm)
    sel_btns.grid(row=9, column=0, sticky="w", pady=(0, 6))
    ttk.Button(sel_btns, text="대본·OCR 검색…", command=open_keyword_search_window).pack(
        side=tk.LEFT, padx=(16, 0)
    )
    ttk.Button(sel_btns, text="전체 ☑", command=lambda: set_all_checked(True)).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(sel_btns, text="선택 해제", command=lambda: set_all_checked(False)).pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Button(
        sel_btns, text="변경 가능만 ☑", command=lambda: set_all_matched(True)
    ).pack(side=tk.LEFT)

    prog = ttk.Progressbar(frm, mode="determinate", maximum=100)
    prog.grid(row=11, column=0, sticky="ew", pady=(0, 4))

    btn_scan: ttk.Button
    btn_cancel_scan: ttk.Button
    btn_save: ttk.Button
    btn_delete: ttk.Button
    btn_normalize: ttk.Button

    def _load_table_from_disk() -> bool:
        """SRT·PNG 폴더 기준으로 목록을 다시 읽어 표시 (OCR 없음)."""
        srt = Path(srt_var.get().strip())
        png = Path(png_var.get().strip())
        if not srt.is_file():
            messagebox.showerror("SRT", f"파일이 없습니다:\n{srt}")
            return False
        if not png.is_dir():
            messagebox.showerror("PNG 폴더", f"폴더가 없습니다:\n{png}")
            return False
        reload_table()
        return True

    def run_refresh() -> None:
        persist()
        refresh_count()
        _load_table_from_disk()

    scan_cancel_event = threading.Event()

    def set_busy(on: bool) -> None:
        state = tk.DISABLED if on else tk.NORMAL
        btn_scan.configure(state=state)
        btn_cancel_scan.configure(state=tk.NORMAL if on else tk.DISABLED)
        btn_save.configure(state=state)
        btn_delete.configure(state=state)
        btn_normalize.configure(state=state)
        btn_refresh.configure(state=state)
        for w in browse_widgets:
            try:
                w.configure(state=state)
            except tk.TclError:
                pass

    def persist(*, preview_width: int | None = None) -> None:
        try:
            pw = preview_width
            if pw is None and table_body.winfo_exists():
                pw = _preview_pane_width()
            try:
                ts = int(thumb_size_var.get())
            except (tk.TclError, ValueError):
                ts = thumb_size[0]
            ts = max(_THUMB_SIZE_MIN, min(_THUMB_SIZE_MAX, ts))
            thumb_size[0] = ts
            save_gui_settings(
                srt_file=srt_var.get().strip(),
                png_dir=png_var.get().strip(),
                download_dir=download_var.get().strip(),
                preview_pane_width=pw,
                preview_thumb_size=ts,
            )
        except (OSError, tk.TclError):
            pass

    def _validate_paths() -> tuple[Path, Path] | None:
        srt = Path(srt_var.get().strip())
        png = Path(png_var.get().strip())
        if not srt.is_file():
            messagebox.showerror("SRT", f"파일이 없습니다:\n{srt}")
            return None
        if not png.is_dir():
            messagebox.showerror("PNG 폴더", f"폴더가 없습니다:\n{png}")
            return None
        try:
            from png_rename.ocr import ensure_tesseract_cmd

            ensure_tesseract_cmd()
        except RuntimeError as e:
            messagebox.showerror("Tesseract OCR", str(e))
            return None
        return srt, png

    def cancel_scan() -> None:
        if not scan_cancel_event.is_set():
            scan_cancel_event.set()
            btn_cancel_scan.configure(state=tk.DISABLED)
            status_var.set("목록 조회 취소 중…")

    def run_scan() -> None:
        paths = _validate_paths()
        if paths is None:
            return
        srt, png = paths
        persist()
        clear_table()
        scan_cancel_event.clear()
        set_busy(True)
        prog.configure(value=0)
        status_var.set("OCR·매칭 목록 조회 중…")

        def work() -> None:
            err: Exception | None = None
            all_rows: list[MatchPreview] = []
            def on_prog(i: int, total: int, name: str) -> None:
                pct = 0 if total <= 0 else int(100 * i / total)

                def ui() -> None:
                    prog.configure(value=pct)
                    status_var.set(f"OCR·매칭 중… {pct}% ({i}/{total}) {name}")

                safe_after(root, ui)

            def show_skeleton_ui() -> None:
                try:
                    skel = build_srt_centric_skeleton(
                        srt,
                        png,
                        recursive=bool(recursive_var.get()),
                    )
                except Exception as e:
                    status_var.set(f"목록 로드 오류: {e}")
                    return
                _refresh_srt_name_choices()
                for row in skel:
                    _apply_row_override(row)
                _all_rows_cache[:] = skel
                _remap_rows_from_filenames()
                _sort_tree_by_srt_asc(refresh_heading=True)
                status_var.set(
                    f"대본 {len(_all_rows_cache)}행 (대본번호 오름차순) · OCR·매칭 분석 중…"
                )

            safe_after(root, show_skeleton_ui)

            try:
                all_rows = scan_srt_centric_matches(
                    srt,
                    png,
                    recursive=bool(recursive_var.get()),
                    skip_already_named=skip_already_named,
                    on_progress=on_prog,
                    should_cancel=scan_cancel_event.is_set,
                )
            except ScanCancelledError as e:
                err = e
            except Exception as e:
                err = e
                traceback.print_exc()

            def done() -> None:
                set_busy(False)
                if isinstance(err, ScanCancelledError):
                    prog.configure(value=0)
                    status_var.set(
                        f"목록 조회 취소됨 · 대본 {len(_all_rows_cache)}행 (OCR·매칭 미완료)"
                    )
                    return
                if err:
                    prog.configure(value=0)
                    messagebox.showerror("오류", str(err))
                    status_var.set("조회 오류")
                    return
                n_cues = len(srt_cue_map)
                n_ok = sum(1 for r in all_rows if r.matched)
                n_bad = sum(1 for r in all_rows if not r.matched and "썸네일" not in r.status)
                n_missing = sum(1 for r in all_rows if r.status == "이미지 없음")
                n_rename = sum(1 for r in all_rows if r.can_rename)
                _refresh_srt_name_choices()
                for row in all_rows:
                    _apply_row_override(row)
                _all_rows_cache[:] = all_rows
                _remap_rows_from_filenames()
                _sort_tree_by_srt_asc(refresh_heading=True)
                show_all_rows()
                n_with_ocr = sum(1 for r in all_rows if (r.ocr_preview or "").strip())
                prog.configure(value=100)
                n_sel = len(selected_row_ids)
                status_var.set(
                    f"조회 완료: 대본 {n_cues}개 · 표시 {len(all_rows)}행 · "
                    f"이미지 없음 {n_missing} · 일치 {n_ok} · 불일치 {n_bad} · "
                    f"이름변경 가능 {n_rename} · 선택 {n_sel}"
                )

            safe_after(root, done)

        threading.Thread(target=work, daemon=True).start()

    def _rows_for_save() -> list[MatchPreview]:
        if selected_row_ids:
            return [r for r in _all_rows_cache if id(r) in selected_row_ids]
        sel = tree.selection()
        if sel and sel[0] in rows_by_iid:
            return [rows_by_iid[sel[0]]]
        return []

    def run_save_rename() -> None:
        selected_rows = _rows_for_save()
        if not selected_rows:
            messagebox.showwarning(
                "선택 없음",
                "이름을 바꿀 항목을 ☑ 선택하거나 목록에서 한 줄을 클릭하세요.\n"
                "현재 파일명은 셀 더블클릭으로 수정할 수 있습니다.",
            )
            return

        pending_raw: list[MatchPreview] = []
        for r in selected_rows:
            norm_tgt = _normalize_target_name(r.target_name)
            if norm_tgt is not None:
                r.target_name = norm_tgt
                tgt = norm_tgt
            else:
                tgt = (r.target_name or "").strip()
                if tgt in ("", "—") and r.srt_number >= 0:
                    r.target_name = srt_png_name(r.srt_number)
                    tgt = r.target_name
            if tgt not in ("", "—"):
                pending_raw.append(r)
        if not pending_raw:
            messagebox.showwarning(
                "저장 불가",
                "현재 파일명을 SRT_XXX.png 형식으로 지정하거나\n"
                "대본 번호를 먼저 지정하세요.",
            )
            return

        prep_errors: list[str] = []
        pending: list[MatchPreview] = []
        for row in pending_raw:
            map_err = _auto_resolve_row_mapping_for_save(row)
            if map_err:
                label = (
                    f"대본 {row.srt_number}번"
                    if row.srt_number >= 0
                    else row.source.name
                )
                prep_errors.append(f"  {label}: {map_err}")
                continue
            err = _prepare_row_for_rename(row)
            if err == "이미 해당 파일명입니다":
                continue
            if err == _SKIP_NO_SOURCE:
                continue
            if err:
                label = (
                    f"대본 {row.srt_number}번"
                    if row.srt_number >= 0
                    else row.source.name
                )
                prep_errors.append(f"  {label}: {err}")
            else:
                pending.append(row)

        if not pending and not prep_errors:
            messagebox.showinfo(
                "저장",
                "선택한 파일은 이미 지정한 파일명과 같습니다.\n"
                "다른 이름으로 바꾸려면 「현재 파일명」을 더블클릭해 수정하세요.",
            )
            return

        if prep_errors and not pending:
            messagebox.showwarning(
                "저장 불가",
                "선택한 항목을 이름 변경할 수 없습니다.\n\n"
                + "\n".join(prep_errors[:10]),
            )
            return
        if prep_errors:
            extra = f"\n  … 외 {len(prep_errors) - 5}건" if len(prep_errors) > 5 else ""
            if not messagebox.askyesno(
                "일부 항목 제외",
                f"{len(prep_errors)}개 항목은 제외하고 {len(pending)}개만 변경합니다.\n\n"
                + "\n".join(prep_errors[:5])
                + extra
                + "\n\n계속하시겠습니까?",
            ):
                return

        if not pending:
            return

        names = "\n".join(
            f"  {r.source.name}  →  {r.target_name}" for r in pending[:12]
        )
        extra = f"\n  … 외 {len(pending) - 12}개" if len(pending) > 12 else ""
        if not messagebox.askyesno(
            "저장 (파일명 변경)",
            f"{len(pending)}개 파일을 디스크에서 이름을 변경합니다.\n\n{names}{extra}",
        ):
            return

        set_busy(True)
        prog.configure(value=0)
        status_var.set("선택 항목 이름 변경 중…")

        def work() -> None:
            err: Exception | None = None
            results: list[RenameResult] = []
            apply_skips: list[RenameSkip] = []

            def on_prog(i: int, total: int, item: RenameResult | RenameSkip) -> None:
                pct = 0 if total <= 0 else int(100 * i / total)

                def ui() -> None:
                    prog.configure(value=pct)
                    if isinstance(item, RenameResult):
                        status_var.set(
                            f"변경 중… {pct}% — {item.source.name} → {item.target.name}"
                        )

                safe_after(root, ui)

            try:
                results, apply_skips = apply_match_renames(
                    pending, manual=True, on_progress=on_prog
                )
            except ScanCancelledError as e:
                err = e
            except Exception as e:
                err = e
                traceback.print_exc()

            def done() -> None:
                set_busy(False)
                refresh_count()
                if err:
                    messagebox.showerror("오류", str(err))
                    status_var.set("변경 오류")
                    return
                _apply_rename_results(results, pending)
                _purge_stale_rows_after_rename(results)
                for row in pending:
                    _rename_source_by_row.pop(id(row), None)
                for r in results:
                    try:
                        _ocr_cache_keys.discard(_ocr_cache_key(r.source))
                    except OSError:
                        pass
                    _ocr_cache_keys.add(_ocr_cache_key(r.target))
                reload_table(
                    status_msg=(
                        f"완료: 변경 {len(results)}개, 실패 {len(apply_skips)}개 · 목록 갱신"
                    ),
                    quiet=True,
                )
                prog.configure(value=100)
                skip_msg = ""
                if apply_skips:
                    lines = [
                        f"  {s.source.name}: {s.reason}" for s in apply_skips[:8]
                    ]
                    skip_msg = "\n\n건너뜀:\n" + "\n".join(lines)
                    if len(apply_skips) > 8:
                        skip_msg += f"\n  … 외 {len(apply_skips) - 8}건"
                messagebox.showinfo(
                    "완료",
                    f"이름 변경: {len(results)}개\n실패·건너뜀: {len(apply_skips)}개"
                    f"{skip_msg}\n\n목록을 다시 불러왔습니다.",
                )

            safe_after(root, done)

        threading.Thread(target=work, daemon=True).start()

    def run_delete_selected() -> None:
        selected_rows = _collect_delete_targets()
        if not selected_rows:
            messagebox.showwarning(
                "선택 없음",
                "삭제할 줄을 ☑ 하거나 목록에서 줄을 클릭한 뒤 삭제하세요.",
            )
            return

        names = "\n".join(
            f"  {p.name}"
            for r in selected_rows[:15]
            if (p := _current_file_path(r)) is not None
        )
        extra = (
            f"\n  … 외 {len(selected_rows) - 15}개" if len(selected_rows) > 15 else ""
        )
        if not messagebox.askyesno(
            "파일 삭제 확인",
            f"{len(selected_rows)}개 PNG 파일을 디스크에서 삭제합니다.\n"
            "복구할 수 없습니다.\n\n"
            f"{names}{extra}\n\n계속하시겠습니까?",
            icon="warning",
        ):
            return

        deleted = 0
        failed: list[str] = []
        preview_path = None
        if tree.selection():
            row = rows_by_iid.get(tree.selection()[0])
            if row:
                preview_path = row.source

        for row in selected_rows:
            path = _current_file_path(row)
            if path is None:
                failed.append(f"{row.srt_number}번: 파일 없음")
                continue
            try:
                path.unlink()
                deleted += 1
            except OSError as e:
                failed.append(f"{path.name}: {e}")

        # 삭제된 이미지에 대한 수동 저장값도 정리
        changed_ov = False
        for row in selected_rows:
            k = _override_key(row.source)
            if k in manual_overrides:
                manual_overrides.pop(k, None)
                changed_ov = True
        if changed_ov:
            try:
                save_manual_overrides(manual_overrides)
            except OSError:
                pass

        for row in selected_rows:
            selected_row_ids.discard(id(row))

        reload_table(quiet=True)

        if preview_path and not preview_path.is_file():
            clear_preview()

        refresh_count()
        status_var.set(
            f"삭제 완료: {deleted}개"
            + (f", 실패 {len(failed)}개" if failed else "")
            + f" · 대본 {len(_all_rows_cache)}행"
        )
        if failed:
            messagebox.showwarning(
                "삭제 일부 실패",
                f"삭제됨: {deleted}개\n실패: {len(failed)}개\n\n" + "\n".join(failed[:8]),
            )
        else:
            messagebox.showinfo("삭제 완료", f"{deleted}개 파일을 삭제했습니다.")

    def run_normalize_filenames() -> None:
        png = Path(png_var.get().strip())
        if not png.is_dir():
            messagebox.showerror("PNG 폴더", f"폴더가 없습니다:\n{png}")
            return
        persist()
        pairs = find_srt_filename_normalizations(
            png, recursive=bool(recursive_var.get())
        )
        if not pairs:
            messagebox.showinfo(
                "파일명 정규화",
                "정규화할 파일이 없습니다.\n"
                "(예: SRT_240_8084dc2e.png → SRT_240.png)",
            )
            return

        preview = "\n".join(
            f"  {src.name}  →  {tgt}" for src, tgt in pairs[:15]
        )
        extra = f"\n  … 외 {len(pairs) - 15}개" if len(pairs) > 15 else ""
        if not messagebox.askyesno(
            "파일명 정규화",
            f"{len(pairs)}개 파일의 접미사를 제거합니다.\n\n{preview}{extra}\n\n"
            "계속하시겠습니까?",
        ):
            return

        set_busy(True)
        prog.configure(value=0)
        status_var.set("파일명 정규화 중…")

        def work() -> None:
            err: Exception | None = None
            results: list[RenameResult] = []
            skips: list[RenameSkip] = []

            def on_prog(i: int, total: int, item: RenameResult | RenameSkip) -> None:
                pct = 0 if total <= 0 else int(100 * i / total)

                def ui() -> None:
                    prog.configure(value=pct)
                    if isinstance(item, RenameResult):
                        status_var.set(
                            f"정규화… {pct}% — {item.source.name} → {item.target.name}"
                        )

                safe_after(root, ui)

            try:
                results, skips = apply_srt_filename_normalizations(
                    pairs, on_progress=on_prog
                )
            except Exception as e:
                err = e
                traceback.print_exc()

            def done() -> None:
                set_busy(False)
                refresh_count()
                if err:
                    messagebox.showerror("오류", str(err))
                    status_var.set("정규화 오류")
                    return
                if rows_by_iid:
                    reload_table(
                        status_msg=(
                            f"정규화 완료: {len(results)}개, "
                            f"건너뜀 {len(skips)}개 · 목록 갱신"
                        ),
                        quiet=True,
                    )
                else:
                    status_var.set(
                        f"정규화 완료: {len(results)}개, 건너뜀 {len(skips)}개"
                    )
                prog.configure(value=100)
                skip_msg = ""
                if skips:
                    lines = [f"  {s.source.name}: {s.reason}" for s in skips[:8]]
                    skip_msg = "\n\n건너뜀:\n" + "\n".join(lines)
                    if len(skips) > 8:
                        skip_msg += f"\n  … 외 {len(skips) - 8}건"
                messagebox.showinfo(
                    "정규화 완료",
                    f"변경: {len(results)}개\n건너뜀: {len(skips)}개{skip_msg}",
                )

            safe_after(root, done)

        threading.Thread(target=work, daemon=True).start()

    row_btns = ttk.Frame(frm)
    row_btns.grid(row=13, column=0, sticky="ew", pady=(8, 0))
    btn_scan = ttk.Button(row_btns, text="① 목록 조회 (OCR·매칭)", command=run_scan)
    btn_scan.pack(side=tk.LEFT, padx=(0, 10))
    btn_cancel_scan = ttk.Button(
        row_btns, text="조회 취소", command=cancel_scan, state=tk.DISABLED
    )
    btn_cancel_scan.pack(side=tk.LEFT, padx=(0, 10))
    btn_save = ttk.Button(row_btns, text="② 저장 (파일명 변경)", command=run_save_rename)
    btn_save.pack(side=tk.LEFT, padx=(0, 10))
    btn_delete = ttk.Button(row_btns, text="선택 줄 삭제", command=run_delete_selected)
    btn_delete.pack(side=tk.LEFT, padx=(0, 10))
    btn_normalize = ttk.Button(
        row_btns, text="파일명 정규화", command=run_normalize_filenames
    )
    btn_normalize.pack(side=tk.LEFT, padx=(0, 10))
    btn_refresh = ttk.Button(row_btns, text="새로고침", command=run_refresh)
    btn_refresh.pack(side=tk.LEFT)
    def on_delete_key(_event: tk.Event | None = None) -> None:
        w = root.focus_get()
        if w is not None and w.winfo_class() in ("Entry", "TEntry", "TCombobox"):
            return
        if rows_by_iid:
            run_delete_selected()

    root.bind("<Delete>", on_delete_key)
    action_widgets.extend([btn_scan, btn_save, btn_delete, btn_normalize, btn_refresh])

    def on_close() -> None:
        nonlocal _search_win
        if _search_win is not None:
            try:
                if _search_win.winfo_exists():
                    _search_win.destroy()
            except tk.TclError:
                pass
            _search_win = None
        persist()

    bind_close(root, standalone, on_close)
    if not standalone:
        bind_hub_destroy(root, on_close)

    def startup_load_default_folder() -> None:
        png_var.set(str(resolve_initial_png_dir(None, cfg.get("png_dir"))))
        srt_var.set(str(resolve_initial_srt(None, cfg.get("srt_file"))))
        refresh_count()
        png = Path(png_var.get().strip())
        srt = Path(srt_var.get().strip())
        if png.is_dir() and srt.is_file():
            _load_table_from_disk()
        status_var.set("")

    refresh_count()
    root.after(200, startup_load_default_folder)
    run_mainloop(root, standalone)
