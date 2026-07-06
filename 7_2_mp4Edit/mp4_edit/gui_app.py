# -*- coding: utf-8 -*-
"""MP4 구간·영역 자르기 GUI."""

from __future__ import annotations

import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from mp4_edit import __version__
from mp4_edit.ffmpeg_util import (
    crop_and_trim,
    extract_frame_png,
    extract_frame_png_from_url,
    probe_duration,
    probe_video_size,
    resolve_edit_dest,
    temp_preview_png,
)
from mp4_edit.paths import default_output_dir
from mp4_edit.settings import load_gui_settings, save_gui_settings
from mp4_edit.youtube_util import (
    download_youtube_section,
    fetch_youtube_meta,
    get_youtube_stream_url,
    is_youtube_url,
    youtube_video_id,
)
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

_MP4_EXTS = (("MP4", "*.mp4"), ("동영상", "*.mp4;*.mov;*.mkv"), ("모든 파일", "*.*"))


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


def _parse_sec(text: str) -> float | None:
    raw = (text or "").strip()
    if not raw:
        return None
    if ":" in raw:
        parts = raw.split(":")
        try:
            if len(parts) == 2:
                return float(parts[0]) * 60.0 + float(parts[1])
            if len(parts) == 3:
                return float(parts[0]) * 3600.0 + float(parts[1]) * 60.0 + float(parts[2])
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
        "preview_job": None,
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

    def set_busy(busy: bool) -> None:
        state["busy"] = busy
        btn_crop.configure(state=tk.DISABLED if busy else tk.NORMAL)
        btn_load.configure(state=tk.DISABLED if busy else tk.NORMAL)

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
    btn_load.grid(row=0, column=3)

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
    ttk.Label(time_fr, text="구간(초)", width=8).pack(side=tk.LEFT)
    ttk.Label(time_fr, text="시작").pack(side=tk.LEFT, padx=(0, 4))
    start_entry = ttk.Entry(time_fr, textvariable=start_entry_var, width=10)
    start_entry.pack(side=tk.LEFT, padx=(0, 12))
    ttk.Label(time_fr, text="종료").pack(side=tk.LEFT, padx=(0, 4))
    end_entry = ttk.Entry(time_fr, textvariable=end_entry_var, width=10)
    end_entry.pack(side=tk.LEFT, padx=(0, 8))
    ttk.Label(time_fr, text="(종료 비우면 끝까지 · YouTube는 이 구간만 다운로드)").pack(side=tk.LEFT)

    def sync_time_entries_from_state() -> None:
        start_entry_var.set(f"{state['start_sec']:.2f}".rstrip("0").rstrip("."))
        if state["end_sec"] is None:
            end_entry_var.set("")
        else:
            end_entry_var.set(f"{state['end_sec']:.2f}".rstrip("0").rstrip("."))

    def apply_time_entries_to_state() -> None:
        start = _parse_sec(start_entry_var.get())
        if start is not None:
            state["start_sec"] = min(start, max(state["duration"], 0.0))
        end_raw = end_entry_var.get().strip()
        if not end_raw:
            state["end_sec"] = None
        else:
            end = _parse_sec(end_raw)
            if end is not None:
                state["end_sec"] = min(end, max(state["duration"], 0.0))
                if state["end_sec"] <= state["start_sec"]:
                    state["start_sec"], state["end_sec"] = state["end_sec"], state["start_sec"]
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

    timeline_cv = tk.Canvas(frm, height=48, bg="#222", highlightthickness=1, highlightbackground="#555")
    timeline_cv.grid(row=5, column=0, sticky="ew", pady=(8, 4))

    seek_fr = ttk.Frame(frm)
    seek_fr.grid(row=6, column=0, sticky="ew", pady=(0, 8))
    seek_fr.grid_columnconfigure(1, weight=1)
    ttk.Label(seek_fr, text="미리보기").grid(row=0, column=0, sticky="w", padx=(0, 6))
    seek_scale = ttk.Scale(seek_fr, from_=0.0, to=1.0, orient=tk.HORIZONTAL)
    seek_scale.grid(row=0, column=1, sticky="ew")
    ttk.Label(seek_fr, textvariable=preview_time_var, width=10).grid(row=0, column=2, padx=(6, 0))

    btn_fr = ttk.Frame(frm)
    btn_fr.grid(row=7, column=0, sticky="ew")
    btn_reset_start = ttk.Button(btn_fr, text="시작 초기화")
    btn_reset_start.pack(side=tk.LEFT, padx=(0, 6))
    btn_reset_end = ttk.Button(btn_fr, text="종료 초기화")
    btn_reset_end.pack(side=tk.LEFT, padx=(0, 6))
    btn_reset_crop = ttk.Button(btn_fr, text="영역 초기화")
    btn_reset_crop.pack(side=tk.LEFT, padx=(0, 16))
    btn_crop = ttk.Button(btn_fr, text="자르기")
    btn_crop.pack(side=tk.LEFT)

    ttk.Label(frm, textvariable=status_var).grid(row=8, column=0, sticky="w", pady=(8, 0))

    def clear_crop_visual() -> None:
        if state["rect_id"] is not None:
            preview_cv.delete(state["rect_id"])
            state["rect_id"] = None
        state["crop"] = None
        crop_var.set("영역: 전체")

    def redraw_timeline() -> None:
        timeline_cv.delete("all")
        w = max(timeline_cv.winfo_width(), 10)
        h = max(timeline_cv.winfo_height(), 10)
        dur = state["duration"]
        timeline_cv.create_rectangle(4, h // 2 - 6, w - 4, h // 2 + 6, fill="#444", outline="#666")
        if dur <= 0:
            return

        def x_at(sec: float) -> float:
            return 4 + (w - 8) * (sec / dur)

        sx = x_at(state["start_sec"])
        state["start_line"] = timeline_cv.create_line(sx, 4, sx, h - 4, fill="#4caf50", width=3)
        timeline_cv.create_text(sx, 10, text="S", fill="#4caf50", anchor=tk.N)
        end_sec = state["end_sec"] if state["end_sec"] is not None else dur
        ex = x_at(end_sec)
        state["end_line"] = timeline_cv.create_line(ex, 4, ex, h - 4, fill="#f44336", width=3)
        timeline_cv.create_text(ex, h - 10, text="E", fill="#f44336", anchor=tk.S)
        if state["end_sec"] is not None and end_sec > state["start_sec"]:
            timeline_cv.create_rectangle(sx, h // 2 - 6, ex, h // 2 + 6, fill="#2e7d32", outline="")

    def update_time_labels() -> None:
        start_var.set(f"시작: {_fmt_time(state['start_sec'])}")
        if state["end_sec"] is None:
            end_var.set(f"종료: {_fmt_time(state['duration'])} (끝)")
        else:
            end_var.set(f"종료: {_fmt_time(state['end_sec'])}")

    def canvas_to_video(x: float, y: float) -> tuple[int, int]:
        scale = state["display_scale"] or 1.0
        vx = int((x - state["display_off_x"]) / scale)
        vy = int((y - state["display_off_y"]) / scale)
        vx = max(0, min(state["video_w"] - 1, vx))
        vy = max(0, min(state["video_h"] - 1, vy))
        return vx, vy

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
            status_var.set(str(e))

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

    def _apply_output_dir_from_ui() -> Path:
        raw = out_dir_var.get().strip()
        if raw:
            p = Path(raw)
            state["output_dir"] = p
            return p
        if state.get("path"):
            return state["path"].parent
        return default_output_dir()

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

    def resolve_and_load(text: str) -> None:
        raw = (text or "").strip()
        if not raw:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", "MP4 파일 또는 YouTube URL 을 입력하세요.")
            return
        if state["busy"]:
            return
        if is_youtube_url(raw):
            set_busy(True)
            status_var.set("YouTube 정보 조회 중…")

            def work() -> None:
                try:
                    meta = fetch_youtube_meta(raw)
                    url = raw

                    def ok() -> None:
                        set_busy(False)
                        state["duration"] = meta.duration
                        state["video_w"] = meta.width
                        state["video_h"] = meta.height
                        seek_scale.configure(to=meta.duration if meta.duration > 0 else 1.0)
                        seek_scale.set(0.0)
                        load_youtube(url, source_text=raw)

                    safe_after(root, ok)
                except Exception as e:

                    def fail() -> None:
                        set_busy(False)
                        status_var.set(str(e))
                        safe_messagebox(root, "showerror", "7_2 mp4Edit", str(e))

                    safe_after(root, fail)

            threading.Thread(target=work, daemon=True).start()
            return
        path = Path(raw)
        if not path.is_file():
            safe_messagebox(root, "showerror", "7_2 mp4Edit", f"파일을 찾을 수 없습니다:\n{raw}")
            return
        load_video(path, source_text=raw)

    def on_load_click() -> None:
        resolve_and_load(mp4_var.get())

    btn_load.configure(command=on_load_click)
    mp4_ent.bind("<Return>", lambda _e: on_load_click())

    def timeline_click(event: tk.Event) -> None:
        dur = state["duration"]
        if dur <= 0:
            return
        w = max(timeline_cv.winfo_width(), 10)
        frac = max(0.0, min(1.0, (event.x - 4) / max(w - 8, 1)))
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
    timeline_cv.bind("<Configure>", lambda _e: redraw_timeline())

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

    def do_crop() -> None:
        path: Path | None = state.get("path")
        yt_url: str | None = state.get("youtube_url")
        if path is None and not yt_url:
            safe_messagebox(root, "showwarning", "7_2 mp4Edit", "영상을 먼저 불러오세요.")
            return
        apply_time_entries_to_state()
        out_base = _apply_output_dir_from_ui()
        stem = state.get("youtube_id") or (path.stem if path else "output")
        src_for_name = path or Path(stem + ".mp4")
        dest = resolve_edit_dest(
            src_for_name,
            output_dir=out_base,
            output_name=out_name_var.get().strip() or None,
            default_stem=stem,
        )
        start = state["start_sec"]
        end = state["end_sec"]
        crop = state["crop"]
        set_busy(True)
        status_var.set("저장 중…")

        def work() -> None:
            try:
                if path is not None and path.is_file():
                    crop_and_trim(
                        path,
                        dest,
                        start_sec=start,
                        end_sec=end,
                        crop_rect=crop,
                    )
                else:
                    tmp = dest.with_name(dest.stem + "_dl" + dest.suffix) if crop else dest
                    work_path = download_youtube_section(
                        yt_url,
                        start_sec=start,
                        end_sec=end,
                        dest=tmp,
                        on_status=lambda msg: safe_after(root, lambda m=msg: status_var.set(m)),
                    )
                    if crop is not None:
                        crop_and_trim(
                            work_path,
                            dest,
                            start_sec=0.0,
                            end_sec=None,
                            crop_rect=crop,
                        )
                        if work_path != dest:
                            try:
                                work_path.unlink(missing_ok=True)
                            except OSError:
                                pass

                def ok() -> None:
                    set_busy(False)
                    status_var.set(f"저장 완료: {dest.name}")
                    safe_messagebox(root, "showinfo", "7_2 mp4Edit", f"저장했습니다.\n\n{dest}")

                safe_after(root, ok)
            except Exception as e:

                def fail() -> None:
                    set_busy(False)
                    status_var.set(str(e))
                    safe_messagebox(root, "showerror", "7_2 mp4Edit", str(e))

                safe_after(root, fail)

        threading.Thread(target=work, daemon=True).start()

    btn_crop.configure(command=do_crop)

    def on_close() -> None:
        save_gui_settings(
            mp4_path=mp4_var.get().strip(),
            output_dir=out_dir_var.get().strip(),
            output_name=out_name_var.get().strip(),
            start_sec=start_entry_var.get().strip(),
            end_sec=end_entry_var.get().strip(),
        )

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    init = mp4_var.get().strip()
    if init:
        root.after_idle(lambda s=init: resolve_and_load(s))
    else:
        redraw_timeline()

    run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
