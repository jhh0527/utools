# -*- coding: utf-8 -*-
"""MP4 구간·영역 자르기 GUI."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from mp4_edit import __version__
from mp4_edit.ffmpeg_util import (
    SPEED_CHOICES,
    crop_and_trim,
    extract_frame_png,
    extract_frame_png_from_url,
    extract_timeline_frame,
    ffmpeg_bin,
    ffprobe_bin,
    loop_segment_in_video,
    normalize_speed,
    probe_duration,
    probe_video_size,
    resolve_edit_dest,
    resolve_loop_plan,
    speed_stem_suffix,
    temp_preview_png,
    temp_timeline_dir,
)
from mp4_edit.loop_auto import DEFAULT_MIN_SCORE, find_loop_points, list_mp4_files
from mp4_edit.log_util import log_file_display, mp4_edit_log, mp4_edit_log_exc
from mp4_edit.paths import default_output_dir
from mp4_edit.settings import load_gui_settings, save_gui_settings
from mp4_edit.youtube_util import (
    download_youtube,
    download_youtube_section,
    fetch_youtube_meta,
    get_youtube_stream_url,
    is_youtube_url,
    normalize_youtube_url,
    youtube_video_id,
)
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

_TIMELINE_THUMB_W = 72
_TIMELINE_THUMB_H = 54
_TIMELINE_THUMB_MAX = 24
_TIMELINE_THUMB_MIN = 4
_FILMOT_URL = "https://filmot.com/"
_YOUGLISH_URL = "https://youglish.com/"
_QUICK_CLIP_SEC = 10.0


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _fmt_time(sec: float) -> str:
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:d}:{s:05.2f}"


def _fmt_time_entry(sec: float) -> str:
    """입력란용 — ``1:10`` / ``2:30`` (초는 정수, 소수면 ``1:10.50``)."""
    sec = max(0.0, float(sec))
    m = int(sec // 60)
    s = sec - m * 60
    if abs(s - round(s)) < 0.05:
        return f"{m}:{int(round(s)):02d}"
    return f"{m}:{s:05.2f}"


def _parse_sec(text: str) -> float | None:
    """초 숫자 또는 ``1:10`` / ``1:10.5`` / ``1:02:30`` 형식."""
    raw = (text or "").strip().replace(",", ".")
    if not raw:
        return None
    if ":" in raw:
        parts = raw.split(":")
        try:
            if len(parts) == 2:
                return max(0.0, float(parts[0]) * 60.0 + float(parts[1]))
            if len(parts) == 3:
                return max(
                    0.0,
                    float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2]),
                )
        except ValueError:
            return None
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        return None


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_close,
        bind_file_drop,
        bind_hub_destroy,
        bind_path_entry_dnd,
        bind_path_row_dnd,
        configure_notebook_tabs,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
    )

    cfg = load_gui_settings()
    mp4_edit_log(f"=== 7_2 mp4Edit {__version__} 시작 log={log_file_display()} ===")
    root, standalone = tk_host(container)
    configure_notebook_tabs(root)
    apply_window_chrome(
        root,
        standalone,
        title=f"7_2 mp4Edit {__version__}",
        minsize=(960, 640),
        geometry="1100x720",
    )
    if standalone and sys.platform == "win32":
        try:
            root.state("zoomed")
        except tk.TclError:
            pass

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    mp4_var = tk.StringVar(value=cfg.get("mp4_path", ""))
    out_dir_var = tk.StringVar(value=cfg.get("output_dir", ""))
    out_name_var = tk.StringVar(value=cfg.get("output_name", ""))
    start_entry_var = tk.StringVar(value=cfg.get("start_sec", "0"))
    end_entry_var = tk.StringVar(value=cfg.get("end_sec", ""))
    status_var = tk.StringVar(value="MP4 파일 또는 YouTube URL 을 지정하세요.")
    start_var = tk.StringVar(value="시작: —")
    end_var = tk.StringVar(value="종료: —")
    crop_var = tk.StringVar(value="영역: 전체")
    preview_time_var = tk.StringVar(value="0:00.00")
    timeline_mode = tk.StringVar(value="start")

    state: dict = {
        "path": None,
        "youtube_url": None,
        "youtube_id": None,
        "stream_url": None,
        "source_text": "",
        "output_dir": default_output_dir(),
        "duration": 0.0,
        "video_w": 0,
        "video_h": 0,
        "start_sec": 0.0,
        "end_sec": None,
        "crop": None,
        "photo": None,
        "display_scale": 1.0,
        "display_off_x": 0.0,
        "display_off_y": 0.0,
        "drag_start": None,
        "rect_id": None,
        "start_line": None,
        "end_line": None,
        "busy": False,
        "loading": False,
        "load_token": 0,
        "preview_job": None,
        "timeline_thumbs": [],
        "timeline_photos": [],
        "timeline_thumb_token": 0,
    }

    if cfg.get("output_dir"):
        state["output_dir"] = Path(cfg["output_dir"])

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(4, weight=1)

    path_fr = ttk.Frame(frm)
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    path_fr.grid_columnconfigure(1, weight=1)
    ttk.Label(path_fr, text="영상", width=8).grid(row=0, column=0, sticky="w")
    mp4_ent = ttk.Entry(path_fr, textvariable=mp4_var)
    mp4_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6))

    btn_load = ttk.Button(path_fr, text="불러오기")
    btn_cancel_load = ttk.Button(path_fr, text="불러오기 취소", state=tk.DISABLED)

    def update_action_buttons() -> None:
        loading = bool(state.get("loading"))
        busy = bool(state.get("busy"))
        locked = loading or busy
        btn_load.configure(state=tk.DISABLED if locked else tk.NORMAL)
        btn_cancel_load.configure(state=tk.NORMAL if loading else tk.DISABLED)
        btn_crop.configure(state=tk.DISABLED if locked else tk.NORMAL)
        btn_crop_10.configure(state=tk.DISABLED if locked else tk.NORMAL)
        btn_loop.configure(state=tk.DISABLED if locked else tk.NORMAL)
        btn_loop_auto.configure(state=tk.DISABLED if locked else tk.NORMAL)
        btn_loop_preview.configure(state=tk.DISABLED if locked else tk.NORMAL)
        btn_loop_batch.configure(state=tk.DISABLED if locked else tk.NORMAL)

    def set_busy(busy: bool) -> None:
        state["busy"] = busy
        update_action_buttons()

    def _load_cancelled(token: int) -> bool:
        return token != state.get("load_token", 0)

    def begin_load() -> int:
        state["load_token"] = state.get("load_token", 0) + 1
        state["loading"] = True
        update_action_buttons()
        return state["load_token"]

    def end_load(token: int) -> bool:
        cancelled = _load_cancelled(token)
        state["loading"] = False
        update_action_buttons()
        return cancelled

    def cancel_load() -> None:
        if not state.get("loading"):
            return
        mp4_edit_log("load cancel requested")
        state["load_token"] = state.get("load_token", 0) + 1
        state["timeline_thumb_token"] = state.get("timeline_thumb_token", 0) + 1
        state["loading"] = False
        clear_timeline_thumbs()
        job = state.get("preview_job")
        if job is not None:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass
            state["preview_job"] = None
        update_action_buttons()
        status_var.set("불러오기 취소됨")

    def pick_mp4() -> None:
        init = Path(mp4_var.get().strip()) if mp4_var.get().strip() else Path.home()
        parent = init.parent if init.is_file() else (init if init.is_dir() else Path.home())
        p = filedialog.askopenfilename(
            title="MP4 선택",
            initialdir=folder_dialog_initial(parent),
            filetypes=list(_MP4_EXTS),
        )
        if p:
            mp4_var.set(str(p))
            resolve_and_load(str(p))

    ttk.Button(path_fr, text="찾기…", command=pick_mp4).grid(row=0, column=2, padx=(0, 6))
    btn_load.grid(row=0, column=3, padx=(0, 6))
    btn_cancel_load.grid(row=0, column=4)
    btn_cancel_load.configure(command=cancel_load)

    save_fr = ttk.Frame(frm)
    save_fr.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    save_fr.grid_columnconfigure(1, weight=1)
    save_fr.grid_columnconfigure(4, weight=1)
    ttk.Label(save_fr, text="저장 폴더", width=8).grid(row=0, column=0, sticky="w")
    out_dir_ent = ttk.Entry(save_fr, textvariable=out_dir_var)
    out_dir_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6))

    def pick_out_dir() -> None:
        init = Path(out_dir_var.get().strip()) if out_dir_var.get().strip() else default_output_dir()
        if not init.is_dir():
            init = init.parent if init.parent.is_dir() else Path.home()
        p = filedialog.askdirectory(title="저장 폴더", initialdir=folder_dialog_initial(init))
        if p:
            out_dir_var.set(p)
            state["output_dir"] = Path(p)

    ttk.Button(save_fr, text="찾기…", command=pick_out_dir).grid(row=0, column=2, padx=(0, 12))
    ttk.Label(save_fr, text="파일명", width=6).grid(row=0, column=3, sticky="w")
    ttk.Entry(save_fr, textvariable=out_name_var, width=24).grid(row=0, column=4, sticky="ew", padx=(4, 0))

    time_fr = ttk.Frame(frm)
    time_fr.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    ttk.Label(time_fr, text="구간", width=8).pack(side=tk.LEFT)
    ttk.Label(time_fr, text="시작").pack(side=tk.LEFT, padx=(0, 4))
    start_entry = ttk.Entry(time_fr, textvariable=start_entry_var, width=10)
    start_entry.pack(side=tk.LEFT, padx=(0, 12))
    ttk.Label(time_fr, text="종료").pack(side=tk.LEFT, padx=(0, 4))
    end_entry = ttk.Entry(time_fr, textvariable=end_entry_var, width=10)
    end_entry.pack(side=tk.LEFT, padx=(0, 8))
    ttk.Label(
        time_fr,
        text="예: 1:10 · 2:30 (종료 비우면 끝까지)",
        foreground="#555555",
    ).pack(side=tk.LEFT)

    def sync_time_entries_from_state() -> None:
        start_entry_var.set(_fmt_time_entry(float(state["start_sec"] or 0.0)))
        if state["end_sec"] is None:
            end_entry_var.set("")
        else:
            end_entry_var.set(_fmt_time_entry(float(state["end_sec"])))

    def apply_time_entries_to_state() -> None:
        dur = float(state.get("duration") or 0.0)
        start = _parse_sec(start_entry_var.get())
        if start is not None:
            state["start_sec"] = min(start, dur) if dur > 0 else start
        end_raw = end_entry_var.get().strip()
        if not end_raw:
            state["end_sec"] = None
        else:
            end = _parse_sec(end_raw)
            if end is None:
                status_var.set("종료 시각 형식이 올바르지 않습니다. 예: 2:30")
                return
            state["end_sec"] = min(end, dur) if dur > 0 else end
            if state["end_sec"] is not None and state["end_sec"] <= state["start_sec"]:
                state["start_sec"], state["end_sec"] = state["end_sec"], state["start_sec"]
        # 입력값을 분:초 형식으로 정규화해 다시 표시
        sync_time_entries_from_state()
        update_time_labels()
        redraw_timeline()
        save_gui_settings(
            mp4_path=mp4_var.get().strip(),
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )

    start_entry.bind("<FocusOut>", lambda _e: apply_time_entries_to_state())
    end_entry.bind("<FocusOut>", lambda _e: apply_time_entries_to_state())
    start_entry.bind("<Return>", lambda _e: apply_time_entries_to_state())
    end_entry.bind("<Return>", lambda _e: apply_time_entries_to_state())

    def on_mp4_drop(paths: list[str]) -> None:
        for raw in paths:
            text = raw.strip()
            if is_youtube_url(text):
                mp4_var.set(text)
                resolve_and_load(text)
                return
            p = Path(text)
            if p.is_file() and p.suffix.lower() in {".mp4", ".mov", ".mkv", ".m4v", ".webm"}:
                mp4_var.set(str(p))
                resolve_and_load(str(p))
                return

    def on_path_set(p: str) -> None:
        resolve_and_load(p)

    bind_path_row_dnd(mp4_ent, path_fr, mp4_var, mode="file", on_set=on_path_set)
    bind_file_drop(root, on_mp4_drop)

    ctrl_fr = ttk.Frame(frm)
    ctrl_fr.grid(row=3, column=0, sticky="ew", pady=(0, 6))
    ttk.Radiobutton(ctrl_fr, text="시작 클릭", variable=timeline_mode, value="start").pack(side=tk.LEFT, padx=(0, 8))
    ttk.Radiobutton(ctrl_fr, text="종료 클릭", variable=timeline_mode, value="end").pack(side=tk.LEFT, padx=(0, 16))
    ttk.Label(ctrl_fr, textvariable=start_var).pack(side=tk.LEFT, padx=(0, 12))
    ttk.Label(ctrl_fr, textvariable=end_var).pack(side=tk.LEFT, padx=(0, 12))
    ttk.Label(ctrl_fr, textvariable=crop_var).pack(side=tk.LEFT)

    body = ttk.Frame(frm)
    body.grid(row=4, column=0, sticky="nsew")
    body.grid_columnconfigure(0, weight=1)
    body.grid_rowconfigure(0, weight=1)

    preview_cv = tk.Canvas(body, bg="#111", highlightthickness=1, highlightbackground="#555")
    preview_cv.grid(row=0, column=0, sticky="nsew")

    timeline_cv = tk.Canvas(frm, height=64, bg="#222", highlightthickness=1, highlightbackground="#555")
    timeline_cv.grid(row=5, column=0, sticky="ew", pady=(8, 4))

    seek_fr = ttk.Frame(frm)
    seek_fr.grid(row=6, column=0, sticky="ew", pady=(0, 8))
    seek_fr.grid_columnconfigure(1, weight=1)
    ttk.Label(seek_fr, text="미리보기").grid(row=0, column=0, sticky="w", padx=(0, 6))
    seek_scale = ttk.Scale(seek_fr, from_=0.0, to=1.0, orient=tk.HORIZONTAL)
    seek_scale.grid(row=0, column=1, sticky="ew")
    ttk.Label(seek_fr, textvariable=preview_time_var, width=10).grid(row=0, column=2, padx=(6, 0))

    speed_var = tk.StringVar(value="1")
    speed_hint_var = tk.StringVar(value="")
    speed_fr = ttk.Frame(frm)
    speed_fr.grid(row=7, column=0, sticky="ew", pady=(0, 6))
    ttk.Label(speed_fr, text="느리게", width=8).pack(side=tk.LEFT)
    for key, _val, label in SPEED_CHOICES:
        ttk.Radiobutton(speed_fr, text=label, variable=speed_var, value=key).pack(
            side=tk.LEFT, padx=(0, 10)
        )
    ttk.Label(speed_fr, textvariable=speed_hint_var).pack(side=tk.LEFT, padx=(8, 0))

    loop_mode_var = tk.StringVar(value="count")  # count | sec
    loop_value_var = tk.StringVar(value="3")
    loop_hint_var = tk.StringVar(value="")
    loop_unit_var = tk.StringVar(value="번")
    loop_fade_var = tk.BooleanVar(value=True)
    loop_fr = ttk.Frame(frm)
    loop_fr.grid(row=8, column=0, sticky="ew", pady=(0, 4))
    ttk.Label(loop_fr, text="구간 반복", width=8).pack(side=tk.LEFT)
    ttk.Radiobutton(loop_fr, text="몇 번", variable=loop_mode_var, value="count").pack(
        side=tk.LEFT, padx=(0, 6)
    )
    ttk.Radiobutton(loop_fr, text="몇 초", variable=loop_mode_var, value="sec").pack(
        side=tk.LEFT, padx=(0, 8)
    )
    ttk.Entry(loop_fr, textvariable=loop_value_var, width=6).pack(side=tk.LEFT)
    ttk.Label(loop_fr, textvariable=loop_unit_var, width=3).pack(side=tk.LEFT, padx=(4, 8))
    ttk.Checkbutton(loop_fr, text="이음새 페이드", variable=loop_fade_var).pack(
        side=tk.LEFT, padx=(0, 10)
    )
    btn_loop = ttk.Button(loop_fr, text="반복 저장")
    btn_loop.pack(side=tk.LEFT, padx=(0, 6))
    ttk.Label(loop_fr, textvariable=loop_hint_var).pack(side=tk.LEFT)

    loop_auto_fr = ttk.Frame(frm)
    loop_auto_fr.grid(row=9, column=0, sticky="ew", pady=(0, 6))
    ttk.Label(loop_auto_fr, text="", width=8).pack(side=tk.LEFT)
    btn_loop_auto = ttk.Button(loop_auto_fr, text="자동 찾기")
    btn_loop_auto.pack(side=tk.LEFT, padx=(0, 6))
    btn_loop_preview = ttk.Button(loop_auto_fr, text="미리보기")
    btn_loop_preview.pack(side=tk.LEFT, padx=(0, 6))
    btn_loop_batch = ttk.Button(loop_auto_fr, text="폴더 일괄")
    btn_loop_batch.pack(side=tk.LEFT, padx=(0, 10))
    ttk.Label(
        loop_auto_fr,
        text="자동 찾기=시작 기준 종료점 · 실패 시 수동 조정",
        foreground="#555555",
    ).pack(side=tk.LEFT)

    btn_fr = ttk.Frame(frm)
    btn_fr.grid(row=10, column=0, sticky="ew")
    btn_reset_start = ttk.Button(btn_fr, text="시작 초기화")
    btn_reset_start.pack(side=tk.LEFT, padx=(0, 6))
    btn_reset_end = ttk.Button(btn_fr, text="종료 초기화")
    btn_reset_end.pack(side=tk.LEFT, padx=(0, 6))
    btn_reset_crop = ttk.Button(btn_fr, text="영역 초기화")
    btn_reset_crop.pack(side=tk.LEFT, padx=(0, 16))
    btn_crop = ttk.Button(btn_fr, text="자르기")
    btn_crop.pack(side=tk.LEFT, padx=(0, 6))
    btn_crop_10 = ttk.Button(btn_fr, text="10초 자르기")
    btn_crop_10.pack(side=tk.LEFT, padx=(0, 16))
    ttk.Button(btn_fr, text="Filmot", command=lambda: webbrowser.open(_FILMOT_URL)).pack(side=tk.LEFT, padx=(0, 6))
    ttk.Button(btn_fr, text="YouGlish", command=lambda: webbrowser.open(_YOUGLISH_URL)).pack(side=tk.LEFT)

    ttk.Label(frm, textvariable=status_var).grid(row=11, column=0, sticky="w", pady=(8, 0))

    def clear_crop_visual() -> None:
        if state["rect_id"] is not None:
            preview_cv.delete(state["rect_id"])
            state["rect_id"] = None
        state["crop"] = None
        crop_var.set("영역: 전체")

    def clear_timeline_thumbs() -> None:
        state["timeline_thumbs"] = []
        state["timeline_photos"] = []

    def timeline_thumb_count() -> int:
        w = max(timeline_cv.winfo_width(), 320)
        return max(_TIMELINE_THUMB_MIN, min(_TIMELINE_THUMB_MAX, w // _TIMELINE_THUMB_W))

    def schedule_timeline_thumbs() -> None:
        dur = state["duration"]
        path: Path | None = state.get("path")
        yt_url: str | None = state.get("youtube_url")
        if dur <= 0 or ((path is None or not path.is_file()) and not yt_url):
            clear_timeline_thumbs()
            redraw_timeline()
            return
        state["timeline_thumb_token"] = state.get("timeline_thumb_token", 0) + 1
        token = state["timeline_thumb_token"]
        count = timeline_thumb_count()
        if count <= 1:
            times = [0.0]
        else:
            times = [dur * i / (count - 1) for i in range(count)]

        def work() -> None:
            try:
                mp4_edit_log(f"timeline thumbs start count={count} token={token}")
                tl_dir = temp_timeline_dir()
                stream = state.get("stream_url")
                if yt_url and not stream:
                    stream = get_youtube_stream_url(yt_url)
                    state["stream_url"] = stream
                from PIL import Image

                images: list[tuple[float, Image.Image]] = []
                for i, t in enumerate(times):
                    if token != state.get("timeline_thumb_token", 0):
                        mp4_edit_log(f"timeline thumbs cancelled token={token}")
                        return
                    png = tl_dir / f"tl_{token}_{i}.png"
                    extract_timeline_frame(
                        path=path if path and path.is_file() else None,
                        stream_url=stream,
                        time_sec=t,
                        dest=png,
                    )
                    im = Image.open(png)
                    im = im.resize(
                        (_TIMELINE_THUMB_W, _TIMELINE_THUMB_H),
                        Image.Resampling.LANCZOS,
                    )
                    images.append((t, im))

                def apply() -> None:
                    if token != state.get("timeline_thumb_token", 0):
                        return
                    from PIL import ImageTk

                    photos: list[tuple[float, object]] = []
                    keep: list[object] = []
                    for t, im in images:
                        photo = ImageTk.PhotoImage(im)
                        photos.append((t, photo))
                        keep.append(photo)
                    state["timeline_thumbs"] = photos
                    state["timeline_photos"] = keep
                    redraw_timeline()
                    mp4_edit_log(f"timeline thumbs ok count={len(photos)} token={token}")

                safe_after(root, apply)
            except Exception as e:
                mp4_edit_log_exc(f"timeline thumbs FAIL token={token}", e)

                def fail() -> None:
                    if token != state.get("timeline_thumb_token", 0):
                        return
                    clear_timeline_thumbs()
                    redraw_timeline()

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def redraw_timeline() -> None:
        timeline_cv.delete("all")
        w = max(timeline_cv.winfo_width(), 10)
        h = max(timeline_cv.winfo_height(), 10)
        dur = state["duration"]
        thumbs: list = state.get("timeline_thumbs") or []
        pad = 4

        if thumbs and dur > 0:
            n = len(thumbs)
            slot_w = (w - pad * 2) / n
            for i, (_t, photo) in enumerate(thumbs):
                x0 = pad + i * slot_w
                x1 = pad + (i + 1) * slot_w
                cx = (x0 + x1) / 2
                timeline_cv.create_image(cx, h // 2, image=photo, anchor=tk.CENTER)
                timeline_cv.create_rectangle(x0, 2, x1, h - 2, outline="#444")
        else:
            timeline_cv.create_rectangle(pad, h // 2 - 6, w - pad, h // 2 + 6, fill="#444", outline="#666")

        if dur <= 0:
            return

        def x_at(sec: float) -> float:
            return pad + (w - pad * 2) * (sec / dur)

        end_sec = state["end_sec"] if state["end_sec"] is not None else dur
        sx = x_at(state["start_sec"])
        ex = x_at(end_sec)
        if state["end_sec"] is not None and end_sec > state["start_sec"]:
            timeline_cv.create_rectangle(sx, 2, ex, h - 2, fill="#2e7d32", stipple="gray50", outline="")
        state["start_line"] = timeline_cv.create_line(sx, 2, sx, h - 2, fill="#4caf50", width=3)
        timeline_cv.create_text(sx, 8, text="S", fill="#4caf50", anchor=tk.N, font=(fam, max(8, sz - 1), "bold"))
        state["end_line"] = timeline_cv.create_line(ex, 2, ex, h - 2, fill="#f44336", width=3)
        timeline_cv.create_text(ex, h - 8, text="E", fill="#f44336", anchor=tk.S, font=(fam, max(8, sz - 1), "bold"))

    def update_time_labels() -> None:
        start_var.set(f"시작: {_fmt_time(state['start_sec'])}")
        if state["end_sec"] is None:
            end_var.set(f"종료: {_fmt_time(state['duration'])} (끝)")
        else:
            end_var.set(f"종료: {_fmt_time(state['end_sec'])}")
        update_speed_hint()
        update_loop_hint()

    def update_speed_hint() -> None:
        speed = normalize_speed(speed_var.get())
        start = float(state.get("start_sec") or 0.0)
        end = state.get("end_sec")
        dur = float(state.get("duration") or 0.0)
        if end is None:
            end = dur if dur > 0 else None
        if end is None or end <= start:
            if abs(speed - 1.0) < 1e-9:
                speed_hint_var.set("← 자르기 할 때 적용")
            else:
                speed_hint_var.set("← 자르기 하면 더 길어짐")
            return
        clip = float(end) - start
        if abs(speed - 1.0) < 1e-9:
            speed_hint_var.set(f"자르기 시 {_fmt_time(clip)}")
            return
        out_dur = clip / speed
        speed_hint_var.set(f"자르기 시 {_fmt_time(clip)} → {_fmt_time(out_dur)}")

    def _loop_params_from_ui() -> tuple[int, float | None]:
        """(횟수, 목표초|None). 모드에 따라 한쪽만 유효."""
        raw = (loop_value_var.get() or "").strip() or "3"
        if loop_mode_var.get() == "sec":
            sec = _parse_sec(raw)
            if sec is None or sec <= 0:
                raise ValueError("초는 숫자로 입력하세요. 예: 3")
            return 3, sec
        try:
            count = int(float(raw))
        except ValueError as e:
            raise ValueError("횟수는 정수로 입력하세요. 예: 3") from e
        if count < 1:
            raise ValueError("횟수는 1 이상이어야 합니다.")
        return count, None

    def update_loop_hint() -> None:
        loop_unit_var.set("초" if loop_mode_var.get() == "sec" else "번")
        start = float(state.get("start_sec") or 0.0)
        end = state.get("end_sec")
        dur = float(state.get("duration") or 0.0)
        if end is None or float(end) <= start:
            loop_hint_var.set("① 시작·종료 모두 지정  ② 숫자 입력  ③ 반복 저장")
            return
        try:
            count, target = _loop_params_from_ui()
            _n, loop_out, total_out = resolve_loop_plan(
                loop_start=start,
                loop_end=float(end),
                total_dur=dur,
                repeat_count=count,
                target_loop_sec=target,
            )
        except ValueError as e:
            loop_hint_var.set(str(e))
            return
        seg = float(end) - start
        if target is not None:
            loop_hint_var.set(
                f"선택 {_fmt_time(seg)} 구간을 {_fmt_time(loop_out)}까지 반복 → 전체 {_fmt_time(total_out)}"
            )
        else:
            loop_hint_var.set(
                f"선택 {_fmt_time(seg)} 구간을 {count}번 → 전체 {_fmt_time(total_out)}"
            )

    def canvas_to_video(x: float, y: float) -> tuple[int, int]:
        scale = state["display_scale"] or 1.0
        vx = int((x - state["display_off_x"]) / scale)
        vy = int((y - state["display_off_y"]) / scale)
        vx = max(0, min(state["video_w"] - 1, vx))
        vy = max(0, min(state["video_h"] - 1, vy))
        return vx, vy

    speed_var.trace_add("write", lambda *_a: update_speed_hint())
    loop_mode_var.trace_add("write", lambda *_a: update_loop_hint())
    loop_value_var.trace_add("write", lambda *_a: update_loop_hint())
    update_speed_hint()
    update_loop_hint()

    def draw_crop_rect(x0: float, y0: float, x1: float, y1: float) -> None:
        if state["rect_id"] is not None:
            preview_cv.delete(state["rect_id"])
        x0, x1 = sorted((x0, x1))
        y0, y1 = sorted((y0, y1))
        if abs(x1 - x0) < 4 or abs(y1 - y0) < 4:
            return
        state["rect_id"] = preview_cv.create_rectangle(
            x0, y0, x1, y1, outline="#ffeb3b", width=2, dash=(4, 2)
        )
        vx0, vy0 = canvas_to_video(x0, y0)
        vx1, vy1 = canvas_to_video(x1, y1)
        x = min(vx0, vx1)
        y = min(vy0, vy1)
        w = abs(vx1 - vx0)
        h = abs(vy1 - vy0)
        if w >= 4 and h >= 4:
            state["crop"] = (x, y, w, h)
            crop_var.set(f"영역: {x},{y} {w}×{h}")

    def show_frame_at(time_sec: float) -> None:
        path: Path | None = state.get("path")
        yt_url: str | None = state.get("youtube_url")
        if (path is None or not path.is_file()) and not yt_url:
            return
        time_sec = max(0.0, min(time_sec, max(state["duration"], 0.0)))
        preview_time_var.set(_fmt_time(time_sec))
        try:
            png = temp_preview_png()
            if path is not None and path.is_file():
                extract_frame_png(path, time_sec, png)
            else:
                stream = state.get("stream_url")
                if not stream:
                    stream = get_youtube_stream_url(yt_url)
                    state["stream_url"] = stream
                extract_frame_png_from_url(stream, time_sec, png)
            from PIL import Image, ImageTk

            im = Image.open(png)
            if state["video_w"] <= 0 or state["video_h"] <= 0:
                state["video_w"], state["video_h"] = im.size
            cw = max(preview_cv.winfo_width(), 320)
            ch = max(preview_cv.winfo_height(), 240)
            scale = min(cw / im.width, ch / im.height, 1.0)
            dw, dh = max(1, int(im.width * scale)), max(1, int(im.height * scale))
            if scale < 1.0:
                im = im.resize((dw, dh), Image.Resampling.LANCZOS)
            state["display_scale"] = im.width / max(state["video_w"], 1)
            state["display_off_x"] = (cw - im.width) / 2
            state["display_off_y"] = (ch - im.height) / 2
            photo = ImageTk.PhotoImage(im)
            state["photo"] = photo
            preview_cv.delete("all")
            preview_cv.create_image(cw // 2, ch // 2, image=photo, anchor=tk.CENTER)
            if state["crop"]:
                x, y, w, h = state["crop"]
                s = state["display_scale"]
                ox, oy = state["display_off_x"], state["display_off_y"]
                draw_crop_rect(
                    ox + x * s,
                    oy + y * s,
                    ox + (x + w) * s,
                    oy + (y + h) * s,
                )
        except Exception as e:
            mp4_edit_log_exc(f"preview FAIL t={time_sec}", e)
            status_var.set(str(e))

    def set_status(msg: str, *, tag: str = "") -> None:
        if tag:
            mp4_edit_log(f"status[{tag}]: {msg}")
        else:
            mp4_edit_log(f"status: {msg}")
        status_var.set(msg)

    def crop_status(msg: str) -> None:
        mp4_edit_log(f"crop status callback: {msg}")
        safe_after(root, lambda m=msg: status_var.set(m))

    def schedule_preview(time_sec: float) -> None:
        job = state.get("preview_job")
        if job is not None:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass

        def run() -> None:
            show_frame_at(time_sec)

        state["preview_job"] = root.after(120, run)

    def on_seek(_val: str) -> None:
        if state["duration"] <= 0:
            return
        t = float(seek_scale.get()) * state["duration"]
        schedule_preview(t)

    seek_scale.configure(command=on_seek)

    def _apply_output_dir_from_ui(source_path: Path | None = None) -> Path:
        raw = out_dir_var.get().strip()
        if raw:
            p = Path(raw)
            state["output_dir"] = p
            return p
        if state.get("path"):
            return state["path"].parent
        if source_path is not None and source_path.is_file():
            return source_path.parent
        return default_output_dir()

    def _apply_loaded_video(
        path: Path,
        *,
        dur: float,
        size: tuple[int, int],
        source_text: str | None = None,
    ) -> None:
        touch_workspace_from_path(path)
        src_label = source_text or str(path)
        mp4_var.set(src_label)
        save_gui_settings(
            mp4_path=src_label,
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )
        state["path"] = path
        state["youtube_url"] = None
        state["youtube_id"] = None
        state["stream_url"] = None
        state["source_text"] = src_label
        if not out_dir_var.get().strip():
            state["output_dir"] = path.parent
            out_dir_var.set(str(path.parent))
        state["duration"] = dur
        state["video_w"], state["video_h"] = size
        apply_time_entries_to_state()
        clear_crop_visual()
        seek_scale.configure(to=dur if dur > 0 else 1.0)
        seek_scale.set(0.0)
        sync_time_entries_from_state()
        update_time_labels()
        redraw_timeline()
        status_var.set(f"로드: {path.name} ({_fmt_time(dur)}, {size[0]}×{size[1]})")
        schedule_preview(0.0)
        schedule_timeline_thumbs()

    def load_video(path: Path, *, source_text: str | None = None) -> None:
        path = Path(path)
        if not path.is_file():
            safe_messagebox(root, "showerror", "7_2 mp4Edit", f"파일 없음:\n{path}")
            return
        dur = probe_duration(path)
        if dur is None or dur <= 0:
            safe_messagebox(root, "showerror", "7_2 mp4Edit", "영상 길이를 읽을 수 없습니다 (ffprobe).")
            return
        size = probe_video_size(path) or (0, 0)
        _apply_loaded_video(path, dur=dur, size=size, source_text=source_text)

    def load_youtube(url: str, *, source_text: str | None = None) -> None:
        src_label = source_text or url
        mp4_var.set(src_label)
        save_gui_settings(
            mp4_path=src_label,
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )
        state["path"] = None
        state["youtube_url"] = url
        state["stream_url"] = None
        state["source_text"] = src_label
        state["youtube_id"] = youtube_video_id(url)
        if not out_dir_var.get().strip():
            state["output_dir"] = default_output_dir()
            out_dir_var.set(str(state["output_dir"]))
        apply_time_entries_to_state()
        clear_crop_visual()
        update_time_labels()
        redraw_timeline()
        status_var.set(f"YouTube: {state['youtube_id']} ({_fmt_time(state['duration'])})")
        schedule_preview(0.0)
        schedule_timeline_thumbs()

    def resolve_and_load(text: str) -> None:
        raw = (text or "").strip()
        mp4_edit_log(f"resolve_and_load: {raw[:120]!r}")
        if not raw:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", "MP4 파일 또는 YouTube URL 을 입력하세요.")
            return
        if state.get("loading") or state.get("busy"):
            set_status(
                "이미 불러오는 중입니다. 「불러오기 취소」 후 다시 시도하세요.",
                tag="load",
            )
            mp4_edit_log("resolve_and_load skipped (loading/busy)")
            return
        clear_timeline_thumbs()
        redraw_timeline()
        token = begin_load()
        if is_youtube_url(raw):
            set_status("YouTube 전체 다운로드 중…", tag="load")
            out_dir_snap = _apply_output_dir_from_ui(None)

            def work() -> None:
                try:
                    mp4_edit_log(f"load youtube worker start token={token}")
                    if _load_cancelled(token):
                        mp4_edit_log(f"load youtube cancelled before download token={token}")
                        return

                    def _status(msg: str) -> None:
                        if _load_cancelled(token):
                            return
                        safe_after(root, lambda m=msg: set_status(m, tag="load"))

                    path = download_youtube(
                        raw,
                        dest_dir=out_dir_snap,
                        on_status=_status,
                    )
                    if _load_cancelled(token):
                        safe_after(root, lambda t=token: end_load(t))
                        return
                    dur = probe_duration(path)
                    if dur is None or dur <= 0:
                        meta = fetch_youtube_meta(raw)
                        dur = meta.duration
                    size = probe_video_size(path) or (0, 0)
                    if size == (0, 0):
                        try:
                            meta = fetch_youtube_meta(raw)
                            size = (meta.width, meta.height)
                        except Exception:
                            pass
                    if _load_cancelled(token):
                        safe_after(root, lambda t=token: end_load(t))
                        return
                    yt_norm = normalize_youtube_url(raw)
                    yt_id = youtube_video_id(raw)

                    def ok() -> None:
                        if end_load(token):
                            mp4_edit_log(f"load youtube ok skipped (cancelled) token={token}")
                            return
                        mp4_edit_log(
                            f"load youtube full ok path={path} dur={dur} {size[0]}x{size[1]} token={token}"
                        )
                        _apply_loaded_video(path, dur=dur, size=size, source_text=str(path))
                        state["youtube_url"] = yt_norm
                        state["youtube_id"] = yt_id
                        status_var.set(
                            f"다운로드 완료: {path.name} ({_fmt_time(dur)}, {size[0]}×{size[1]})"
                        )

                    safe_after(root, ok)
                except Exception as e:
                    mp4_edit_log_exc(f"load youtube worker FAIL token={token}", e)

                    def fail() -> None:
                        if end_load(token):
                            return
                        set_status(str(e), tag="load")
                        safe_messagebox(
                            root,
                            "showerror",
                            "7_2 mp4Edit",
                            f"{e}\n\n로그:\n{log_file_display()}",
                        )

                    safe_after(root, fail)

            threading.Thread(target=work, daemon=True).start()
            return

        # 로컬/네트워크 경로 — is_file·ffprobe 는 워커에서 (S: 등 네트워크 드라이브 UI 정지 방지)
        set_status("영상 확인 중…", tag="load")

        def work_local() -> None:
            try:
                mp4_edit_log(f"load local worker start path={raw!r} token={token}")
                if _load_cancelled(token):
                    return
                path = Path(raw)
                try:
                    exists = path.is_file()
                except OSError as e:
                    raise RuntimeError(
                        f"파일에 접근할 수 없습니다 (네트워크 드라이브·권한):\n{raw}\n{e}"
                    ) from e
                if not exists:
                    raise FileNotFoundError(
                        f"파일을 찾을 수 없습니다:\n{raw}\n\n"
                        "경로·드라이브(S: 등) 연결을 확인하세요."
                    )
                if _load_cancelled(token):
                    safe_after(root, lambda t=token: end_load(t))
                    return
                safe_after(root, lambda: set_status("영상 분석 중…", tag="load"))
                dur = probe_duration(path)
                if _load_cancelled(token):
                    safe_after(root, lambda t=token: end_load(t))
                    return
                if dur is None or dur <= 0:
                    raise RuntimeError(
                        "영상 길이를 읽을 수 없습니다 (ffprobe).\n"
                        f"ffprobe={ffprobe_bin() or '없음'}, ffmpeg={ffmpeg_bin() or '없음'}\n"
                        f"파일: {path}"
                    )
                size = probe_video_size(path) or (0, 0)
                if _load_cancelled(token):
                    safe_after(root, lambda t=token: end_load(t))
                    return

                def ok() -> None:
                    if end_load(token):
                        return
                    _apply_loaded_video(path, dur=dur, size=size, source_text=raw)

                safe_after(root, ok)
            except Exception as e:
                mp4_edit_log_exc(f"load local worker FAIL token={token}", e)

                def fail() -> None:
                    if end_load(token):
                        return
                    set_status(str(e), tag="load")
                    safe_messagebox(
                        root,
                        "showerror",
                        "7_2 mp4Edit",
                        f"{e}\n\n로그:\n{log_file_display()}",
                    )

                safe_after(root, fail)

        threading.Thread(target=work_local, daemon=True).start()

    def on_load_click() -> None:
        resolve_and_load(mp4_var.get())

    btn_load.configure(command=on_load_click)
    mp4_ent.bind("<Return>", lambda _e: on_load_click())

    def timeline_click(event: tk.Event) -> None:
        dur = state["duration"]
        if dur <= 0:
            return
        w = max(timeline_cv.winfo_width(), 10)
        pad = 4
        frac = max(0.0, min(1.0, (event.x - pad) / max(w - pad * 2, 1)))
        t = frac * dur
        if timeline_mode.get() == "start":
            state["start_sec"] = t
            if state["end_sec"] is not None and state["end_sec"] <= state["start_sec"]:
                state["end_sec"] = None
        else:
            state["end_sec"] = t
            if state["end_sec"] <= state["start_sec"]:
                state["start_sec"], state["end_sec"] = state["end_sec"], state["start_sec"]
        update_time_labels()
        redraw_timeline()
        sync_time_entries_from_state()
        seek_scale.set(t)
        schedule_preview(t)

    timeline_cv.bind("<Button-1>", timeline_click)

    def on_timeline_configure(_e: tk.Event) -> None:
        redraw_timeline()
        if state["duration"] <= 0:
            return
        want = timeline_thumb_count()
        have = len(state.get("timeline_thumbs") or [])
        if have == 0 or abs(want - have) >= 2:
            schedule_timeline_thumbs()

    timeline_cv.bind("<Configure>", on_timeline_configure)

    def preview_press(event: tk.Event) -> None:
        state["drag_start"] = (event.x, event.y)

    def preview_drag(event: tk.Event) -> None:
        if state["drag_start"]:
            x0, y0 = state["drag_start"]
            draw_crop_rect(x0, y0, event.x, event.y)

    def preview_release(event: tk.Event) -> None:
        if state["drag_start"]:
            x0, y0 = state["drag_start"]
            draw_crop_rect(x0, y0, event.x, event.y)
        state["drag_start"] = None

    preview_cv.bind("<ButtonPress-1>", preview_press)
    preview_cv.bind("<B1-Motion>", preview_drag)
    preview_cv.bind("<ButtonRelease-1>", preview_release)
    preview_cv.bind("<Configure>", lambda _e: schedule_preview(float(seek_scale.get()) * max(state["duration"], 0.0)))

    def reset_start() -> None:
        state["start_sec"] = 0.0
        update_time_labels()
        redraw_timeline()
        sync_time_entries_from_state()

    def reset_end() -> None:
        state["end_sec"] = None
        update_time_labels()
        redraw_timeline()
        sync_time_entries_from_state()

    btn_reset_start.configure(command=reset_start)
    btn_reset_end.configure(command=reset_end)
    btn_reset_crop.configure(command=clear_crop_visual)

    def _cut_times_from_entries() -> tuple[float, float | None]:
        start = _parse_sec(start_entry_var.get())
        if start is None:
            start = float(state.get("start_sec") or 0.0)
        end_raw = end_entry_var.get().strip()
        if not end_raw:
            return start, None
        end = _parse_sec(end_raw)
        if end is None:
            return start, state.get("end_sec")
        return start, end

    def do_crop(*, clip_len_sec: float | None = None) -> None:
        raw = mp4_var.get().strip()
        mp4_edit_log(f"do_crop start: {raw[:120]!r} clip_len={clip_len_sec}")
        if not raw:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", "MP4 파일 또는 YouTube URL 을 입력하세요.")
            return
        if state.get("loading") or state.get("busy"):
            set_status("작업 중입니다. 잠시 후 다시 시도하세요.", tag="crop")
            return

        apply_time_entries_to_state()
        start, end = _cut_times_from_entries()
        if clip_len_sec is not None:
            start = float(state.get("start_sec") or 0.0)
            dur = float(state.get("duration") or 0.0)
            end = start + float(clip_len_sec)
            if dur > 0:
                end = min(end, dur)
            if end <= start:
                safe_messagebox(
                    root,
                    "showwarning",
                    "7_2 mp4Edit",
                    f"시작({_fmt_time_entry(start)})에서 {clip_len_sec:g}초를 자를 수 없습니다.\n"
                    "영상 끝을 넘지 않는 시작 시각을 지정하세요.",
                )
                return
            state["start_sec"] = start
            state["end_sec"] = end
            sync_time_entries_from_state()
            update_time_labels()
            redraw_timeline()
        elif end is not None and end <= start:
            safe_messagebox(
                root,
                "showwarning",
                "7_2 mp4Edit",
                f"종료({_fmt_time_entry(end)})가 시작({_fmt_time_entry(start)})보다 뒤여야 합니다.\n"
                "예: 시작 1:10 · 종료 2:30",
            )
            return

        # 불러오기로 받은 로컬 파일이 있으면 우선 사용 (YouTube 전체 다운로드 후)
        path: Path | None = None
        yt_url: str | None = None
        loaded_path = state.get("path")
        if isinstance(loaded_path, Path):
            path = loaded_path
            stem = path.stem
            touch_workspace_from_path(path)
        elif is_youtube_url(raw):
            yt_url = normalize_youtube_url(raw)
            stem = youtube_video_id(yt_url) or "output"
        else:
            path = Path(raw)
            stem = path.stem
            touch_workspace_from_path(path)
        out_base = _apply_output_dir_from_ui(path)
        src_for_name = path or Path(stem + ".mp4")
        speed = normalize_speed(speed_var.get())
        slow_suffix = speed_stem_suffix(speed)
        default_stem = f"{stem}{slow_suffix}" if slow_suffix else stem
        dest = resolve_edit_dest(
            src_for_name,
            output_dir=out_base,
            output_name=out_name_var.get().strip() or None,
            default_stem=default_stem,
        )
        crop = state.get("crop")
        mp4_edit_log(
            f"do_crop dest={dest} start={start} end={end} crop={crop} speed={speed} "
            f"yt={yt_url is not None} path={path}"
        )
        save_gui_settings(
            mp4_path=raw,
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )
        if not ffmpeg_bin():
            safe_messagebox(
                root,
                "showerror",
                "7_2 mp4Edit",
                "ffmpeg 를 찾을 수 없습니다.\n\n"
                "wisdom/tools/ffmpeg/bin 에 ffmpeg.exe·ffprobe.exe 를 두거나\n"
                "시스템 PATH 에 ffmpeg 를 설치하세요.",
            )
            return
        set_busy(True)
        if path is None and yt_url:
            set_status("YouTube 구간 저장 중…", tag="crop")
        elif abs(speed - 1.0) > 1e-9:
            set_status("배속 적용·저장 중…", tag="crop")
        else:
            set_status("저장 중…", tag="crop")

        def work() -> None:
            try:
                mp4_edit_log("do_crop worker thread started")
                src = path
                if src is not None:
                    try:
                        ok_file = src.is_file()
                    except OSError as e:
                        raise RuntimeError(f"파일에 접근할 수 없습니다:\n{src}\n{e}") from e
                    if not ok_file:
                        raise FileNotFoundError(f"파일을 찾을 수 없습니다:\n{src}")
                    crop_status("ffmpeg 자르기 중…" if abs(speed - 1.0) < 1e-9 else "ffmpeg 배속·자르기 중…")
                    crop_and_trim(
                        src,
                        dest,
                        start_sec=start,
                        end_sec=end,
                        crop_rect=crop,
                        speed=speed,
                    )
                elif yt_url:
                    crop_status("YouTube 정보 조회 중…")
                    need_reencode = crop is not None or abs(speed - 1.0) > 1e-9
                    tmp = dest.with_name(dest.stem + "_dl" + dest.suffix) if need_reencode else dest
                    work_path = download_youtube_section(
                        yt_url,
                        start_sec=start,
                        end_sec=end,
                        dest=tmp,
                        on_status=crop_status,
                    )
                    if need_reencode:
                        crop_and_trim(
                            work_path,
                            dest,
                            start_sec=0.0,
                            end_sec=None,
                            crop_rect=crop,
                            speed=speed,
                        )
                        if work_path != dest:
                            try:
                                work_path.unlink(missing_ok=True)
                            except OSError:
                                pass
                else:
                    raise RuntimeError("자를 영상 파일 또는 YouTube URL 이 없습니다.")

                def ok() -> None:
                    set_busy(False)
                    mp4_edit_log(f"do_crop ok dest={dest}")
                    set_status(f"저장 완료: {dest.name}", tag="crop")
                    safe_messagebox(root, "showinfo", "7_2 mp4Edit", f"저장했습니다.\n\n{dest}")

                safe_after(root, ok)
            except Exception as e:
                mp4_edit_log_exc("do_crop worker FAIL", e)

                def fail() -> None:
                    set_busy(False)
                    set_status(str(e), tag="crop")
                    safe_messagebox(
                        root,
                        "showerror",
                        "7_2 mp4Edit",
                        f"{e}\n\n로그:\n{log_file_display()}",
                    )

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def do_crop_10sec() -> None:
        """시작 구간부터 10초 구간 자르기."""
        do_crop(clip_len_sec=_QUICK_CLIP_SEC)

    def do_loop_segment() -> None:
        """시작~종료 구간을 반복하고 앞·뒤는 유지해 저장."""
        raw = mp4_var.get().strip()
        mp4_edit_log(f"do_loop_segment start: {raw[:120]!r}")
        if not raw:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", "MP4 파일 또는 YouTube URL 을 입력하세요.")
            return
        if state.get("loading") or state.get("busy"):
            set_status("작업 중입니다. 잠시 후 다시 시도하세요.", tag="loop")
            return

        apply_time_entries_to_state()
        start, end = _cut_times_from_entries()
        dur = float(state.get("duration") or 0.0)
        # 종료를 비우면 영상 끝까지라서 엉뚱한(너무 긴) 구간이 반복됨 → 명시 필수
        if end is None:
            safe_messagebox(
                root,
                "showwarning",
                "7_2 mp4Edit",
                "반복할 구간의 종료 시각을 지정하세요.\n"
                "(종료를 비우면 영상 끝까지라서 원하지 않는 구간이 반복됩니다.)",
            )
            return
        if end <= start:
            safe_messagebox(
                root,
                "showwarning",
                "7_2 mp4Edit",
                "먼저 타임라인에서 반복할 구간의 시작·종료를 지정하세요.",
            )
            return
        mp4_edit_log(f"do_loop_segment range start={start:.3f} end={end:.3f} dur={dur:.3f}")

        try:
            count, target = _loop_params_from_ui()
        except ValueError as e:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", str(e))
            return
        try:
            n, loop_out, total_out = resolve_loop_plan(
                loop_start=start,
                loop_end=float(end),
                total_dur=dur,
                repeat_count=count,
                target_loop_sec=target,
            )
        except ValueError as e:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", str(e))
            return

        path: Path | None = None
        yt_url: str | None = None
        loaded_path = state.get("path")
        if isinstance(loaded_path, Path):
            path = loaded_path
            stem = path.stem
            touch_workspace_from_path(path)
        elif is_youtube_url(raw):
            yt_url = normalize_youtube_url(raw)
            stem = youtube_video_id(yt_url) or "output"
        else:
            path = Path(raw)
            stem = path.stem
            touch_workspace_from_path(path)

        out_base = _apply_output_dir_from_ui(path)
        src_for_name = path or Path(stem + ".mp4")
        dest = resolve_edit_dest(
            src_for_name,
            output_dir=out_base,
            output_name=out_name_var.get().strip() or None,
            default_stem=f"{stem}_loop{n}",
        )
        save_gui_settings(
            mp4_path=raw,
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )
        if not ffmpeg_bin():
            safe_messagebox(
                root,
                "showerror",
                "7_2 mp4Edit",
                "ffmpeg 를 찾을 수 없습니다.\n\n"
                "wisdom/tools/ffmpeg/bin 에 ffmpeg.exe·ffprobe.exe 를 두거나\n"
                "시스템 PATH 에 ffmpeg 를 설치하세요.",
            )
            return

        set_busy(True)
        if target is not None:
            set_status(
                f"반복 저장 중… 선택 구간 → {_fmt_time(loop_out)} (전체 {_fmt_time(total_out)})",
                tag="loop",
            )
        else:
            set_status(
                f"반복 저장 중… 선택 구간 ×{n} (전체 {_fmt_time(total_out)})",
                tag="loop",
            )

        def work() -> None:
            try:
                src = path

                def loop_status(msg: str) -> None:
                    mp4_edit_log(f"loop status: {msg}")
                    safe_after(root, lambda m=msg: set_status(m, tag="loop"))

                if src is None and yt_url:
                    loop_status("YouTube 전체 다운로드 중…")
                    src = download_youtube(yt_url, dest_dir=out_base, on_status=loop_status)
                if src is None:
                    raise RuntimeError("반복할 영상 파일이 없습니다.")
                try:
                    ok_file = src.is_file()
                except OSError as e:
                    raise RuntimeError(f"파일에 접근할 수 없습니다:\n{src}\n{e}") from e
                if not ok_file:
                    raise FileNotFoundError(f"파일을 찾을 수 없습니다:\n{src}")
                loop_status("ffmpeg 구간 반복 중…")
                fade = 0.15 if loop_fade_var.get() else 0.0
                loop_segment_in_video(
                    src,
                    dest,
                    loop_start=start,
                    loop_end=float(end),
                    repeat_count=count,
                    target_loop_sec=target,
                    crossfade_sec=fade,
                )

                def ok() -> None:
                    set_busy(False)
                    mp4_edit_log(f"do_loop_segment ok dest={dest}")
                    set_status(f"저장 완료: {dest.name}", tag="loop")
                    safe_messagebox(root, "showinfo", "7_2 mp4Edit", f"저장했습니다.\n\n{dest}")

                safe_after(root, ok)
            except Exception as e:
                mp4_edit_log_exc("do_loop_segment worker FAIL", e)

                def fail() -> None:
                    set_busy(False)
                    set_status(str(e), tag="loop")
                    safe_messagebox(
                        root,
                        "showerror",
                        "7_2 mp4Edit",
                        f"{e}\n\n로그:\n{log_file_display()}",
                    )

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    btn_crop.configure(command=do_crop)
    btn_crop_10.configure(command=do_crop_10sec)
    btn_loop.configure(command=do_loop_segment)

    def _require_local_video() -> Path | None:
        raw = mp4_var.get().strip()
        loaded = state.get("path")
        if isinstance(loaded, Path) and loaded.is_file():
            return loaded
        if raw and not is_youtube_url(raw):
            p = Path(raw)
            if p.is_file():
                return p
        return None

    def do_loop_auto_find() -> None:
        """시작 시각 기준으로 종료(루프점) 자동 탐색."""
        path = _require_local_video()
        if path is None:
            safe_messagebox(
                root,
                "showwarning",
                "7_2 mp4Edit",
                "자동 찾기는 로컬 MP4 가 필요합니다.\n먼저 영상을 불러오세요.",
            )
            return
        if state.get("loading") or state.get("busy"):
            set_status("작업 중입니다.", tag="loop")
            return
        apply_time_entries_to_state()
        start = float(state.get("start_sec") or 0.0)
        set_busy(True)
        set_status("자동 루프점 찾는 중…", tag="loop")

        def work() -> None:
            try:
                result = find_loop_points(
                    path,
                    loop_start=start,
                    min_score=DEFAULT_MIN_SCORE,
                    on_progress=lambda m: safe_after(root, lambda msg=m: set_status(msg, tag="loop")),
                )

                def done() -> None:
                    set_busy(False)
                    state["start_sec"] = result.loop_start
                    state["end_sec"] = result.loop_end
                    sync_time_entries_from_state()
                    update_time_labels()
                    redraw_timeline()
                    set_status(result.message, tag="loop")
                    if result.ok:
                        safe_messagebox(root, "showinfo", "7_2 mp4Edit", result.message)
                    else:
                        safe_messagebox(
                            root,
                            "showwarning",
                            "7_2 mp4Edit",
                            result.message + "\n\n후보 구간은 입력란에 넣어 두었습니다.",
                        )

                safe_after(root, done)
            except Exception as e:
                mp4_edit_log_exc("do_loop_auto_find FAIL", e)

                def fail() -> None:
                    set_busy(False)
                    set_status(str(e), tag="loop")
                    safe_messagebox(root, "showerror", "7_2 mp4Edit", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def do_loop_preview() -> None:
        """선택 구간을 2번 반복한 미리보기 파일을 열어 확인."""
        path = _require_local_video()
        if path is None:
            safe_messagebox(
                root,
                "showwarning",
                "7_2 mp4Edit",
                "미리보기는 로컬 MP4 가 필요합니다.",
            )
            return
        if state.get("loading") or state.get("busy"):
            return
        apply_time_entries_to_state()
        start, end = _cut_times_from_entries()
        if end is None or end <= start:
            safe_messagebox(
                root,
                "showwarning",
                "7_2 mp4Edit",
                "미리볼 시작·종료를 지정하세요.\n(자동 찾기를 먼저 실행해도 됩니다.)",
            )
            return
        set_busy(True)
        set_status("미리보기 만드는 중…", tag="loop")
        fade = 0.15 if loop_fade_var.get() else 0.0
        preview_path = Path(tempfile.gettempdir()) / f"mp4_edit_loop_preview_{os.getpid()}.mp4"

        def work() -> None:
            try:
                loop_segment_in_video(
                    path,
                    preview_path,
                    loop_start=start,
                    loop_end=float(end),
                    repeat_count=2,
                    crossfade_sec=fade,
                )

                def ok() -> None:
                    set_busy(False)
                    set_status(f"미리보기: {preview_path.name}", tag="loop")
                    try:
                        os.startfile(str(preview_path))  # type: ignore[attr-defined]
                    except OSError as e:
                        safe_messagebox(root, "showerror", "7_2 mp4Edit", f"미리보기 열기 실패:\n{e}")

                safe_after(root, ok)
            except Exception as e:
                mp4_edit_log_exc("do_loop_preview FAIL", e)

                def fail() -> None:
                    set_busy(False)
                    set_status(str(e), tag="loop")
                    safe_messagebox(root, "showerror", "7_2 mp4Edit", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    def do_loop_batch() -> None:
        """폴더 안 MP4 일괄: 자동 루프점 → 반복 저장. 실패는 목록으로 남김."""
        if state.get("loading") or state.get("busy"):
            return
        init = Path(out_dir_var.get().strip()) if out_dir_var.get().strip() else default_output_dir()
        folder = filedialog.askdirectory(
            title="일괄 처리할 MP4 폴더",
            initialdir=folder_dialog_initial(init),
        )
        if not folder:
            return
        files = list_mp4_files(Path(folder))
        if not files:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", "폴더에 MP4 가 없습니다.")
            return
        try:
            count, target = _loop_params_from_ui()
        except ValueError as e:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", str(e))
            return
        out_base = _apply_output_dir_from_ui(None)
        out_base.mkdir(parents=True, exist_ok=True)
        fade = 0.15 if loop_fade_var.get() else 0.0
        if not messagebox.askyesno(
            "7_2 mp4Edit",
            f"{len(files)}개 MP4 를 일괄 처리합니다.\n"
            f"저장 폴더: {out_base}\n"
            f"유사도 {DEFAULT_MIN_SCORE:.0%} 미만은 건너뛰고 목록에 남깁니다.\n계속할까요?",
        ):
            return
        set_busy(True)

        def work() -> None:
            ok_n = 0
            skip: list[str] = []
            try:
                for i, src in enumerate(files, 1):
                    safe_after(
                        root,
                        lambda i=i, name=src.name: set_status(
                            f"일괄 {i}/{len(files)}: {name}", tag="loop"
                        ),
                    )
                    try:
                        found = find_loop_points(src, loop_start=0.0, min_score=DEFAULT_MIN_SCORE)
                        if not found.ok:
                            skip.append(f"{src.name} — {found.message}")
                            continue
                        dest = resolve_edit_dest(
                            src,
                            output_dir=out_base,
                            default_stem=f"{src.stem}_loop",
                        )
                        loop_segment_in_video(
                            src,
                            dest,
                            loop_start=found.loop_start,
                            loop_end=found.loop_end,
                            repeat_count=count,
                            target_loop_sec=target,
                            crossfade_sec=fade,
                        )
                        ok_n += 1
                    except Exception as e:
                        skip.append(f"{src.name} — {e}")
                        mp4_edit_log_exc(f"batch fail {src}", e)

                def done() -> None:
                    set_busy(False)
                    msg = f"일괄 완료: 성공 {ok_n} / 전체 {len(files)}"
                    set_status(msg, tag="loop")
                    if skip:
                        detail = "\n".join(skip[:30])
                        if len(skip) > 30:
                            detail += f"\n… 외 {len(skip) - 30}건"
                        # 실패 목록 파일
                        fail_path = out_base / "_loop_batch_manual.txt"
                        fail_path.write_text(
                            "수동 시작·종료가 필요한 파일\n\n" + "\n".join(skip) + "\n",
                            encoding="utf-8",
                        )
                        safe_messagebox(
                            root,
                            "showwarning",
                            "7_2 mp4Edit",
                            f"{msg}\n\n수동 필요 {len(skip)}건 →\n{fail_path}\n\n{detail}",
                        )
                    else:
                        safe_messagebox(root, "showinfo", "7_2 mp4Edit", msg)

                safe_after(root, done)
            except Exception as e:
                mp4_edit_log_exc("do_loop_batch FAIL", e)

                def fail() -> None:
                    set_busy(False)
                    set_status(str(e), tag="loop")
                    safe_messagebox(root, "showerror", "7_2 mp4Edit", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    btn_loop_auto.configure(command=do_loop_auto_find)
    btn_loop_preview.configure(command=do_loop_preview)
    btn_loop_batch.configure(command=do_loop_batch)

    def on_close() -> None:
        save_gui_settings(
            mp4_path=mp4_var.get().strip(),
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )

    # 설정에 초 숫자만 있으면 분:초로 정규화
    for _var in (start_entry_var, end_entry_var):
        _raw = _var.get().strip()
        if not _raw:
            continue
        _sec = _parse_sec(_raw)
        if _sec is not None:
            _var.set(_fmt_time_entry(_sec))

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    init = mp4_var.get().strip()
    if init:
        root.after(300, lambda s=init: resolve_and_load(s))
    else:
        redraw_timeline()

    run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
