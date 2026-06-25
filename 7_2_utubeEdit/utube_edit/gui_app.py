# -*- coding: utf-8 -*-
"""7_2_utubeEdit GUI — YouTube 다운로드·장면 분리·구간 MP4 저장."""

from __future__ import annotations

import threading
import traceback
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, ttk

from PIL import Image, ImageTk

from utube_edit import __version__
from utube_edit.download import DownloadError, download_youtube
from utube_edit.media_paths import prepend_local_ffmpeg_bin_to_os_path
from utube_edit.models import SceneSegment
from utube_edit.paths import default_output_dir
from utube_edit.scene_detect import SceneDetectError, build_segments
from utube_edit.video_edit import VideoEditError, build_scene_thumbnails, export_segment
from utube_edit.video_preview import SegmentPreviewPlayer, extract_preview_frame


def _format_time(sec: float) -> str:
    s = max(0, int(sec))
    h, rem = divmod(s, 3600)
    m, ss = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{ss:02d}"
    return f"{m}:{ss:02d}"


def _segment_label(seg: SceneSegment) -> str:
    return f"#{seg.index} {_format_time(seg.start_sec)}–{_format_time(seg.end_sec)}"


def _safe_filename(title: str, fallback: str = "clip") -> str:
    s = "".join(c if c.isalnum() or c in "._-" else "_" for c in title).strip("._-")
    return (s[:40] or fallback)


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import apply_window_chrome, bind_close, run_mainloop, safe_after, tk_host

    prepend_local_ffmpeg_bin_to_os_path()

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"7_2_utubeEdit — YouTube 구간 편집 {__version__}",
        minsize=(960, 620),
        geometry="1100x720",
    )

    url_var = tk.StringVar(value="")
    status_var = tk.StringVar(value="YouTube 주소를 입력한 뒤 「조회」를 누르세요.")
    title_var = tk.StringVar(value="")
    selected_var = tk.StringVar(value="하단 구간을 클릭하세요.")
    busy = {"v": False}

    video_path: Path | None = None
    video_title = ""
    video_id = ""
    save_out_dir = default_output_dir()
    segments: list[SceneSegment] = []
    selected_index: int | None = None
    thumb_photos: dict[int, ImageTk.PhotoImage] = {}
    scene_frames: dict[int, tk.Frame] = {}
    preview_photo: ImageTk.PhotoImage | None = None
    player = SegmentPreviewPlayer()
    playing = {"v": False}

    frm = ttk.Frame(root, padding=8)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.columnconfigure(0, weight=1)
    frm.rowconfigure(3, weight=1)

    top = ttk.LabelFrame(frm, text="YouTube 주소", padding=6)
    top.grid(row=0, column=0, sticky="ew", pady=(0, 6))
    top.columnconfigure(1, weight=1)
    ttk.Label(top, text="URL").grid(row=0, column=0, sticky="w", padx=(0, 6))
    url_ent = ttk.Entry(top, textvariable=url_var)
    url_ent.grid(row=0, column=1, sticky="ew")
    fetch_btn = ttk.Button(top, text="조회")
    fetch_btn.grid(row=0, column=2, padx=(6, 0))
    ttk.Label(
        top,
        text="다운로드 → 장면 분리 → 하단 구간 클릭(중앙 미리보기) → MP4 저장(output)",
        font=("", 8),
    ).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))

    info_fr = ttk.Frame(frm)
    info_fr.grid(row=1, column=0, sticky="ew", pady=(0, 4))
    info_fr.columnconfigure(0, weight=1)
    ttk.Label(info_fr, textvariable=title_var, font=("", 10, "bold")).grid(row=0, column=0, sticky="w")
    ttk.Label(info_fr, textvariable=status_var, font=("", 8)).grid(row=1, column=0, sticky="w")

    btn_fr = ttk.Frame(frm)
    btn_fr.grid(row=2, column=0, sticky="ew", pady=(0, 6))
    save_btn = ttk.Button(btn_fr, text="선택 구간 MP4 저장 (output)", state=tk.DISABLED)
    save_btn.pack(side=tk.LEFT, padx=(0, 6))
    play_btn = ttk.Button(btn_fr, text="미리보기 재생", state=tk.DISABLED)
    play_btn.pack(side=tk.LEFT, padx=(0, 6))
    stop_btn = ttk.Button(btn_fr, text="정지", state=tk.DISABLED)
    stop_btn.pack(side=tk.LEFT, padx=(0, 12))
    ttk.Label(btn_fr, textvariable=selected_var).pack(side=tk.LEFT)

    preview_outer = ttk.LabelFrame(frm, text="영상 미리보기", padding=4)
    preview_outer.grid(row=3, column=0, sticky="nsew", pady=(0, 6))
    preview_outer.columnconfigure(0, weight=1)
    preview_outer.rowconfigure(0, weight=1)
    preview_lbl = tk.Label(
        preview_outer,
        text="구간을 클릭하면 여기에서 미리보기",
        bg="#1a1a1a",
        fg="#cccccc",
        anchor="center",
    )
    preview_lbl.grid(row=0, column=0, sticky="nsew")

    strip_outer = ttk.LabelFrame(frm, text="구간 (연속 · 클릭하여 선택)", padding=4)
    strip_outer.grid(row=4, column=0, sticky="ew")
    strip_outer.columnconfigure(0, weight=1)
    strip_canvas = tk.Canvas(strip_outer, height=188, highlightthickness=0)
    strip_hsb = ttk.Scrollbar(strip_outer, orient="horizontal", command=strip_canvas.xview)
    strip_canvas.configure(xscrollcommand=strip_hsb.set)
    strip_canvas.grid(row=0, column=0, sticky="ew")
    strip_hsb.grid(row=1, column=0, sticky="ew")
    strip_inner = tk.Frame(strip_canvas)
    strip_window = strip_canvas.create_window((0, 0), window=strip_inner, anchor="nw")

    def _on_strip_configure(_e=None) -> None:
        strip_canvas.configure(scrollregion=strip_canvas.bbox("all"))

    def _on_strip_canvas_configure(e: tk.Event) -> None:
        strip_canvas.itemconfigure(strip_window, height=e.height)

    strip_inner.bind("<Configure>", _on_strip_configure)
    strip_canvas.bind("<Configure>", _on_strip_canvas_configure)

    def _on_strip_wheel(e: tk.Event) -> None:
        strip_canvas.xview_scroll(int(-1 * (e.delta / 120)), "units")

    def _bind_strip_wheel(_e: tk.Event) -> None:
        strip_canvas.bind_all("<MouseWheel>", _on_strip_wheel)

    def _unbind_strip_wheel(_e: tk.Event) -> None:
        strip_canvas.unbind_all("<MouseWheel>")

    strip_canvas.bind("<Enter>", _bind_strip_wheel)
    strip_canvas.bind("<Leave>", _unbind_strip_wheel)

    def set_busy(on: bool) -> None:
        busy["v"] = on
        state = tk.DISABLED if on else tk.NORMAL
        fetch_btn.configure(state=state)
        can_save = selected_index is not None and not on
        save_btn.configure(state=tk.NORMAL if can_save else tk.DISABLED)
        can_play = video_path is not None and selected_index is not None and not on
        play_btn.configure(state=tk.NORMAL if can_play else tk.DISABLED)
        stop_btn.configure(state=tk.NORMAL if playing["v"] and not on else tk.DISABLED)

    def _show_preview_image(im: Image.Image) -> None:
        nonlocal preview_photo
        max_w = max(320, preview_lbl.winfo_width() or 720)
        max_h = max(240, preview_lbl.winfo_height() or 400)
        copy = im.copy()
        copy.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)
        preview_photo = ImageTk.PhotoImage(copy)
        preview_lbl.configure(image=preview_photo, text="")
        preview_lbl.image = preview_photo

    def stop_preview() -> None:
        player.stop()
        playing["v"] = False
        if not busy["v"]:
            stop_btn.configure(state=tk.DISABLED)
            if selected_index is not None:
                play_btn.configure(state=tk.NORMAL)

    def show_segment_preview(index: int) -> None:
        if video_path is None or not (0 <= index < len(segments)):
            return
        seg = segments[index]
        stop_preview()
        im: Image.Image | None = None
        if seg.thumb_path and seg.thumb_path.is_file():
            try:
                im = Image.open(seg.thumb_path).convert("RGB")
            except OSError:
                im = None
        if im is None:
            im = extract_preview_frame(video_path, seg.start_sec + seg.duration_sec * 0.2)
        if im is not None:
            _show_preview_image(im)
        start_playback()

    def start_playback() -> None:
        if video_path is None or selected_index is None or busy["v"]:
            return
        seg = segments[selected_index]
        stop_preview()
        playing["v"] = True
        play_btn.configure(state=tk.DISABLED)
        stop_btn.configure(state=tk.NORMAL)

        def on_frame(im: Image.Image) -> None:
            safe_after(root, lambda img=im: _show_preview_image(img))

        def on_done() -> None:
            def done() -> None:
                playing["v"] = False
                if not busy["v"]:
                    play_btn.configure(state=tk.NORMAL)
                    stop_btn.configure(state=tk.DISABLED)

            safe_after(root, done)

        player.play(
            video_path,
            seg.start_sec,
            seg.end_sec,
            on_frame=on_frame,
            on_done=on_done,
            fps=10.0,
        )

    def clear_scenes() -> None:
        nonlocal selected_index, preview_photo
        stop_preview()
        selected_index = None
        preview_photo = None
        thumb_photos.clear()
        scene_frames.clear()
        for w in strip_inner.winfo_children():
            w.destroy()
        preview_lbl.configure(image="", text="구간을 클릭하면 여기에서 미리보기", bg="#1a1a1a", fg="#cccccc")
        selected_var.set("하단 구간을 클릭하세요.")
        save_btn.configure(state=tk.DISABLED)
        play_btn.configure(state=tk.DISABLED)
        stop_btn.configure(state=tk.DISABLED)

    def highlight_selection() -> None:
        for idx, fr in scene_frames.items():
            if idx == selected_index:
                fr.configure(relief=tk.SOLID, borderwidth=3, bg="#cce5ff")
            else:
                fr.configure(relief=tk.FLAT, borderwidth=1, bg=strip_inner.cget("bg"))

    def select_segment(index: int) -> None:
        nonlocal selected_index
        if not (0 <= index < len(segments)):
            return
        selected_index = index
        seg = segments[index]
        selected_var.set(_segment_label(seg))
        highlight_selection()
        if not busy["v"]:
            save_btn.configure(state=tk.NORMAL)
            play_btn.configure(state=tk.NORMAL)
        show_segment_preview(index)

    def render_scenes() -> None:
        clear_scenes()
        if not segments:
            tk.Label(strip_inner, text="장면 없음").grid(row=0, column=0, padx=8, pady=8)
            return
        for i, seg in enumerate(segments):
            cell = tk.Frame(strip_inner, padx=3, pady=3, bd=1, relief=tk.FLAT)
            cell.grid(row=0, column=i, padx=2, pady=2, sticky="n")
            scene_frames[i] = cell

            img_lbl = tk.Label(cell, text="—", anchor="center")
            img_lbl.pack()
            if seg.thumb_path and seg.thumb_path.is_file():
                try:
                    im = Image.open(seg.thumb_path)
                    im.thumbnail((240, 135))
                    photo = ImageTk.PhotoImage(im)
                    thumb_photos[i] = photo
                    img_lbl.configure(image=photo, text="")
                    img_lbl.image = photo
                except OSError:
                    pass

            tk.Label(cell, text=_segment_label(seg), font=("", 7), anchor="center").pack(pady=(1, 0))

            def _bind_click(_e: tk.Event, idx: int = i) -> None:
                select_segment(idx)

            for w in (cell, img_lbl):
                w.bind("<Button-1>", _bind_click)
                w.configure(cursor="hand2")

        if segments:
            select_segment(0)

    def save_selected() -> None:
        if video_path is None or selected_index is None:
            return
        if not (0 <= selected_index < len(segments)):
            return
        seg = segments[selected_index]
        out_dir = save_out_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        base = _safe_filename(video_title, video_id or "clip")
        out_path = out_dir / f"{base}_scene{seg.index:03d}.mp4"
        set_busy(True)
        status_var.set(f"MP4 저장 중… {out_path.name}")

        def work() -> None:
            try:
                export_segment(video_path, seg, out_path)
                msg = f"저장: {out_path}"
                ok = True
            except VideoEditError as e:
                msg = str(e)
                ok = False

            def done() -> None:
                set_busy(False)
                status_var.set(msg if ok else f"저장 실패: {msg}")
                if ok:
                    messagebox.showinfo("7_2_utubeEdit", msg)
                else:
                    messagebox.showerror("7_2_utubeEdit", msg)

            safe_after(root, done)

        threading.Thread(target=work, daemon=True).start()

    save_btn.configure(command=save_selected)
    play_btn.configure(command=start_playback)
    stop_btn.configure(command=stop_preview)

    def do_fetch() -> None:
        nonlocal video_path, video_title, video_id, segments, save_out_dir
        url = url_var.get().strip()
        if not url:
            messagebox.showwarning("7_2_utubeEdit", "YouTube 주소를 입력하세요.")
            return
        if busy["v"]:
            return
        set_busy(True)
        title_var.set("")
        clear_scenes()
        status_var.set("다운로드 중… (네트워크·영상 길이에 따라 시간이 걸릴 수 있습니다)")

        def work() -> None:
            err = ""
            ok = False
            local_video: Path | None = None
            local_title = ""
            local_vid = ""
            local_segments: list[SceneSegment] = []
            local_out = default_output_dir()
            try:
                local_out.mkdir(parents=True, exist_ok=True)
                local_video, local_title, local_vid = download_youtube(url, local_out)
                thumb_dir = local_out / local_vid / "thumbs"
                local_segments = build_segments(local_video)
                local_segments = build_scene_thumbnails(local_video, local_segments, thumb_dir)
                ok = True
            except DownloadError as e:
                err = str(e)
            except SceneDetectError as e:
                err = str(e)
            except VideoEditError as e:
                err = str(e)
            except Exception:
                err = traceback.format_exc()

            def done() -> None:
                nonlocal video_path, video_title, video_id, segments, save_out_dir
                set_busy(False)
                if ok and local_video is not None:
                    video_path = local_video
                    video_title = local_title
                    video_id = local_vid
                    segments = local_segments
                    save_out_dir = local_out
                    title_var.set(local_title)
                    status_var.set(
                        f"{len(segments)}개 구간 · 하단 클릭(미리보기) · 저장 폴더: {save_out_dir}"
                    )
                    render_scenes()
                else:
                    video_path = None
                    video_title = ""
                    video_id = ""
                    segments = []
                    status_var.set(f"실패: {err[:200]}")
                    messagebox.showerror("7_2_utubeEdit", err[:1200])

            safe_after(root, done)

        threading.Thread(target=work, daemon=True).start()

    fetch_btn.configure(command=do_fetch)
    url_ent.bind("<Return>", lambda _e: do_fetch())

    def on_close() -> None:
        stop_preview()
        _unbind_strip_wheel(None)

    bind_close(root, standalone, on_close)
    run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
