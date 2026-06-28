# -*- coding: utf-8 -*-
"""SRT 구간별 무료 스톡 영상 검색·적용 GUI."""

from __future__ import annotations

import sys
import threading
import traceback
import tkinter as tk
from dataclasses import dataclass, field
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk

from mp4_search import __version__
from mp4_search.image_effects import (
    PNG_EFFECT_BY_LABEL,
    PNG_EFFECT_LABELS_LIST,
    normalize_png_effect,
    png_effect_label,
)
from mp4_search.download import (
    ComposeStopped,
    _probe_media_duration,
    abort_compose_ffmpeg,
    compose_timeline_to_all_mp4,
    copy_local_image_as_png,
    optimize_srt_images_in_folder,
    copy_local_video,
    download_thumbnail,
    download_url,
    find_download_asset,
    play_video,
    temp_preview_path,
    trim_video,
)
from mp4_search.naming import (
    ALL_MP4_NAME,
    scan_srt_assets,
    srt_mp4_name,
    srt_png_name,
    timeline_asset_number,
    parse_srt_asset_number,
)
from mp4_search.timeline_compose import (
    build_asset_start_times_from_srt,
    clip_duration_until_next_asset,
    compose_asset_statuses,
    folder_asset_display_owners,
    folder_asset_for_cue_row,
    format_compose_debug_log,
    format_jobs_timeline_summary,
    format_timeline_compose_status,
    list_timeline_compose_jobs,
    missing_timeline_mp4_slots,
    timeline_total_sec,
)
from mp4_search.paths import default_output_dir, mp3_candidates_for_srt, resolve_mp3_for_srt, stock_api_config_write_path
from mp4_search.settings import (
    load_download_mp4_inputs,
    load_gui_settings,
    save_download_mp4_inputs,
    save_gui_settings,
)
from mp4_search.srt_parse import format_ms_short, parse_srt_cues_timed
from mp4_search.stock_images import StockImage, image_cache_key, search_stock_images
from mp4_search.stock_search import (
    StockVideo,
    api_keys_status,
    normalize_search_query,
    search_stock_videos,
    video_cache_key,
)
from mp4_search.translate_util import search_query_from_cue
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

_THUMB_W = 160
_PREVIEW_PANE_DEFAULT = 520
_TREE_ROW_PX = 22
_COL_KEYWORD = "keyword"
_COL_DOWNLOAD = "download_mp4"
_COL_MP4 = "mp4_file"
_COL_PNG_FX = "png_fx"
_COL_CUE = "cue"
_KEYWORD_COL_WIDTH = 140
_VIDEO_DROP_EXTS = frozenset({".mp4", ".mov", ".webm", ".mkv", ".m4v", ".avi"})
_PROVIDER_LABELS = {"pexels": "Pexels", "pixabay": "Pixabay", "mixkit": "Mixkit"}


@dataclass
class CueRow:
    srt_id: int
    cue_text: str
    time_start: str = ""
    time_end: str = ""
    cue_duration_sec: float = 0.0
    timeline_start_sec: float = 0.0
    timeline_end_sec: float = 0.0
    clip_start_sec: float = 0.0
    clip_end_sec: float = 0.0
    main_text: str = ""
    cue_ids: list[int] = field(default_factory=list)
    mp4_path: Path | None = None
    png_path: Path | None = None
    png_effect: str = "fixed"
    query: str = ""
    results: list[StockVideo] = field(default_factory=list)
    image_results: list[StockImage] = field(default_factory=list)
    selected: StockVideo | None = None
    selected_image: StockImage | None = None
    preview_path: Path | None = None
    preview_paths: dict[str, Path] = field(default_factory=dict)
    image_preview_paths: dict[str, Path] = field(default_factory=dict)
    compose_status: str = ""


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
        bind_file_drop,
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
        title=f"7_3 mp4Search {__version__}",
        minsize=(1100, 640),
        geometry="1280x760",
    )
    if standalone and sys.platform == "win32":
        try:
            root.state("zoomed")
        except tk.TclError:
            pass
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    srt_var = tk.StringVar(value=cfg.get("srt_file", ""))
    mp4_var = tk.StringVar(value=cfg.get("mp4_dir", "") or str(default_output_dir()))
    mp3_var = tk.StringVar(value=cfg.get("mp3_file", ""))
    download_default = cfg.get("download_dir") or str(Path.home() / "Downloads")
    download_var = tk.StringVar(value=download_default)
    status_var = tk.StringVar(value="SRT 파일을 선택한 뒤 「① 목록 조회」를 누르세요.")
    query_var = tk.StringVar(value="")
    keyword_var = tk.StringVar(value="")
    busy = {"v": False}
    search_busy = {"v": False}
    compose_busy = {"v": False}
    compose_cancel = threading.Event()
    rows: dict[str, CueRow] = {}
    download_mp4_inputs: dict[str, str] = load_download_mp4_inputs()
    thumb_refs: list[tk.PhotoImage] = []
    preview_pane_w = int(cfg.get("preview_pane_width", str(_PREVIEW_PANE_DEFAULT)) or _PREVIEW_PANE_DEFAULT)

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(5, weight=3)
    frm.grid_rowconfigure(7, weight=1)

    def persist() -> None:
        nonlocal preview_pane_w
        try:
            preview_pane_w = _preview_pane_width_from_sash()
        except NameError:
            pass
        save_gui_settings(
            srt_file=srt_var.get().strip(),
            mp4_dir=mp4_var.get().strip(),
            download_dir=download_var.get().strip(),
            mp3_file=mp3_var.get().strip(),
            preview_pane_width=str(preview_pane_w),
        )

    def suggest_mp3_from_srt() -> Path | None:
        if mp3_var.get().strip() and Path(mp3_var.get().strip()).is_file():
            return Path(mp3_var.get().strip())
        srt = Path(srt_var.get().strip())
        if not srt.is_file():
            return None
        found = resolve_mp3_for_srt(srt)
        if found:
            mp3_var.set(str(found))
            return found
        return None

    def set_busy(on: bool) -> None:
        busy["v"] = on
        if not compose_busy["v"]:
            for w in (btn_load, btn_apply, btn_optimize_img, btn_compose, btn_play):
                w.state(["disabled"] if on else ["!disabled"])
        if not search_busy["v"] and not compose_busy["v"]:
            btn_search.state(["disabled"] if on else ["!disabled"])

    def set_search_busy(on: bool) -> None:
        search_busy["v"] = on
        btn_search.state(["disabled"] if on else ["!disabled"])
        if on:
            for w in (btn_load, btn_apply, btn_optimize_img, btn_compose, btn_play):
                w.state(["disabled"])
        elif not busy["v"] and not compose_busy["v"]:
            for w in (btn_load, btn_apply, btn_optimize_img, btn_compose, btn_play):
                w.state(["!disabled"])

    def set_compose_busy(on: bool) -> None:
        compose_busy["v"] = on
        btn_compose.state(["disabled"] if on else ["!disabled"])
        btn_compose_stop.state(["!disabled"] if on else ["disabled"])
        if on:
            for w in (btn_load, btn_apply, btn_optimize_img, btn_play):
                w.state(["disabled"])
            btn_search.state(["disabled"])
        elif not busy["v"] and not search_busy["v"]:
            for w in (btn_load, btn_apply, btn_optimize_img, btn_compose, btn_play):
                w.state(["!disabled"])
            btn_search.state(["!disabled"])

    def mp4_dir() -> Path:
        p = Path(mp4_var.get().strip() or default_output_dir())
        p.mkdir(parents=True, exist_ok=True)
        return p

    path_fr = ttk.Frame(frm)
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    path_fr.grid_columnconfigure(1, weight=1)

    ttk.Label(path_fr, text="SRT", width=8).grid(row=0, column=0, sticky="w")
    srt_ent = ttk.Entry(path_fr, textvariable=srt_var)
    srt_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6))

    def pick_srt() -> None:
        init = Path(srt_var.get().strip()) if srt_var.get().strip() else Path.home()
        if init.is_file():
            init = init.parent
        p = filedialog.askopenfilename(
            title="SRT 파일",
            initialdir=folder_dialog_initial(init),
            filetypes=[("SRT", "*.srt"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        touch_workspace_from_path(p)
        srt_var.set(p)
        suggest_mp3_from_srt()
        persist()

    ttk.Button(path_fr, text="찾기…", command=pick_srt).grid(row=0, column=2)

    ttk.Label(path_fr, text="MP4 폴더", width=8).grid(row=1, column=0, sticky="w", pady=(6, 0))
    mp4_ent = ttk.Entry(path_fr, textvariable=mp4_var)
    mp4_ent.grid(row=1, column=1, sticky="ew", padx=(4, 6), pady=(6, 0))

    def pick_mp4_dir() -> None:
        init = Path(mp4_var.get().strip()) if mp4_var.get().strip() else default_output_dir()
        p = filedialog.askdirectory(title="MP4 저장 폴더", initialdir=folder_dialog_initial(init))
        if not p:
            return
        touch_workspace_from_path(p)
        mp4_var.set(p)
        persist()

    def view_mp4_folder() -> None:
        d = mp4_dir()
        all_path = d / ALL_MP4_NAME
        if all_path.is_file():
            play_video(all_path)
            status_var.set(f"재생: {all_path.name}")
            return
        row = current_row()
        if row and row.mp4_path and row.mp4_path.is_file():
            play_video(row.mp4_path)
            status_var.set(f"재생: {row.mp4_path.name}")
            return
        if sys_platform_open_folder(d):
            status_var.set(f"폴더 열기: {d}")
        else:
            safe_messagebox(root, "showinfo", "7_3 mp4Search", f"MP4 폴더:\n{d}")

    ttk.Button(path_fr, text="찾기…", command=pick_mp4_dir).grid(row=1, column=2, pady=(6, 0))
    ttk.Button(path_fr, text="조회", command=view_mp4_folder).grid(row=1, column=3, padx=(4, 0), pady=(6, 0))

    ttk.Label(path_fr, text="다운로드", width=8).grid(row=2, column=0, sticky="w", pady=(6, 0))
    download_ent = ttk.Entry(path_fr, textvariable=download_var)
    download_ent.grid(row=2, column=1, sticky="ew", padx=(4, 6), pady=(6, 0))

    def pick_download_dir() -> None:
        init = Path(download_var.get().strip()) if download_var.get().strip() else Path.home() / "Downloads"
        p = filedialog.askdirectory(title="다운로드 폴더", initialdir=folder_dialog_initial(init))
        if not p:
            return
        touch_workspace_from_path(p)
        download_var.set(p)
        persist()

    ttk.Button(path_fr, text="찾기…", command=pick_download_dir).grid(row=2, column=2, pady=(6, 0))

    ttk.Label(path_fr, text="MP3", width=8).grid(row=3, column=0, sticky="w", pady=(6, 0))
    mp3_ent = ttk.Entry(path_fr, textvariable=mp3_var)
    mp3_ent.grid(row=3, column=1, sticky="ew", padx=(4, 6), pady=(6, 0))

    def pick_mp3() -> None:
        init = Path(mp3_var.get().strip()) if mp3_var.get().strip() else Path.home()
        if init.is_file():
            init = init.parent
        elif not init.is_dir():
            srt = Path(srt_var.get().strip())
            init = srt.parent if srt.is_file() else Path.home()
        p = filedialog.askopenfilename(
            title="MP3 파일 (합성 시 음성)",
            initialdir=folder_dialog_initial(init),
            filetypes=[("MP3", "*.mp3"), ("모든 파일", "*.*")],
        )
        if not p:
            return
        touch_workspace_from_path(p)
        mp3_var.set(p)
        persist()

    ttk.Button(path_fr, text="찾기…", command=pick_mp3).grid(row=3, column=2, pady=(6, 0))

    bind_path_row_dnd(
        path_fr,
        srt_ent,
        srt_var,
        mode="file",
        extensions=(".srt",),
        on_set=lambda _p: persist(),
    )
    bind_path_row_dnd(
        path_fr,
        mp4_ent,
        mp4_var,
        mode="dir",
        on_set=lambda _p: persist(),
    )

    bind_path_row_dnd(
        path_fr,
        download_ent,
        download_var,
        mode="dir",
        on_set=lambda _p: persist(),
    )
    bind_path_row_dnd(
        path_fr,
        mp3_ent,
        mp3_var,
        mode="file",
        extensions=(".mp3",),
        on_set=lambda _p: persist(),
    )

    def _refresh_api_hint() -> None:
        providers, cfg_path, loaded = api_keys_status()
        prov = " · ".join(providers)
        if loaded and loaded.name == "stock_api.example.json":
            hint_var.set(
                f"검색: {prov} · API 예시 파일 사용 중 → {stock_api_config_write_path()} 로 복사 권장"
            )
        elif loaded:
            hint_var.set(f"검색: {prov} · API: {loaded}")
        else:
            hint_var.set(f"검색: {prov} · API 키: {cfg_path}")

    hint_var = tk.StringVar(value="")
    hint = ttk.Label(frm, textvariable=hint_var)
    hint.grid(row=1, column=0, sticky="w", pady=(0, 2))
    _refresh_api_hint()

    usage_hint = ttk.Label(
        frm,
        text="④ 합성 → all.mp4 (+ MP3 음성) · SRT# · 동영상 선택 · MP4 열 드롭",
    )
    usage_hint.grid(row=2, column=0, sticky="w", pady=(0, 4))

    ctrl_fr = ttk.Frame(frm)
    ctrl_fr.grid(row=3, column=0, sticky="w", pady=(0, 6))
    btn_load = ttk.Button(ctrl_fr, text="① 목록 조회")
    btn_load.pack(side=tk.LEFT, padx=(0, 8))
    btn_search = ttk.Button(ctrl_fr, text="② 영상검색")
    btn_search.pack(side=tk.LEFT, padx=(0, 8))
    btn_apply = ttk.Button(ctrl_fr, text="③ 적용 (SRT_XXX.mp4 저장)")
    btn_apply.pack(side=tk.LEFT, padx=(0, 8))
    btn_optimize_img = ttk.Button(ctrl_fr, text="이미지 최적화")
    btn_optimize_img.pack(side=tk.LEFT, padx=(0, 8))
    btn_compose = ttk.Button(ctrl_fr, text="④ 합성 (MP4+PNG)")
    btn_compose.pack(side=tk.LEFT, padx=(0, 8))
    btn_compose_stop = ttk.Button(ctrl_fr, text="합성중지", state=["disabled"])
    btn_compose_stop.pack(side=tk.LEFT, padx=(0, 8))
    btn_play = ttk.Button(ctrl_fr, text="▶ 재생")
    btn_play.pack(side=tk.LEFT)
    ttk.Label(ctrl_fr, text="검색 키워드").pack(side=tk.LEFT, padx=(16, 4))
    keyword_ent = ttk.Entry(ctrl_fr, textvariable=keyword_var, width=40)
    keyword_ent.pack(side=tk.LEFT, padx=(0, 4))

    progress_fr = ttk.Frame(frm)
    progress_fr.grid(row=4, column=0, sticky="ew", pady=(0, 4))
    progress_fr.grid_columnconfigure(1, weight=1)
    progress_text_var = tk.StringVar(value="")
    ttk.Label(progress_fr, textvariable=progress_text_var, width=44).grid(row=0, column=0, sticky="w", padx=(0, 8))
    progress_var = tk.DoubleVar(value=0.0)
    progress_bar = ttk.Progressbar(progress_fr, variable=progress_var, maximum=100, mode="determinate", length=320)
    progress_bar.grid(row=0, column=1, sticky="ew")

    table_frm = ttk.Frame(frm)
    table_frm.grid(row=5, column=0, sticky="nsew", pady=(4, 0))
    table_frm.grid_columnconfigure(0, weight=1)
    table_frm.grid_rowconfigure(0, weight=1)

    table_body = ttk.Frame(table_frm)
    table_body.grid(row=0, column=0, sticky="nsew")
    table_body.grid_columnconfigure(0, weight=1)
    table_body.grid_rowconfigure(0, weight=1)

    paned = ttk.Panedwindow(table_body, orient=tk.HORIZONTAL)
    paned.grid(row=0, column=0, sticky="nsew")

    list_frm = ttk.Frame(paned)
    preview_frm = ttk.Frame(paned, padding=8)
    paned.add(list_frm, weight=3)
    paned.add(preview_frm, weight=2)

    def _apply_pane_sash() -> None:
        nonlocal preview_pane_w
        try:
            root.update_idletasks()
            total = paned.winfo_width()
            if total < 400:
                return
            paned.sashpos(0, max(280, total - preview_pane_w))
        except tk.TclError:
            pass

    def _preview_pane_width_from_sash() -> int:
        try:
            return max(240, min(1200, paned.winfo_width() - paned.sashpos(0)))
        except tk.TclError:
            return preview_pane_w
    preview_frm.grid_columnconfigure(0, weight=1)
    preview_frm.grid_rowconfigure(1, weight=2)
    preview_frm.grid_rowconfigure(6, weight=1)

    cols = (
        "srt_no",
        "t_start",
        "t_end",
        "cue",
        "keyword",
        "download_mp4",
        "mp4_file",
        "png_file",
        "png_fx",
        "status",
    )
    tree = ttk.Treeview(list_frm, columns=cols, show="headings", height=14)
    tree.heading("srt_no", text="SRT#")
    tree.heading("t_start", text="시작")
    tree.heading("t_end", text="종료")
    tree.heading("cue", text="SRT 내용")
    tree.heading("keyword", text="검색 키워드")
    tree.heading("download_mp4", text="다운로드파일")
    tree.heading("mp4_file", text="MP4")
    tree.heading("png_file", text="PNG")
    tree.heading("png_fx", text="이미지효과")
    tree.heading("status", text="상태")
    tree.column("srt_no", width=44, anchor=tk.CENTER, stretch=False)
    tree.column("t_start", width=56, anchor=tk.CENTER, stretch=False)
    tree.column("t_end", width=56, anchor=tk.CENTER, stretch=False)
    tree.column("cue", width=150, anchor=tk.W, stretch=False)
    tree.column("keyword", width=_KEYWORD_COL_WIDTH, anchor=tk.W, stretch=False)
    tree.column("download_mp4", width=100, anchor=tk.W, stretch=False)
    tree.column("mp4_file", width=80, anchor=tk.W, stretch=False)
    tree.column("png_file", width=80, anchor=tk.W, stretch=False)
    tree.column("png_fx", width=72, anchor=tk.CENTER, stretch=False)
    tree.column("status", width=56, anchor=tk.CENTER, stretch=False)
    vsb = ttk.Scrollbar(list_frm, orient=tk.VERTICAL, command=tree.yview)
    hsb = ttk.Scrollbar(list_frm, orient=tk.HORIZONTAL, command=tree.xview)
    tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    vsb.grid(row=0, column=1, sticky="ns")
    hsb.grid(row=1, column=0, sticky="ew")
    list_frm.grid_rowconfigure(0, weight=1)
    list_frm.grid_columnconfigure(0, weight=1)

    def _resize_tree(_evt: tk.Event | None = None) -> None:
        try:
            h = max(8, (list_frm.winfo_height() - 28) // _TREE_ROW_PX)
            tree.configure(height=h)
        except tk.TclError:
            pass

    list_frm.bind("<Configure>", _resize_tree)

    ttk.Label(preview_frm, text="동영상 (클릭 미리보기 · [선택] 적용)").grid(row=0, column=0, sticky="w")
    results_wrap = ttk.Frame(preview_frm)
    results_wrap.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
    results_wrap.grid_columnconfigure(0, weight=1)
    results_wrap.grid_rowconfigure(0, weight=1)
    results_canvas = tk.Canvas(results_wrap, highlightthickness=0)
    results_scroll = ttk.Scrollbar(results_wrap, orient=tk.VERTICAL, command=results_canvas.yview)
    results_inner = ttk.Frame(results_canvas)
    results_inner.bind(
        "<Configure>",
        lambda _e: results_canvas.configure(scrollregion=results_canvas.bbox("all")),
    )
    _results_window = results_canvas.create_window((0, 0), window=results_inner, anchor=tk.NW)
    results_canvas.configure(yscrollcommand=results_scroll.set)

    def _on_results_canvas_configure(event: tk.Event) -> None:
        results_canvas.itemconfigure(_results_window, width=event.width)

    results_canvas.bind("<Configure>", _on_results_canvas_configure)
    results_canvas.grid(row=0, column=0, sticky="nsew")
    results_scroll.grid(row=0, column=1, sticky="ns")

    clip_fr = ttk.Frame(preview_frm)
    clip_fr.grid(row=2, column=0, sticky="ew", pady=(4, 4))
    ttk.Label(clip_fr, text="적용 구간(초)").pack(side=tk.LEFT)
    clip_start_var = tk.StringVar(value="0")
    clip_end_var = tk.StringVar(value="")
    clip_start_ent = ttk.Entry(clip_fr, textvariable=clip_start_var, width=6)
    clip_start_ent.pack(side=tk.LEFT, padx=(6, 2))
    ttk.Label(clip_fr, text="~").pack(side=tk.LEFT)
    clip_end_ent = ttk.Entry(clip_fr, textvariable=clip_end_var, width=6)
    clip_end_ent.pack(side=tk.LEFT, padx=(2, 6))
    ttk.Label(clip_fr, text="(종료 비우면 다음 영상/이미지까지)").pack(side=tk.LEFT, padx=(0, 10))
    ttk.Label(clip_fr, text="시작(초)").pack(side=tk.LEFT)
    apply_srt_var = tk.StringVar(value="")
    apply_srt_ent = ttk.Entry(clip_fr, textvariable=apply_srt_var, width=5)
    apply_srt_ent.pack(side=tk.LEFT, padx=(4, 6))
    btn_pick_video = ttk.Button(clip_fr, text="동영상 선택…")
    btn_pick_video.pack(side=tk.LEFT)

    def on_clip_focus_out(_evt=None) -> None:
        row = current_row()
        if row:
            _save_clip_from_ui(row)

    preview_lbl = ttk.Label(preview_frm, text="(영상을 선택하세요)", anchor=tk.W)
    preview_lbl.grid(row=3, column=0, sticky="ew", pady=(2, 4))

    ttk.Label(preview_frm, text="이미지 (더블클릭 크게 · [선택] PNG 저장)").grid(row=4, column=0, sticky="w", pady=(4, 0))
    images_wrap = ttk.Frame(preview_frm)
    images_wrap.grid(row=5, column=0, sticky="nsew", pady=(4, 4))
    images_wrap.grid_columnconfigure(0, weight=1)
    images_wrap.grid_rowconfigure(0, weight=1)
    images_canvas = tk.Canvas(images_wrap, height=120, highlightthickness=0)
    images_scroll = ttk.Scrollbar(images_wrap, orient=tk.VERTICAL, command=images_canvas.yview)
    images_inner = ttk.Frame(images_canvas)
    images_inner.bind(
        "<Configure>",
        lambda _e: images_canvas.configure(scrollregion=images_canvas.bbox("all")),
    )
    _images_window = images_canvas.create_window((0, 0), window=images_inner, anchor=tk.NW)
    images_canvas.configure(yscrollcommand=images_scroll.set)

    def _on_images_canvas_configure(event: tk.Event) -> None:
        images_canvas.itemconfigure(_images_window, width=event.width)

    images_canvas.bind("<Configure>", _on_images_canvas_configure)
    images_canvas.grid(row=0, column=0, sticky="nsew")
    images_scroll.grid(row=0, column=1, sticky="ns")

    def _bind_canvas_wheel(canvas: tk.Canvas) -> None:
        def _wheel(event: tk.Event) -> None:
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

        def _on_enter(_e: tk.Event) -> None:
            canvas.bind_all("<MouseWheel>", _wheel)

        def _on_leave(_e: tk.Event) -> None:
            canvas.unbind_all("<MouseWheel>")

        canvas.bind("<Enter>", _on_enter)
        canvas.bind("<Leave>", _on_leave)

    _bind_canvas_wheel(results_canvas)
    _bind_canvas_wheel(images_canvas)

    ttk.Label(preview_frm, textvariable=query_var).grid(row=6, column=0, sticky="ew")

    ttk.Label(frm, textvariable=status_var).grid(row=6, column=0, sticky="w", pady=(8, 0))

    log_fr = ttk.LabelFrame(frm, text="합성 로그 (완료 후 복사·제출)", padding=4)
    log_fr.grid(row=7, column=0, sticky="nsew", pady=(6, 0))
    log_fr.grid_columnconfigure(0, weight=1)
    log_fr.grid_rowconfigure(1, weight=1)
    log_btn_fr = ttk.Frame(log_fr)
    log_btn_fr.grid(row=0, column=0, sticky="ew", pady=(0, 4))
    compose_log = scrolledtext.ScrolledText(
        log_fr,
        height=7,
        wrap=tk.WORD,
        font=(fam, max(9, sz - 1)),
    )
    compose_log.grid(row=1, column=0, sticky="nsew")
    compose_log.configure(state=tk.DISABLED)

    def append_compose_log(text: str) -> None:
        compose_log.configure(state=tk.NORMAL)
        if compose_log.index("end-1c") != "1.0":
            compose_log.insert(tk.END, "\n")
        compose_log.insert(tk.END, text.rstrip())
        compose_log.see(tk.END)
        compose_log.configure(state=tk.DISABLED)

    def clear_compose_log() -> None:
        compose_log.configure(state=tk.NORMAL)
        compose_log.delete("1.0", tk.END)
        compose_log.configure(state=tk.DISABLED)

    def copy_compose_log() -> None:
        content = compose_log.get("1.0", tk.END).strip()
        if not content:
            safe_messagebox(root, "showinfo", "7_3 mp4Search", "복사할 로그가 없습니다.")
            return
        root.clipboard_clear()
        root.clipboard_append(content)
        status_var.set("합성 로그를 클립보드에 복사했습니다.")

    ttk.Button(log_btn_fr, text="로그 복사", command=copy_compose_log).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(log_btn_fr, text="로그 지우기", command=clear_compose_log).pack(side=tk.LEFT)

    def current_iid() -> str | None:
        sel = tree.selection()
        return sel[0] if sel else None

    def current_row() -> CueRow | None:
        iid = current_iid()
        return rows.get(iid) if iid else None

    def apply_keyword_from_entry() -> None:
        row = current_row()
        iid = current_iid()
        if not row or not iid:
            return
        row.query = keyword_var.get().strip()
        refresh_tree_values(iid)

    def sync_keyword_to_entry(row: CueRow | None) -> None:
        keyword_var.set(row.query if row else "")

    keyword_ent.bind("<FocusOut>", lambda _e: apply_keyword_from_entry())

    def row_asset_sec(row: CueRow) -> int:
        return timeline_asset_number(row.timeline_start_sec)

    def _timeline_segments() -> list[tuple[float, float]]:
        return [
            (row.timeline_start_sec, row.cue_duration_sec)
            for row in sorted(rows.values(), key=lambda r: r.timeline_start_sec)
        ]

    def _asset_start_times() -> dict[int, float]:
        """``SRT_NNN`` 파일 번호 → SRT 실제 시작(초). SRT 파일 기준, 행과 병합."""
        from mp4_search.timeline_compose import build_asset_start_times_from_srt

        starts: dict[int, float] = {}
        srt = Path(srt_var.get().strip())
        if srt.is_file():
            starts.update(build_asset_start_times_from_srt(srt))
        for row in rows.values():
            key = row_asset_sec(row)
            t = float(row.timeline_start_sec)
            if key not in starts or t < starts[key]:
                starts[key] = t
        return starts

    def _row_asset_maps() -> tuple[dict[int, Path], dict[int, Path]]:
        """행 자산 — ``SRT_NNN`` **파일명 번호** 기준 (SRT 줄 번호·행 키 사용 안 함)."""
        mp4: dict[int, Path] = {}
        png: dict[int, Path] = {}
        for row in rows.values():
            if row.mp4_path and row.mp4_path.is_file():
                n = parse_srt_asset_number(row.mp4_path.name)
                if n is not None:
                    mp4[n] = row.mp4_path
            if row.png_path and row.png_path.is_file():
                n = parse_srt_asset_number(row.png_path.name)
                if n is not None:
                    png[n] = row.png_path
        return mp4, png

    def _expected_mp4_slots() -> set[int]:
        """다운로드파일 열에 지정했으나 MP4가 아직 없는 자산 번호."""
        slots: set[int] = set()
        for row in rows.values():
            if not _download_mp4_display(row):
                continue
            if row.mp4_path and row.mp4_path.is_file():
                continue
            slots.add(row_asset_sec(row))
        return slots

    def _row_png_effects() -> dict[int, str]:
        fx: dict[int, str] = {}
        for row in rows.values():
            if row.png_path and row.png_path.is_file():
                n = parse_srt_asset_number(row.png_path.name)
                if n is not None:
                    fx[n] = normalize_png_effect(row.png_effect)
        return fx

    def section_label(row: CueRow) -> str:
        if row.cue_ids and len(row.cue_ids) > 1:
            return f"{row.cue_ids[0]}-{row.cue_ids[-1]}"
        return str(row.srt_id)

    def _provider_display(name: str) -> str:
        return _PROVIDER_LABELS.get((name or "").lower(), (name or "").title())

    def _open_stock_page(url: str) -> None:
        u = (url or "").strip()
        if not u:
            return
        import webbrowser

        try:
            webbrowser.open(u)
        except OSError as e:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", f"브라우저를 열 수 없습니다.\n{e}")

    def _bind_stock_site_label(lbl: ttk.Label, provider: str, page_url: str) -> None:
        lbl.configure(text=_provider_display(provider), foreground="#1565c0", cursor="hand2")
        if page_url.strip():
            lbl.bind(
                "<Button-1>",
                lambda _e, u=page_url.strip(): _open_stock_page(u),
            )

    def _fit_cue_column_width() -> None:
        """SRT 내용 열 — 가장 긴 대본보다 약간 넓게 (과도하게 크지 않게)."""
        if not rows:
            return
        longest = max(len((r.cue_text or "").replace("\n", " ")) for r in rows.values())
        # 한글·영문 혼합 대략 7px/자, 여백 +20, 상한 220
        w = min(220, max(88, longest * 7 + 20))
        try:
            tree.column(_COL_CUE, width=w)
        except tk.TclError:
            pass

    def _find_iid_by_mp4_path(path: Path) -> str | None:
        try:
            target = path.resolve()
        except OSError:
            return None
        for iid, row in rows.items():
            if row.mp4_path:
                try:
                    if row.mp4_path.resolve() == target:
                        return iid
                except OSError:
                    continue
        return None

    def _clear_download_cell(row: CueRow, iid: str) -> None:
        key = _download_mp4_key(row)
        if key in download_mp4_inputs:
            download_mp4_inputs.pop(key, None)
            try:
                save_download_mp4_inputs(download_mp4_inputs)
            except OSError:
                pass
        refresh_tree_values(iid)

    def _download_mp4_key(row: CueRow) -> str:
        return str(row.srt_id)

    def _download_mp4_display(row: CueRow) -> str:
        return download_mp4_inputs.get(_download_mp4_key(row), "")

    def _copy_download_asset_to_row(row: CueRow, source_name: str) -> tuple[str | None, Path | None]:
        """다운로드 폴더 파일 → MP4 폴더 ``SRT_NNN.mp4`` / ``SRT_NNN.png``."""
        dl = Path(download_var.get().strip())
        if not dl.is_dir():
            return f"다운로드 폴더가 없습니다: {dl}", None
        src = find_download_asset(dl, source_name)
        if src is None:
            return f"다운로드 폴더에 파일이 없습니다: {source_name}", None
        out_dir = mp4_dir()
        try:
            if _is_video_file(src):
                dest = out_dir / srt_mp4_name(row_asset_sec(row))
                copy_local_video(src, dest)
                row.mp4_path = dest
                row.preview_path = dest
                row.selected = None
                return None, dest
            if _is_image_file(src):
                dest = out_dir / srt_png_name(row_asset_sec(row))
                copy_local_image_as_png(src, dest)
                row.png_path = dest
                return None, dest
            return f"지원하지 않는 파일 형식입니다: {src.name}", None
        except OSError as e:
            return str(e), None

    def _is_video_file(path: Path) -> bool:
        return path.suffix.lower() in _VIDEO_DROP_EXTS

    def _is_image_file(path: Path) -> bool:
        return path.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp")

    def _assign_video_file_to_row(
        iid: str,
        src: Path,
        *,
        move_from_iid: str | None = None,
    ) -> str | None:
        row = rows.get(iid)
        if not row:
            return "선택된 행이 없습니다."
        src = Path(src)
        if not src.is_file():
            return f"파일이 없습니다: {src}"
        if src.suffix.lower() not in _VIDEO_DROP_EXTS:
            return "동영상 파일(mp4, mov …)만 드롭할 수 있습니다."
        dest = mp4_dir() / srt_mp4_name(row_asset_sec(row))
        delete_after: list[Path] = []

        def _mark_delete(p: Path | None) -> None:
            if not p or not p.is_file():
                return
            try:
                pr = p.resolve()
            except OSError:
                return
            for existing in delete_after:
                try:
                    if existing.resolve() == pr:
                        return
                except OSError:
                    continue
            delete_after.append(p)

        try:
            src_res = src.resolve()
            dest_res = dest.resolve()
        except OSError as e:
            return str(e)

        if move_from_iid and move_from_iid in rows and move_from_iid != iid:
            src_row = rows[move_from_iid]
            if src_row.mp4_path:
                try:
                    if src_row.mp4_path.resolve() != dest_res:
                        _mark_delete(src_row.mp4_path)
                except OSError:
                    pass

        if row.mp4_path and row.mp4_path.is_file():
            try:
                old = row.mp4_path.resolve()
                if old != dest_res and old != src_res:
                    _mark_delete(row.mp4_path)
            except OSError:
                pass

        try:
            if src_res != dest_res:
                copy_local_video(src, dest)
        except OSError as e:
            return str(e)

        if move_from_iid and move_from_iid in rows and move_from_iid != iid:
            src_row = rows[move_from_iid]
            src_row.mp4_path = None
            src_row.preview_path = None
            src_row.selected = None
            refresh_tree_values(move_from_iid)

        row.mp4_path = dest
        row.preview_path = dest
        row.selected = None
        refresh_tree_values(iid)

        for old_path in delete_after:
            try:
                if old_path.is_file() and old_path.resolve() != dest_res:
                    old_path.unlink()
            except OSError:
                pass
        return None

    def refresh_tree_values(iid: str, *, status_override: str | None = None) -> None:
        row = rows.get(iid)
        if not row:
            return
        has_mp4 = bool(row.mp4_path and row.mp4_path.is_file())
        has_png = bool(row.png_path and row.png_path.is_file())
        mp4_name = row.mp4_path.name if has_mp4 else ""
        png_name = row.png_path.name if has_png else ""
        if status_override:
            status = status_override
        elif has_mp4 and has_png:
            status = "MP4+PNG"
        elif has_mp4:
            status = "MP4"
        elif has_png:
            status = "PNG"
        elif _download_mp4_display(row):
            status = "지정됨"
        else:
            status = "미적용"
        cue_full = row.cue_text.replace("\n", " ")
        range_label = section_label(row)
        dl_disp = _download_mp4_display(row)[:80]
        tree.item(
            iid,
            values=(
                range_label,
                row.time_start,
                row.time_end,
                cue_full,
                row.query,
                dl_disp,
                mp4_name,
                png_name,
                png_effect_label(row.png_effect),
                status,
            ),
        )

    def _row_compose_log_lines() -> list[str]:
        lines: list[str] = []
        for row in sorted(rows.values(), key=lambda r: r.timeline_start_sec):
            asset = row_asset_sec(row)
            mp4 = row.mp4_path.name if row.mp4_path and row.mp4_path.is_file() else "-"
            fn_num = parse_srt_asset_number(row.mp4_path.name) if row.mp4_path else None
            extra = f" 파일#{fn_num}" if fn_num is not None and fn_num != asset else ""
            lines.append(
                f"SRT#{row.srt_id} 시작={row.timeline_start_sec:g}s 자산={asset:03d}{extra} MP4={mp4}"
            )
        return lines

    def _clear_compose_column() -> None:
        for iid, row in rows.items():
            row.compose_status = ""
            refresh_tree_values(iid)

    def _apply_compose_statuses(statuses: dict[int, str]) -> None:
        asset_starts = _asset_start_times()
        for iid, row in rows.items():
            key = row_asset_sec(row)
            canonical = asset_starts.get(key)
            owns = canonical is not None and abs(row.timeline_start_sec - canonical) < 0.001
            if owns or (row.mp4_path and row.mp4_path.is_file()):
                if row.mp4_path:
                    n = parse_srt_asset_number(row.mp4_path.name)
                    if n is not None:
                        key = n
                row.compose_status = statuses.get(key, "")
            else:
                row.compose_status = ""
            refresh_tree_values(iid)

    def _parse_apply_asset_sec() -> int | None:
        """적용 대상 타임라인 시작(초) — ``SRT_NNN`` 파일 번호."""
        raw = apply_srt_var.get().strip()
        row = current_row()
        if not raw:
            return row_asset_sec(row) if row else None
        try:
            n = int(raw)
        except ValueError:
            return None
        if n < 0:
            return None
        for r in rows.values():
            if row_asset_sec(r) == n:
                return n
        for r in rows.values():
            if r.srt_id == n:
                return row_asset_sec(r)
        return n

    def _update_row_mp4_by_asset(asset_sec: int, dest: Path) -> None:
        for iid, r in rows.items():
            if row_asset_sec(r) == asset_sec:
                r.mp4_path = dest
                r.preview_path = dest
                refresh_tree_values(iid)
                return
        row = current_row()
        if row:
            iid = current_iid()
            row.mp4_path = dest
            row.preview_path = dest
            if iid:
                refresh_tree_values(iid)

    def _clip_range_from_ui() -> tuple[float, float | None]:
        row = current_row()
        if row:
            _save_clip_from_ui(row)
            start = row.clip_start_sec
            end = row.clip_end_sec if row.clip_end_sec > row.clip_start_sec else None
            return start, end
        try:
            start = max(0.0, float(clip_start_var.get().strip() or "0"))
        except ValueError:
            start = 0.0
        end_s = clip_end_var.get().strip()
        if not end_s:
            return start, None
        try:
            end = max(0.0, float(end_s))
            return start, end if end > start else None
        except ValueError:
            return start, None

    def _save_clip_from_ui(row: CueRow) -> None:
        try:
            row.clip_start_sec = max(0.0, float(clip_start_var.get().strip() or "0"))
        except ValueError:
            row.clip_start_sec = 0.0
        end_s = clip_end_var.get().strip()
        if end_s:
            try:
                row.clip_end_sec = max(0.0, float(end_s))
            except ValueError:
                row.clip_end_sec = 0.0
        else:
            row.clip_end_sec = 0.0

    def _resolve_clip_end(asset_sec: int, start_sec: float, end_sec: float | None) -> float | None:
        if end_sec is not None:
            return end_sec
        out_dir = mp4_dir()
        mp4_map, png_map = scan_srt_assets(out_dir)
        extra_mp4, extra_png = _row_asset_maps()
        extra_fx = _row_png_effects()
        mp4_map.update(extra_mp4)
        png_map.update(extra_png)
        asset_times = _asset_start_times()
        segments = _timeline_segments()
        cue_ends = [row.timeline_end_sec for row in rows.values() if row.timeline_end_sec > 0]
        total_end = timeline_total_sec(segments, cue_end_times=cue_ends) if segments else None
        dur = clip_duration_until_next_asset(
            asset_sec,
            mp4_map,
            png_map,
            total_end=total_end,
            asset_start_times=asset_times,
        )
        if dur is None:
            return None
        return start_sec + dur

    def _sync_clip_to_ui(row: CueRow) -> None:
        apply_srt_var.set(str(row_asset_sec(row)))
        clip_start_var.set(str(int(row.clip_start_sec)) if row.clip_start_sec == int(row.clip_start_sec) else f"{row.clip_start_sec:g}")
        if row.clip_end_sec > row.clip_start_sec:
            clip_end_var.set(str(int(row.clip_end_sec)) if row.clip_end_sec == int(row.clip_end_sec) else f"{row.clip_end_sec:g}")
        else:
            clip_end_var.set("")

    clip_start_ent.bind("<FocusOut>", on_clip_focus_out)
    clip_end_ent.bind("<FocusOut>", on_clip_focus_out)

    def load_table() -> None:
        suggest_mp3_from_srt()
        srt = Path(srt_var.get().strip())
        if not srt.is_file():
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "SRT 파일을 선택하세요.")
            return
        try:
            persist()
            out_dir = mp4_dir()
            asset_mp4, asset_png = scan_srt_assets(out_dir)
            tree.delete(*tree.get_children())
            rows.clear()
            cues = parse_srt_cues_timed(srt)
            if not cues:
                safe_messagebox(root, "showwarning", "7_3 mp4Search", "SRT 자막이 없습니다.")
                return
            asset_starts = build_asset_start_times_from_srt(srt)
            mp4_owners = folder_asset_display_owners(asset_mp4, cues, asset_starts)
            png_owners = folder_asset_display_owners(asset_png, cues, asset_starts)
            for srt_id, text, st_ms, en_ms in sorted(cues, key=lambda c: int(c[0])):
                asset_sec = timeline_asset_number(st_ms / 1000.0)
                start_sec = st_ms / 1000.0
                # 같은 파일 번호의 첫 SRT 줄에만 MP4/PNG 표시 (다른 줄에 중복 연결 방지)
                canonical = asset_starts.get(asset_sec)
                owns_asset = canonical is not None and abs(start_sec - canonical) < 0.001
                mp4_path = folder_asset_for_cue_row(
                    srt_id, asset_sec, asset_mp4, mp4_owners, owns_asset=owns_asset
                )
                png_path = folder_asset_for_cue_row(
                    srt_id, asset_sec, asset_png, png_owners, owns_asset=owns_asset
                )
                cue_one = (text or "").strip().replace("\n", " ")
                dur = max(0.0, (en_ms - st_ms) / 1000.0)
                iid = tree.insert("", tk.END, values=(srt_id, "", "", cue_one, "", "", "", "", "고정", ""))
                rows[iid] = CueRow(
                    srt_id=srt_id,
                    cue_text=cue_one,
                    time_start=format_ms_short(st_ms),
                    time_end=format_ms_short(en_ms),
                    cue_duration_sec=dur,
                    timeline_start_sec=max(0.0, st_ms / 1000.0),
                    timeline_end_sec=max(0.0, en_ms / 1000.0),
                    clip_start_sec=0.0,
                    clip_end_sec=0.0,
                    cue_ids=[srt_id],
                    mp4_path=mp4_path,
                    png_path=png_path,
                    preview_path=mp4_path if mp4_path and mp4_path.is_file() else None,
                )
                refresh_tree_values(iid)
            n_mp4 = sum(1 for r in rows.values() if r.mp4_path and r.mp4_path.is_file())
            n_png = sum(1 for r in rows.values() if r.png_path and r.png_path.is_file())
            extra = f" · 폴더 MP4 {n_mp4} · PNG {n_png}" if (n_mp4 or n_png) else ""
            status_var.set(f"자막 {len(cues)}줄{extra} — {out_dir.name}")
            _fit_cue_column_width()
            clear_results_panel()
        except OSError as e:
            safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))
        except Exception as e:
            traceback.print_exc()
            safe_messagebox(root, "showerror", "7_3 mp4Search", f"목록 조회 실패:\n{e}")

    def clear_results_panel() -> None:
        nonlocal thumb_refs
        thumb_refs = []
        for w in results_inner.winfo_children():
            w.destroy()
        for w in images_inner.winfo_children():
            w.destroy()
        preview_lbl.configure(image="", text="(영상을 선택하세요)")
        query_var.set("")

    def show_results_for_row(row: CueRow) -> None:
        for w in results_inner.winfo_children():
            w.destroy()
        n_vid = len(row.results)
        n_img = len(row.image_results)
        if row.query:
            query_var.set(f"검색: {row.query} · 영상 {n_vid} · 이미지 {n_img}")
        elif n_vid or n_img:
            query_var.set(f"영상 {n_vid} · 이미지 {n_img}")
        if not row.results:
            show_images_for_row(row)
            return
        col = 0
        row_idx = 0
        for video in row.results:

            def bind_preview(widget: tk.Widget, v: StockVideo = video) -> None:
                widget.bind("<Button-1>", lambda _e, vid=v: select_video(vid, autoplay=True))
                try:
                    widget.configure(cursor="hand2")
                except tk.TclError:
                    pass

            fr = ttk.Frame(results_inner, padding=4)
            fr.grid(row=row_idx, column=col, padx=4, pady=4, sticky="n")
            img_lbl = ttk.Label(fr, text="…", width=18)
            img_lbl.pack()
            cap = video.title[:24] + ("…" if len(video.title) > 24 else "")
            cap_lbl = ttk.Label(fr, text=cap, wraplength=_THUMB_W)
            cap_lbl.pack()
            prov_lbl = ttk.Label(fr, text="")
            prov_lbl.pack(pady=(2, 0))
            _bind_stock_site_label(prov_lbl, video.provider, video.page_url)
            ttk.Button(fr, text="선택", command=lambda v=video: apply_video(v)).pack(pady=(2, 0))
            for w in (fr, img_lbl, cap_lbl):
                bind_preview(w)
            load_thumb_async(video, img_lbl)
            col += 1
            if col >= 2:
                col = 0
                row_idx += 1
        show_images_for_row(row)

    def show_images_for_row(row: CueRow) -> None:
        for w in images_inner.winfo_children():
            w.destroy()
        if not row.image_results:
            return
        col = 0
        row_idx = 0
        for image in row.image_results:

            def bind_img_preview(widget: tk.Widget, img: StockImage = image) -> None:
                widget.bind("<Button-1>", lambda _e, im=img: preview_image(im))
                widget.bind("<Double-Button-1>", lambda _e, im=img: show_image_large(im))
                try:
                    widget.configure(cursor="hand2")
                except tk.TclError:
                    pass

            fr = ttk.Frame(images_inner, padding=4)
            fr.grid(row=row_idx, column=col, padx=4, pady=4, sticky="n")
            img_lbl = ttk.Label(fr, text="…", width=14)
            img_lbl.pack()
            cap = image.title[:20] + ("…" if len(image.title) > 20 else "")
            ttk.Label(fr, text=cap, wraplength=120).pack()
            img_prov = ttk.Label(fr, text="")
            img_prov.pack(pady=(2, 0))
            _bind_stock_site_label(img_prov, image.provider, image.page_url)
            ttk.Button(fr, text="선택", command=lambda im=image: apply_image(im)).pack(pady=(2, 0))
            for w in (fr, img_lbl):
                bind_img_preview(w)
            load_image_thumb_async(image, img_lbl)
            col += 1
            if col >= 3:
                col = 0
                row_idx += 1

    def load_image_thumb_async(image: StockImage, lbl: ttk.Label) -> None:
        def work() -> None:
            path = temp_preview_path(".jpg", tag=f"img_{image_cache_key(image).replace(':', '_')}")
            ok = download_thumbnail(image.thumbnail_url, path)

            def ui() -> None:
                if not ok or not path.is_file():
                    lbl.configure(text="(없음)")
                    return
                try:
                    from PIL import Image, ImageTk

                    im = Image.open(path).convert("RGB")
                    im.thumbnail((120, 90))
                    photo = ImageTk.PhotoImage(im)
                    thumb_refs.append(photo)
                    lbl.configure(image=photo, text="")
                except Exception:
                    lbl.configure(text="(썸네일)")

            safe_after(root, ui)

        threading.Thread(target=work, daemon=True).start()

    def _open_image_viewer(path: Path, *, title: str = "") -> None:
        try:
            from PIL import Image, ImageTk

            im = Image.open(path).convert("RGB")
            max_w, max_h = 960, 720
            im.thumbnail((max_w, max_h))
            photo = ImageTk.PhotoImage(im)
            thumb_refs.append(photo)
        except Exception as e:
            safe_messagebox(root, "showerror", "7_3 mp4Search", f"이미지를 열 수 없습니다.\n{e}")
            return
        win = tk.Toplevel(root)
        win.title(title or path.name)
        try:
            win.transient(root)
        except tk.TclError:
            pass
        lbl = ttk.Label(win, image=photo)
        lbl.image = photo
        lbl.pack(padx=10, pady=10)
        ttk.Label(win, text=path.name, foreground="#666").pack(pady=(0, 8))

    def show_image_large(image: StockImage) -> None:
        row = current_row()
        if row:
            row.selected_image = image
        vkey = image_cache_key(image)
        status_var.set(f"이미지 불러오는 중… {image.title[:40]}")

        def work() -> None:
            target = image
            try:
                if row:
                    cached = row.image_preview_paths.get(vkey)
                    if cached and cached.is_file():
                        path = cached
                    else:
                        path = temp_preview_path(".jpg", tag=f"full_{vkey.replace(':', '_')}")
                        download_url(target.download_url, path)
                        row.image_preview_paths[vkey] = path
                else:
                    path = temp_preview_path(".jpg", tag=f"full_{vkey.replace(':', '_')}")
                    download_url(target.download_url, path)

                def ui() -> None:
                    _open_image_viewer(path, title=f"{target.provider} · {target.title[:50]}")
                    status_var.set(f"이미지 보기: {target.title[:50]}")

                safe_after(root, ui)
            except Exception as e:

                def fail() -> None:
                    safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def preview_image(image: StockImage) -> None:
        row = current_row()
        if row:
            row.selected_image = image
        preview_lbl.configure(image="", text=f"이미지 · {image.provider} · {image.title[:40]} (더블클릭=크게)")
        status_var.set(f"이미지: {image.title[:50]} — [선택] PNG 저장 · 더블클릭=크게")

    def apply_image(image: StockImage) -> None:
        row = current_row()
        if not row or busy["v"]:
            return
        row.selected_image = image
        dest = mp4_dir() / srt_png_name(row_asset_sec(row))
        set_busy(True)
        status_var.set(f"이미지 저장 중… {dest.name}")

        def work() -> None:
            try:
                download_url(image.download_url, dest.with_suffix(".dl"))
                tmp = dest.with_suffix(".dl")
                copy_local_image_as_png(tmp, dest)
                try:
                    tmp.unlink(missing_ok=True)
                except OSError:
                    pass
                row.png_path = dest

                def ui() -> None:
                    iid = current_iid()
                    if iid:
                        refresh_tree_values(iid)
                    status_var.set(f"이미지 저장 — {dest}")
                    safe_messagebox(root, "showinfo", "7_3 mp4Search", f"이미지 저장:\n{dest}")
                    set_busy(False)
                safe_after(root, ui)
            except Exception as e:
                def fail() -> None:
                    set_busy(False)
                    safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))
                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def apply_video(video: StockVideo) -> None:
        if busy["v"] or search_busy["v"]:
            return
        asset_sec = _parse_apply_asset_sec()
        if asset_sec is None:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "시작(초)에 적용할 타임라인 초(예: 26)를 입력하세요.")
            return
        row = current_row()
        if row:
            row.selected = video
        _apply_stock_video_to_asset(asset_sec, video)

    def _apply_stock_video_to_asset(asset_sec: int, video: StockVideo) -> None:
        start_sec, end_sec = _clip_range_from_ui()
        end_sec = _resolve_clip_end(asset_sec, start_sec, end_sec)
        dest = mp4_dir() / srt_mp4_name(asset_sec)
        set_busy(True)
        status_var.set(f"저장 중… {dest.name}")

        def work() -> None:
            try:
                row = current_row()
                vkey = video_cache_key(video)
                if row and row.preview_path and row.preview_path.is_file() and row.selected == video:
                    src = row.preview_path
                elif row and row.preview_paths.get(vkey) and row.preview_paths[vkey].is_file():
                    src = row.preview_paths[vkey]
                else:
                    src = temp_preview_path(".mp4", tag=f"apply_{vkey.replace(':', '_')}")
                    download_url(video.download_url, src)
                trim_video(src, dest, start_sec=start_sec, end_sec=end_sec)
                _update_row_mp4_by_asset(asset_sec, dest)

                def ui() -> None:
                    seg = f"{start_sec:g}s"
                    if end_sec is not None:
                        seg += f"~{end_sec:g}s"
                    else:
                        seg += "~끝"
                    status_var.set(f"저장 완료 ({seg}) — {dest.name}")
                    safe_messagebox(root, "showinfo", "7_3 mp4Search", f"저장했습니다.\n\n{dest}\n구간: {seg}")
                    set_busy(False)

                safe_after(root, ui)
            except Exception as e:

                def fail() -> None:
                    set_busy(False)
                    safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def pick_local_video_apply() -> None:
        if busy["v"] or compose_busy["v"]:
            return
        asset_sec = _parse_apply_asset_sec()
        if asset_sec is None:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "시작(초)에 적용할 타임라인 초(예: 26)를 입력하세요.")
            return
        init = Path(download_var.get().strip()) if download_var.get().strip() else Path.home() / "Downloads"
        picked = filedialog.askopenfilename(
            title="동영상 선택",
            initialdir=folder_dialog_initial(init),
            filetypes=[
                ("동영상", "*.mp4 *.mov *.webm *.mkv *.m4v *.avi"),
                ("모든 파일", "*.*"),
            ],
        )
        if not picked:
            return
        src = Path(picked)
        if src.suffix.lower() not in _VIDEO_DROP_EXTS:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "동영상 파일(mp4, mov …)만 선택할 수 있습니다.")
            return
        start_sec, end_sec = _clip_range_from_ui()
        end_sec = _resolve_clip_end(asset_sec, start_sec, end_sec)
        dest = mp4_dir() / srt_mp4_name(asset_sec)
        set_busy(True)
        status_var.set(f"저장 중… {dest.name}")

        def work() -> None:
            try:
                trim_video(src, dest, start_sec=start_sec, end_sec=end_sec)
                _update_row_mp4_by_asset(asset_sec, dest)

                def ui() -> None:
                    seg = f"{start_sec:g}s"
                    if end_sec is not None:
                        seg += f"~{end_sec:g}s"
                    else:
                        seg += "~끝"
                    status_var.set(f"저장 완료 ({seg}) — {dest.name}")
                    safe_messagebox(root, "showinfo", "7_3 mp4Search", f"저장했습니다.\n\n{dest}\n구간: {seg}")
                    set_busy(False)

                safe_after(root, ui)
            except Exception as e:

                def fail() -> None:
                    set_busy(False)
                    safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    btn_pick_video.configure(command=pick_local_video_apply)

    def load_thumb_async(video: StockVideo, lbl: ttk.Label) -> None:
        def work() -> None:
            path = temp_preview_path(".jpg", tag=f"thumb_{video_cache_key(video).replace(':', '_')}")
            ok = download_thumbnail(video.thumbnail_url, path)

            def ui() -> None:
                if not ok or not path.is_file():
                    lbl.configure(text="(썸네일 없음)")
                    return
                try:
                    from PIL import Image, ImageTk

                    im = Image.open(path).convert("RGB")
                    im.thumbnail((_THUMB_W, 100))
                    photo = ImageTk.PhotoImage(im)
                    thumb_refs.append(photo)
                    lbl.configure(image=photo, text="")
                except Exception:
                    lbl.configure(text="(썸네일)")

            safe_after(root, ui)

        threading.Thread(target=work, daemon=True).start()

    def select_video(video: StockVideo, *, autoplay: bool = False) -> None:
        row = current_row()
        if not row or search_busy["v"]:
            return
        row.selected = video
        vkey = video_cache_key(video)
        status_var.set(f"다운로드 중… {video.title[:36]}")

        def work() -> None:
            target = video
            try:
                cached = row.preview_paths.get(vkey)
                if cached and cached.is_file():
                    path = cached
                else:
                    path = temp_preview_path(".mp4", tag=vkey.replace(":", "_"))
                    download_url(target.download_url, path)
                    row.preview_paths[vkey] = path
                row.preview_path = path

                def ui() -> None:
                    if row.selected is not target:
                        return
                    preview_lbl.configure(image="", text=f"{target.provider} · {target.title[:40]}")
                    if autoplay:
                        try:
                            play_video(path)
                            status_var.set(f"재생: {target.title[:50]} — ③ 적용 또는 [선택]")
                        except OSError as e:
                            safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))
                    else:
                        status_var.set(f"선택: {target.title[:50]} — ▶ 재생 또는 ③ 적용")

                safe_after(root, ui)
            except Exception as e:

                def fail() -> None:
                    if row.selected is target:
                        safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def show_local_assets_for_row(row: CueRow) -> None:
        mp4 = row.mp4_path if row.mp4_path and row.mp4_path.is_file() else None
        png = row.png_path if row.png_path and row.png_path.is_file() else None
        if not mp4 and not png:
            return
        parts: list[str] = []
        if mp4:
            parts.append(f"MP4: {mp4.name}")
        if png:
            parts.append(f"PNG: {png.name}")
        preview_lbl.configure(image="", text="\n".join(parts))
        query_var.set(f"MP4 폴더 — {' · '.join(parts)}")
        if png:
            for w in images_inner.winfo_children():
                w.destroy()
            fr = ttk.Frame(images_inner, padding=4)
            fr.grid(row=0, column=0, padx=4, pady=4, sticky="n")
            img_lbl = ttk.Label(fr, text="…")
            img_lbl.pack()
            ttk.Label(fr, text=png.name, wraplength=140).pack(pady=(2, 0))

            def bind_local_png(widget: tk.Widget, p: Path = png) -> None:
                widget.bind("<Double-Button-1>", lambda _e, path=p: _open_image_viewer(path, title=path.name))
                try:
                    widget.configure(cursor="hand2")
                except tk.TclError:
                    pass

            for w in (fr, img_lbl):
                bind_local_png(w)
            try:
                from PIL import Image, ImageTk

                im = Image.open(png).convert("RGB")
                im.thumbnail((200, 150))
                photo = ImageTk.PhotoImage(im)
                thumb_refs.append(photo)
                img_lbl.configure(image=photo, text="")
            except Exception:
                img_lbl.configure(text=png.name)

    def on_tree_select(_evt=None) -> None:
        sel = tree.selection()
        sel_iid = sel[0] if sel else None
        if _cell_editor is not None and _edit_iid and sel_iid != _edit_iid:
            _close_cell_editor(save=True)
        row = current_row()
        if not row:
            clear_results_panel()
            sync_keyword_to_entry(None)
            return
        sec = section_label(row)
        sync_keyword_to_entry(row)
        _sync_clip_to_ui(row)
        if row.results or row.image_results:
            show_results_for_row(row)
        else:
            clear_results_panel()
            if row.mp4_path and row.mp4_path.is_file() or row.png_path and row.png_path.is_file():
                show_local_assets_for_row(row)
            else:
                preview_lbl.configure(text="「② 영상검색」을 누르면\n선택 자막의 영상을 조회합니다.")
            if row.query:
                query_var.set(f"SRT {sec} · 키워드: {row.query}")
            elif not ((row.mp4_path and row.mp4_path.is_file()) or (row.png_path and row.png_path.is_file())):
                query_var.set(f"SRT {sec} — 영상검색 대기")
            if row.cue_text.strip() and not row.query and not keyword_var.get().strip():
                suggest_iid = current_iid()

                def suggest_work() -> None:
                    try:
                        q = search_query_from_cue(row.cue_text)
                    except Exception:
                        return

                    def suggest_ui() -> None:
                        if current_iid() != suggest_iid or row.query or keyword_var.get().strip():
                            return
                        keyword_var.set(q)
                        row.query = q
                        refresh_tree_values(suggest_iid)

                    safe_after(root, suggest_ui)

                threading.Thread(target=suggest_work, daemon=True).start()

    _cell_editor: tk.Widget | None = None
    _edit_iid: str | None = None
    _edit_col: str | None = None

    def _save_download_draft(row: CueRow, val: str, iid: str) -> None:
        key = _download_mp4_key(row)
        if val:
            download_mp4_inputs[key] = val
        else:
            download_mp4_inputs.pop(key, None)
        try:
            save_download_mp4_inputs(download_mp4_inputs)
        except OSError:
            pass
        refresh_tree_values(iid)

    def _commit_download_cell(row: CueRow, val: str, iid: str) -> None:
        _save_download_draft(row, val, iid)
        if not val:
            return
        err, saved = _copy_download_asset_to_row(row, val)
        if err:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", err)
            refresh_tree_values(iid)
            return
        _clear_download_cell(row, iid)
        if saved:
            status_var.set(f"다운로드 저장 — {saved.name}")

    def _close_cell_editor(*, save: bool = True) -> None:
        nonlocal _cell_editor, _edit_iid, _edit_col
        if _cell_editor is None:
            return
        col_id = _edit_col
        iid = _edit_iid
        if save and iid and iid in rows and col_id:
            try:
                row = rows[iid]
                val = str(_cell_editor.get()).strip()
                if col_id == _COL_KEYWORD:
                    row.query = val
                    keyword_var.set(row.query)
                    refresh_tree_values(iid)
                elif col_id == _COL_DOWNLOAD:
                    if save:
                        _commit_download_cell(row, val, iid)
                    else:
                        refresh_tree_values(iid)
                elif col_id == _COL_PNG_FX:
                    row.png_effect = normalize_png_effect(
                        PNG_EFFECT_BY_LABEL.get(val, val)
                    )
                    refresh_tree_values(iid)
            except tk.TclError:
                pass
        try:
            _cell_editor.destroy()
        except tk.TclError:
            pass
        _cell_editor = None
        _edit_iid = None
        _edit_col = None

    def _start_cell_edit(iid: str, col_id: str) -> None:
        nonlocal _cell_editor, _edit_iid, _edit_col
        row = rows.get(iid)
        if not row:
            return
        if col_id not in (_COL_KEYWORD, _COL_DOWNLOAD, _COL_PNG_FX):
            return
        if _cell_editor is not None and _edit_iid == iid and _edit_col == col_id:
            try:
                _cell_editor.focus_set()
            except tk.TclError:
                pass
            return
        bbox = tree.bbox(iid, column=col_id)
        if not bbox:
            return
        x, y, w, h = bbox
        if w <= 6 or h <= 6:
            return
        _close_cell_editor(save=True)
        _edit_iid = iid
        _edit_col = col_id

        if col_id == _COL_PNG_FX:
            cb = ttk.Combobox(
                tree,
                values=list(PNG_EFFECT_LABELS_LIST),
                state="readonly",
                width=max(6, w // 10),
            )
            _cell_editor = cb
            cb.place(x=x, y=y, width=max(w, 72), height=h)
            cb.set(png_effect_label(row.png_effect))

            def commit() -> None:
                _close_cell_editor(save=True)

            def cancel() -> None:
                _close_cell_editor(save=False)

            cb.focus_set()
            cb.bind("<<ComboboxSelected>>", lambda _e: commit())
            cb.bind("<Escape>", lambda _e: cancel())
            cb.bind("<FocusOut>", lambda _e: commit())
            return

        ent = ttk.Entry(tree)
        _cell_editor = ent
        ent.place(x=x, y=y, width=max(w, 120), height=h)
        if col_id == _COL_KEYWORD:
            cur = row.query or keyword_var.get() or ""
        elif col_id == _COL_DOWNLOAD:
            cur = _download_mp4_display(row)
        else:
            cur = ""
        ent.insert(0, cur)
        ent.select_range(0, tk.END)
        ent.focus_set()

        def commit() -> None:
            _close_cell_editor(save=True)

        def cancel() -> None:
            _close_cell_editor(save=False)

        if col_id == _COL_DOWNLOAD:

            def save_draft() -> None:
                draft = ent.get().strip()
                _save_download_draft(row, draft, iid)
                _close_cell_editor(save=False)

            ent.bind("<Return>", lambda _e: commit())
            ent.bind("<Escape>", lambda _e: cancel())
            ent.bind("<FocusOut>", lambda _e: save_draft())
            return

        ent.bind("<Return>", lambda _e: commit())
        ent.bind("<Escape>", lambda _e: cancel())
        ent.bind("<FocusOut>", lambda _e: commit())

    def _tree_col_id_at_xy(x: int, y: int) -> tuple[str | None, str | None]:
        if tree.identify_region(x, y) != "cell":
            return None, None
        iid = tree.identify_row(y)
        if not iid or iid not in rows:
            return None, None
        try:
            idx = int(tree.identify_column(x).lstrip("#")) - 1
        except ValueError:
            return iid, None
        if idx < 0 or idx >= len(cols):
            return iid, None
        return iid, cols[idx]

    def _tree_col_id_at(event: tk.Event) -> tuple[str | None, str | None]:
        return _tree_col_id_at_xy(event.x, event.y)

    def _tree_col_id_at_pointer() -> tuple[str | None, str | None]:
        try:
            px, py = tree.winfo_pointerxy()
            rx = px - tree.winfo_rootx()
            ry = py - tree.winfo_rooty()
            if rx < 0 or ry < 0 or rx > tree.winfo_width() or ry > tree.winfo_height():
                return None, None
            return _tree_col_id_at_xy(rx, ry)
        except tk.TclError:
            return None, None

    def on_tree_cell_click(event: tk.Event) -> None:
        """편집 가능 셀 — 한 번 클릭으로 입력 (pngFileName 셀 편집과 동일)."""
        iid, col_id = _tree_col_id_at(event)
        if not iid or col_id not in (_COL_KEYWORD, _COL_DOWNLOAD, _COL_PNG_FX):
            return
        tree.selection_set(iid)
        tree.focus(iid)
        root.after(10, lambda r=iid, c=col_id: _start_cell_edit(r, c))

    def on_tree_double_click(event: tk.Event) -> None:
        if tree.identify_region(event.x, event.y) != "cell":
            run_search()
            return
        iid, col_id = _tree_col_id_at(event)
        if not iid:
            return
        if col_id in (_COL_KEYWORD, _COL_DOWNLOAD, _COL_PNG_FX):
            tree.selection_set(iid)
            _start_cell_edit(iid, col_id)
            return
        run_search()

    tree.bind("<<TreeviewSelect>>", on_tree_select)
    tree.bind("<ButtonRelease-1>", on_tree_cell_click, add="+")
    tree.bind("<Double-1>", on_tree_double_click, add="+")

    _mp4_drag_src_iid: str | None = None

    def _resolve_mp4_drop_target() -> str | None:
        """드롭 시점 커서 위치 MP4 셀 → 없으면 선택 행."""
        drop_iid, drop_col = _tree_col_id_at_pointer()
        if drop_iid and drop_col == _COL_MP4:
            return drop_iid
        sel = tree.selection()
        if sel and sel[0] in rows:
            return sel[0]
        return None

    def on_tree_button1(event: tk.Event) -> None:
        nonlocal _mp4_drag_src_iid
        iid, col_id = _tree_col_id_at(event)
        if col_id == _COL_MP4 and iid:
            _mp4_drag_src_iid = iid
        else:
            _mp4_drag_src_iid = None

    def on_tree_mp4_drag_release(event: tk.Event) -> None:
        nonlocal _mp4_drag_src_iid
        src_iid = _mp4_drag_src_iid
        _mp4_drag_src_iid = None
        if not src_iid or src_iid not in rows:
            return
        dst_iid, col_id = _tree_col_id_at(event)
        if col_id != _COL_MP4 or not dst_iid or dst_iid == src_iid:
            return
        src_row = rows[src_iid]
        if not src_row.mp4_path or not src_row.mp4_path.is_file():
            return
        err = _assign_video_file_to_row(dst_iid, src_row.mp4_path, move_from_iid=src_iid)
        if err:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", err)
            return
        dst_row = rows[dst_iid]
        status_var.set(
            f"MP4 이동 — {srt_mp4_name(row_asset_sec(dst_row))} "
            f"← {src_row.mp4_path.name}"
        )

    def on_tree_video_drop(paths: list[str]) -> None:
        _close_cell_editor(save=True)
        iid = _resolve_mp4_drop_target()
        if not iid or iid not in rows:
            safe_messagebox(
                root,
                "showwarning",
                "7_3 mp4Search",
                "MP4 열 위에 동영상 파일을 드롭하세요.\n"
                "(드롭한 행의 SRT_XXX.mp4 파일명으로 저장됩니다.)",
            )
            return
        src: Path | None = None
        for raw in paths:
            p = Path(raw.strip().strip('"'))
            if p.is_file() and p.suffix.lower() in _VIDEO_DROP_EXTS:
                src = p
                break
        if src is None:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "드롭한 동영상 파일을 찾을 수 없습니다.")
            return
        move_from = _find_iid_by_mp4_path(src)
        if move_from == iid:
            move_from = None
        err = _assign_video_file_to_row(iid, src, move_from_iid=move_from)
        if err:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", err)
            return
        row = rows[iid]
        status_var.set(f"MP4 저장 — {srt_mp4_name(row_asset_sec(row))}")

    tree.bind("<Button-1>", on_tree_button1, add="+")
    tree.bind("<ButtonRelease-1>", on_tree_mp4_drag_release, add="+")
    bind_file_drop(tree, on_tree_video_drop)

    def run_search() -> None:
        if search_busy["v"]:
            return
        _close_cell_editor(save=True)
        root.update_idletasks()
        apply_keyword_from_entry()
        iid = current_iid()
        row = current_row()
        if not row or not iid:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "목록에서 SRT 행을 선택한 뒤 「② 영상검색」을 누르세요.")
            return
        manual_query = keyword_var.get().strip() or row.query.strip()
        if not row.cue_text.strip() and not manual_query:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "검색 키워드를 입력하거나 SRT 내용이 있는 행을 선택하세요.")
            return
        sec = section_label(row)
        row.results = []
        row.image_results = []
        row.selected = None
        row.preview_path = None
        row.preview_paths.clear()
        for w in results_inner.winfo_children():
            w.destroy()
        for w in images_inner.winfo_children():
            w.destroy()
        preview_lbl.configure(image="", text="검색 중…")
        query_var.set(f"검색 중… {manual_query}" if manual_query else "검색 중…")
        set_search_busy(True)
        progress_var.set(0)
        progress_text_var.set("영상검색 0%")
        refresh_tree_values(iid, status_override="0%")
        status_var.set(f"SRT {sec} 영상검색 준비…")

        def on_progress(label: str, pct: float) -> None:
            def ui() -> None:
                if current_iid() != iid:
                    return
                pct_i = int(pct)
                progress_var.set(pct)
                progress_text_var.set(f"영상검색 {pct_i}%")
                refresh_tree_values(iid, status_override=f"{pct_i}%")
                kw = manual_query or row.query
                status_var.set(f"SRT {sec} — {label} ({pct_i}%)" + (f" · {kw}" if kw else ""))

            safe_after(root, ui)

        def work() -> None:
            try:
                if manual_query:
                    q = normalize_search_query(manual_query)
                    on_progress("키워드 확인", 18)
                else:
                    on_progress("키워드 번역", 10)
                    q = search_query_from_cue(row.cue_text)
                if not q:
                    raise RuntimeError("검색 키워드를 만들 수 없습니다.\n키워드 입력란에 영어 검색어를 입력하세요.")

                row.query = q

                def show_keyword() -> None:
                    if current_iid() != iid:
                        return
                    keyword_var.set(q)
                    refresh_tree_values(iid, status_override="검색중")

                safe_after(root, show_keyword)

                results: list[StockVideo] = []
                images: list[StockImage] = []
                search_err = ""
                try:
                    _, results = search_stock_videos("", query=q, per_page=12, on_progress=on_progress)
                except RuntimeError as e:
                    search_err = str(e)
                on_progress("이미지 검색", 88)
                try:
                    images = search_stock_images(q, per_page=9)
                except Exception:
                    images = []
                row.results = results
                row.image_results = images
                row.selected = None
                row.preview_path = None
                row.preview_paths.clear()

                def ui() -> None:
                    if current_iid() != iid:
                        set_search_busy(False)
                        progress_var.set(0)
                        progress_text_var.set("")
                        return
                    keyword_var.set(q)
                    refresh_tree_values(iid)
                    show_results_for_row(row)
                    if results or images:
                        status_var.set(f"SRT {sec} — 「{q}」 영상 {len(results)} · 이미지 {len(images)}")
                    else:
                        status_var.set(f"SRT {sec} — 결과 없음 「{q}」")
                        preview_lbl.configure(image="", text="(검색 결과 없음)")
                        msg = search_err or f"SRT {sec} 검색 결과가 없습니다.\n\n키워드: {q}\n\n키워드를 수정한 뒤 다시 검색하세요."
                        safe_messagebox(root, "showinfo", "7_3 mp4Search", msg)
                    progress_var.set(100 if (results or images) else 0)
                    progress_text_var.set("검색 100%" if (results or images) else "")
                    set_search_busy(False)

                safe_after(root, ui)
            except Exception as e:

                def fail() -> None:
                    if current_iid() == iid:
                        row.results = []
                        row.image_results = []
                        refresh_tree_values(iid)
                        preview_lbl.configure(image="", text="(검색 실패)")
                    progress_var.set(0)
                    progress_text_var.set("")
                    set_search_busy(False)
                    safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def run_apply() -> None:
        asset_sec = _parse_apply_asset_sec()
        if asset_sec is None:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "시작(초)에 적용할 타임라인 초(예: 26)를 입력하세요.")
            return
        row = current_row()
        if not row:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "목록에서 행을 선택하세요.")
            return
        video = row.selected
        if not video:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "오른쪽 검색 결과에서 영상을 선택하세요.")
            return
        _apply_stock_video_to_asset(asset_sec, video)

    def _mark_row_composed(asset_sec: int, dest: Path) -> None:
        for iid, row in rows.items():
            if row_asset_sec(row) == asset_sec:
                row.mp4_path = dest
                row.preview_path = dest
                refresh_tree_values(iid, status_override="합성됨")
                return

    def stop_compose() -> None:
        if not compose_busy["v"]:
            return
        compose_cancel.set()
        abort_compose_ffmpeg()
        status_var.set("합성 중지… (완료 구간 저장 중)")

    def _compose_progress_label(pct: float, mark_sec: float | None, idx: int, total: int) -> str:
        pct_i = int(pct)
        if idx == -1:
            return f"합성 {pct_i}% — MP3 음성 — {ALL_MP4_NAME}"
        if mark_sec is None:
            return f"합성 {pct_i}% — 연결 — {ALL_MP4_NAME}"
        return f"합성 {pct_i}% — {mark_sec:g}초 ({idx}/{total}) — {ALL_MP4_NAME}"

    def _sync_row_assets_from_folder(out_dir: Path) -> None:
        srt = Path(srt_var.get().strip())
        cues = parse_srt_cues_timed(srt) if srt.is_file() else []
        asset_mp4, asset_png = scan_srt_assets(out_dir)
        asset_starts = _asset_start_times()
        mp4_owners = folder_asset_display_owners(asset_mp4, cues, asset_starts) if cues else {}
        png_owners = folder_asset_display_owners(asset_png, cues, asset_starts) if cues else {}
        for iid, row in rows.items():
            asset = row_asset_sec(row)
            canonical = asset_starts.get(asset)
            owns_asset = canonical is not None and abs(row.timeline_start_sec - canonical) < 0.001
            if owns_asset:
                mp4 = folder_asset_for_cue_row(
                    row.srt_id, asset, asset_mp4, mp4_owners, owns_asset=True
                )
                if mp4:
                    row.mp4_path = mp4
                    row.preview_path = mp4
                png = folder_asset_for_cue_row(
                    row.srt_id, asset, asset_png, png_owners, owns_asset=True
                )
                if png:
                    row.png_path = png
            elif row.mp4_path and not row.mp4_path.is_file():
                row.mp4_path = None
            elif row.png_path and not row.png_path.is_file():
                row.png_path = None
            refresh_tree_values(iid)

    def run_optimize_images() -> None:
        if busy["v"] or compose_busy["v"]:
            return
        out_dir = mp4_dir()
        set_busy(True)
        status_var.set("이미지 최적화 중… (PNG → JPG · 전체 표시 · 해상도 맞춤)")

        def work() -> None:
            try:
                pairs = optimize_srt_images_in_folder(out_dir)
                lines = [f"  · {src.name} → {dest.name}" for src, dest in pairs[:12]]
                if len(pairs) > 12:
                    lines.append(f"  … 외 {len(pairs) - 12}개")
                detail = "\n".join(lines) if lines else ""

                def ui() -> None:
                    if rows:
                        _sync_row_assets_from_folder(out_dir)
                    n = len(pairs)
                    if n:
                        status_var.set(f"이미지 최적화 완료 — PNG {n}개 → JPG")
                        safe_messagebox(
                            root,
                            "showinfo",
                            "7_3 mp4Search",
                            f"PNG {n}개를 JPG로 변환하고 합성 해상도에 맞췄습니다.\n\n{detail}",
                        )
                    else:
                        status_var.set("최적화할 PNG 없음 (mp4 폴더)")
                        safe_messagebox(
                            root,
                            "showinfo",
                            "7_3 mp4Search",
                            f"MP4 폴더에 SRT_NNN.png 파일이 없습니다.\n\n{out_dir}",
                        )
                    set_busy(False)

                safe_after(root, ui)
            except Exception as e:
                def fail() -> None:
                    set_busy(False)
                    safe_messagebox(root, "showerror", "7_3 mp4Search", f"이미지 최적화 실패:\n{e}")

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def run_compose() -> None:
        if compose_busy["v"]:
            return
        if not rows:
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "먼저 「① 목록 조회」로 SRT 구간을 불러오세요.")
            return
        out_dir = mp4_dir()
        segments = _timeline_segments()
        cue_ends = [row.timeline_end_sec for row in rows.values() if row.timeline_end_sec > 0]
        suggest_mp3_from_srt()
        mp3_path = Path(mp3_var.get().strip()) if mp3_var.get().strip() else None
        if mp3_path and not mp3_path.is_file():
            safe_messagebox(root, "showwarning", "7_3 mp4Search", f"MP3 파일을 찾을 수 없습니다.\n{mp3_path}")
            return
        mp3_dur = _probe_media_duration(mp3_path) if mp3_path else None
        extra_mp4, extra_png = _row_asset_maps()
        extra_fx = _row_png_effects()
        asset_times = _asset_start_times()
        mp4_map, png_map = scan_srt_assets(out_dir)
        mp4_map.update(extra_mp4)
        png_map.update(extra_png)
        mismatched = [
            f"SRT#{r.srt_id} 행 → {r.mp4_path.name} (파일번호 {parse_srt_asset_number(r.mp4_path.name)})"
            for r in rows.values()
            if r.mp4_path
            and r.mp4_path.is_file()
            and (n := parse_srt_asset_number(r.mp4_path.name)) is not None
            and n != row_asset_sec(r)
        ]
        if mismatched:
            try:
                proceed = messagebox.askyesno(
                    "7_3 mp4Search",
                    "목록에 파일명과 시작(초)가 맞지 않는 행이 있습니다.\n"
                    "합성은 **파일명 번호(SRT_NNN)** 기준입니다.\n\n"
                    + "\n".join(mismatched[:6])
                    + ("\n…" if len(mismatched) > 6 else "")
                    + "\n\n그래도 합성할까요?",
                    parent=root,
                )
            except tk.TclError:
                proceed = False
            if not proceed:
                return
        missing = missing_timeline_mp4_slots(
            mp4_map,
            asset_times,
            expected_slots=_expected_mp4_slots(),
        )
        if missing:
            names = ", ".join(f"SRT_{k:03d}.mp4" for k in missing[:8])
            extra_m = f"\n… 외 {len(missing) - 8}개" if len(missing) > 8 else ""
            detail = "\n".join(
                f"  · SRT_{k:03d} → {asset_times.get(k, k):g}초"
                for k in missing[:8]
            )
            try:
                proceed = messagebox.askyesno(
                    "7_3 mp4Search",
                    "다운로드파일을 지정했지만 MP4가 저장되지 않은 구간이 있습니다.\n"
                    f"({names}{extra_m})\n\n"
                    f"{detail}\n\n"
                    "해당 구간은 이전 영상이 다음 MP4까지 이어집니다.\n\n"
                    "그래도 합성할까요?",
                    parent=root,
                )
            except tk.TclError:
                proceed = False
            if not proceed:
                return
        jobs = list_timeline_compose_jobs(
            out_dir,
            segments,
            cue_end_times=cue_ends,
            audio_sec=mp3_dur,
            extra_mp4=extra_mp4,
            extra_png=extra_png,
            png_effects=extra_fx,
            asset_start_times=asset_times,
        )
        if not jobs:
            safe_messagebox(
                root,
                "showwarning",
                "7_3 mp4Search",
                "합성할 구간이 없습니다.\n\n"
                + format_timeline_compose_status(
                    out_dir,
                    segments,
                    cue_end_times=cue_ends,
                    audio_sec=mp3_dur,
                    extra_mp4=extra_mp4,
                    extra_png=extra_png,
                    asset_start_times=asset_times,
                ),
            )
            return
        compose_cancel.clear()
        set_compose_busy(True)
        progress_var.set(0.0)
        progress_text_var.set("합성 0%")
        total = len(jobs)
        dest = out_dir / ALL_MP4_NAME
        work_dir = out_dir / "_compose_work"
        mp3_hint = f" + {mp3_path.name}" if mp3_path else ""
        status_var.set(f"합성 시작… {ALL_MP4_NAME}{mp3_hint} ({total}구간)")
        folder_mp4, folder_png = scan_srt_assets(out_dir)
        _clear_compose_column()
        clear_compose_log()
        append_compose_log(
            format_compose_debug_log(
                mp4_dir=out_dir,
                srt_path=Path(srt_var.get().strip()) if srt_var.get().strip() else None,
                mp3_path=mp3_path,
                mp4_map=mp4_map,
                png_map=png_map,
                folder_mp4=folder_mp4,
                folder_png=folder_png,
                extra_mp4=extra_mp4,
                extra_png=extra_png,
                asset_start_times=asset_times,
                jobs=jobs,
                row_lines=_row_compose_log_lines(),
                phase="시작",
            )
        )

        def work() -> None:
            stopped = False
            result_path: Path | None = None
            compose_jobs = jobs
            last_logged_job = {"v": 0}

            def set_compose_progress(overall: float, label: str) -> None:
                progress_var.set(min(100.0, max(0.0, overall)))
                progress_text_var.set(label)

            def on_overall(pct: float, mark_sec: float | None, idx: int, job_total: int) -> None:
                label = _compose_progress_label(pct, mark_sec, idx, job_total)
                safe_after(root, lambda p=pct, lb=label: set_compose_progress(p, lb))
                if idx > 0 and idx != last_logged_job["v"] and idx <= len(compose_jobs):
                    last_logged_job["v"] = idx
                    j = compose_jobs[idx - 1]
                    end = sum(x.duration_sec for x in compose_jobs[:idx])
                    start = end - j.duration_sec
                    kind = "연장" if j.is_hold else ("빈구간" if j.is_gap else "재생")
                    vid = j.video.name if j.video else "-"
                    safe_after(
                        root,
                        lambda s=start, e=end, k=kind, v=vid, m=j.mark_sec, i=idx: append_compose_log(
                            f"  클립 #{i:02d} {s:g}~{e:g}초 mark={m:g} [{k}] {v}"
                        ),
                    )

            try:
                try:
                    result_path = compose_timeline_to_all_mp4(
                        jobs,
                        dest,
                        work_dir,
                        audio_mp3=mp3_path,
                        cancel_event=compose_cancel,
                        on_progress=on_overall,
                    )
                except ComposeStopped as e:
                    stopped = True
                    result_path = e.path if e.path and e.path.is_file() else None
                    if result_path is None and dest.is_file():
                        result_path = dest
                out_file = result_path or dest
                folder = out_dir
                was_stopped = stopped

                def ui_done() -> None:
                    set_compose_busy(False)
                    compose_statuses = compose_asset_statuses(compose_jobs, mp4_map, asset_times)
                    if was_stopped:
                        if out_file.is_file():
                            set_compose_progress(100.0, f"합성 중지 — {ALL_MP4_NAME}")
                            status_var.set(f"합성 중지 — {ALL_MP4_NAME}")
                            _apply_compose_statuses(compose_statuses)
                            append_compose_log(
                                format_compose_debug_log(
                                    mp4_dir=out_dir,
                                    mp4_map=mp4_map,
                                    png_map=png_map,
                                    asset_start_times=asset_times,
                                    jobs=compose_jobs,
                                    phase="중지",
                                    result_path=out_file,
                                    stopped=True,
                                )
                            )
                            safe_messagebox(
                                root,
                                "showinfo",
                                "7_3 mp4Search",
                                f"합성을 중지했습니다.\n\n저장: {out_file}\n"
                                f"▶ 재생 또는 「조회」로 all.mp4를 확인하세요.\n\n{folder}\n\n"
                                f"하단 「합성 로그」→ 로그 복사 후 제출해 주세요.",
                            )
                        else:
                            progress_var.set(0.0)
                            progress_text_var.set("")
                            safe_messagebox(root, "showwarning", "7_3 mp4Search", "합성이 중지되었습니다.")
                    elif out_file.is_file():
                        set_compose_progress(100.0, "합성 100%")
                        status_var.set(f"합성 완료 — {ALL_MP4_NAME}")
                        _apply_compose_statuses(compose_statuses)
                        summary = format_jobs_timeline_summary(compose_jobs)
                        append_compose_log(
                            format_compose_debug_log(
                                mp4_dir=out_dir,
                                mp4_map=mp4_map,
                                png_map=png_map,
                                asset_start_times=asset_times,
                                jobs=compose_jobs,
                                phase="완료",
                                result_path=out_file,
                            )
                        )
                        missing_rows = [
                            f"SRT_{k:03d} → {compose_statuses[k]}"
                            for k in sorted(compose_statuses)
                            if compose_statuses[k] in ("누락", "미포함", "연장만")
                        ]
                        miss_hint = ""
                        if missing_rows:
                            miss_hint = "\n\n[주의]\n" + "\n".join(missing_rows[:8])
                            if len(missing_rows) > 8:
                                miss_hint += f"\n… 외 {len(missing_rows) - 8}개"
                        safe_messagebox(
                            root,
                            "showinfo",
                            "7_3 mp4Search",
                            f"타임라인 합성 완료\n\n{out_file}\n\n[재생 시각]\n{summary}"
                            f"{miss_hint}\n\n하단 「합성 로그」→ 로그 복사 후 제출해 주세요.",
                        )
                    else:
                        progress_var.set(0.0)
                        progress_text_var.set("")
                        safe_messagebox(root, "showerror", "7_3 mp4Search", "all.mp4 생성에 실패했습니다.")
                    progress_text_var.set("")

                safe_after(root, ui_done)
            except Exception as e:

                def fail() -> None:
                    set_compose_busy(False)
                    progress_var.set(0.0)
                    progress_text_var.set("")
                    safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

                safe_after(root, fail)
            finally:
                def ensure_idle() -> None:
                    if compose_busy["v"]:
                        set_compose_busy(False)

                safe_after(root, ensure_idle)

        threading.Thread(target=work, daemon=True).start()

    def run_play() -> None:
        all_path = mp4_dir() / ALL_MP4_NAME
        path: Path | None = all_path if all_path.is_file() else None
        if path is None:
            row = current_row()
            if row:
                path = row.preview_path if row.preview_path and row.preview_path.is_file() else row.mp4_path
        if not path or not path.is_file():
            safe_messagebox(root, "showwarning", "7_3 mp4Search", "재생할 영상이 없습니다. 검색·적용 후 ▶ 재생 또는 ④ 합성(all.mp4)을 실행하세요.")
            return
        try:
            play_video(path)
            status_var.set(f"재생: {path.name}")
        except OSError as e:
            safe_messagebox(root, "showerror", "7_3 mp4Search", str(e))

    btn_load.configure(command=load_table)
    btn_search.configure(command=run_search)
    btn_apply.configure(command=run_apply)
    btn_optimize_img.configure(command=run_optimize_images)
    btn_compose.configure(command=run_compose)
    btn_compose_stop.configure(command=stop_compose)
    btn_play.configure(command=run_play)
    keyword_ent.bind("<Return>", lambda _e: run_search())

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    if srt_var.get().strip() and Path(srt_var.get().strip()).is_file():
        suggest_mp3_from_srt()
        root.after(300, load_table)

    root.after(200, _apply_pane_sash)

    run_mainloop(root, standalone)


def sys_platform_open_folder(path: Path) -> bool:
    import os
    import subprocess
    import sys

    path = Path(path)
    if not path.is_dir():
        return False
    try:
        if sys.platform == "win32":
            os.startfile(str(path))  # noqa: S606
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
        return True
    except OSError:
        return False
