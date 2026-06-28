"""4_1_video scenevid — Tkinter GUI (산출물 compose)."""

from __future__ import annotations

import os
import threading
import tkinter as tk
import traceback
from collections.abc import Callable
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from scenevid import __version__
from scenevid.compose_overrides import (
    InsertClipSpec,
    default_overrides_path,
    is_compose_video_path,
    load_compose_overrides,
    image_stem_number,
    per_cue_images_srt_mapping,
    resolve_cue_effect_override,
    resolved_motion_effects_per_cue,
)
from scenevid.compose_render import (
    default_compose_audio,
    default_compose_srt,
    list_compose_images,
    render_compose_from_assets,
)
from scenevid.media_paths import prepend_local_ffmpeg_bin_to_os_path
from scenevid.motion import EFFECT_IDS, effects_for_compose_cues, normalize_effect
from scenevid.repo_paths import (
    default_scenevid_compose_mp4,
    default_scenevid_output_dir,
    default_srt_image_output_dir,
    default_tts_voice_output_dir,
    pick_default_compose_audio_srt,
    wisdom_repo_root,
)
from scenevid.schema import DEFAULT_OUTRO_TEXT, RenderSettings
from scenevid.srt_image_effects import (
    find_srt_image_effects_json,
    load_cue_effects_from_srt_image_json,
)
from scenevid.srt_parse import load_srt_cues_ms
from scenevid.subtitles import seconds_to_srt_ts
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


FX_LABEL_KO: dict[str, str] = {
    "pan_left": "좌팬",
    "pan_right": "우팬",
    "pan_up": "상팬",
    "pan_down": "하팬",
    "zoom_in": "줌인",
    "zoom_out": "줌아웃",
}

# 이미지 효과 팔레트·콤보박스에 노출할 ID (고정/none 제외)
FX_PALETTE_IDS: tuple[str, ...] = tuple(e for e in EFFECT_IDS if e != "none")

# videoPG: SRT 재생 순서대로 반복 (이미지가 바뀔 때만 순환)
FX_CYCLE_ORDER: tuple[str, ...] = FX_PALETTE_IDS


def _fx_disp(token: str) -> str:
    t = normalize_effect(token)
    if t == "none":
        return "고정"
    return FX_LABEL_KO.get(t, t)


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def main(*, container: tk.Misc | None = None) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_hub_destroy,
        bind_path_row_dnd,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
    )

    prepend_local_ffmpeg_bin_to_os_path()
    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"4_1_video scenevid {__version__}",
        minsize=(720, 520),
        geometry="1000x720",
    )

    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    status_var = tk.StringVar(value="대기 중")
    progress_pct_var = tk.StringVar(value="")

    log = tk.Text(root, height=5, wrap=tk.WORD, state=tk.DISABLED)
    body = ttk.Frame(root, padding=6)

    status_bar = ttk.Label(root, textvariable=status_var, padding=(8, 4))
    progress_fr = ttk.Frame(root)
    progress_bar = ttk.Progressbar(progress_fr, mode="determinate", maximum=100)

    status_bar.pack(side=tk.BOTTOM, fill=tk.X)
    progress_fr.pack(side=tk.BOTTOM, fill=tk.X, padx=8, pady=(0, 2))
    progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
    ttk.Label(progress_fr, textvariable=progress_pct_var, width=14).pack(side=tk.RIGHT)

    log.pack(side=tk.BOTTOM, fill=tk.X, expand=False, padx=8, pady=(4, 4))
    body.pack(side=tk.TOP, fill=tk.BOTH, expand=True, padx=4, pady=(4, 0))

    def log_line(msg: str) -> None:
        log.configure(state=tk.NORMAL)
        log.insert(tk.END, msg + "\n")
        log.see(tk.END)
        log.configure(state=tk.DISABLED)

    # --- compose ---
    tab_c = ttk.Frame(body, padding=10)
    tab_c.pack(fill=tk.BOTH, expand=True)
    tab_c.grid_columnconfigure(0, weight=1)

    audio_var = tk.StringVar()
    srt_var = tk.StringVar()
    images_var = tk.StringVar()
    out_var = tk.StringVar()
    outro_msg_var = tk.StringVar(value="")
    add_sub_c = tk.BooleanVar(value=True)
    w_var = tk.StringVar(value="1920")
    h_var = tk.StringVar(value="1080")
    effects_file_var = tk.StringVar()
    effect_var = tk.StringVar(value=FX_PALETTE_IDS[0])
    effect_summary_var = tk.StringVar(
        value=f"기본 효과: {FX_LABEL_KO[FX_PALETTE_IDS[0]]} · 선택 큐: —"
    )
    tl_state: dict[str, object] = {
        "ready": False,
        "root": None,
        "cues": [],
        "images": [],
        "cue_ov": {},
        "cue_fx": {},
        "img_fx": {},
        "inserts": [],
        "json_fx": {},
        "effects_json_path": "",
    }

    def _compose_assets_root() -> Path:
        try:
            from wisdom_content_paths import content_root

            root = content_root()
            if root is not None:
                return root
        except ImportError:
            pass
        return wisdom_repo_root()

    def _sync_compose_paths_from_workspace(
        *,
        audio: str | None = None,
        srt: str | None = None,
        images: str | None = None,
    ) -> None:
        mp3_dir = default_tts_voice_output_dir()
        audio_var.set(audio or str(mp3_dir / "all.mp3"))
        srt_var.set(srt or str(mp3_dir / "all.srt"))
        images_var.set(images or str(default_srt_image_output_dir()))
        out_var.set(str(default_scenevid_compose_mp4()))

    r = 0
    _compose_entries: dict[str, ttk.Entry] = {}

    def _row_labeled(
        label: str,
        var: tk.StringVar,
        pick_cmd,
        *,
        entry_key: str | None = None,
        dnd_mode: str = "path",
        dnd_ext: tuple[str, ...] = (),
        on_dnd_set: Callable[[str], None] | None = None,
    ) -> None:
        nonlocal r
        fr = ttk.Frame(tab_c)
        fr.grid(row=r, column=0, columnspan=3, sticky="ew", pady=2)
        fr.grid_columnconfigure(1, weight=1)
        ttk.Label(fr, text=label, width=14).grid(row=0, column=0, sticky="w")
        ent = ttk.Entry(fr, textvariable=var)
        ent.grid(row=0, column=1, sticky="ew", padx=(4, 6))
        if entry_key:
            _compose_entries[entry_key] = ent
        ttk.Button(fr, text="찾기…", command=pick_cmd).grid(row=0, column=2)
        bind_path_row_dnd(
            ent,
            fr,
            var,
            mode=dnd_mode,  # type: ignore[arg-type]
            extensions=dnd_ext,
            on_set=on_dnd_set,
        )
        r += 1

    def pick_audio() -> None:
        aud, _ = pick_default_compose_audio_srt()
        init = Path(audio_var.get().strip()) if audio_var.get().strip() else aud
        if init is None or not init.is_file():
            init = default_tts_voice_output_dir() / "all.mp3"
        p = filedialog.askopenfilename(
            title="MP3",
            initialdir=folder_dialog_initial(init.parent if init.is_file() else init),
            initialfile=init.name if init.is_file() else "all.mp3",
            filetypes=[("MP3", "*.mp3"), ("모든 파일", "*.*")],
        )
        if p:
            touch_workspace_from_path(p)
            _sync_compose_paths_from_workspace(audio=p)
            timeline_refresh(silent=True)

    def pick_srt() -> None:
        _aud, sr = pick_default_compose_audio_srt()
        init = Path(srt_var.get().strip()) if srt_var.get().strip() else sr
        if init is None or not init.is_file():
            init = default_tts_voice_output_dir() / "all.srt"
        p = filedialog.askopenfilename(
            title="SRT",
            initialdir=folder_dialog_initial(init.parent if init.is_file() else init),
            initialfile=init.name if init.is_file() else "all.srt",
            filetypes=[("SRT", "*.srt"), ("모든 파일", "*.*")],
        )
        if p:
            touch_workspace_from_path(p)
            _sync_compose_paths_from_workspace(srt=p)
            timeline_refresh(silent=True)

    def pick_images_dir() -> None:
        init = Path(images_var.get().strip()) if images_var.get().strip() else default_srt_image_output_dir()
        if not init.is_dir():
            init = default_srt_image_output_dir()
        p = filedialog.askdirectory(
            title="이미지·영상 폴더",
            initialdir=folder_dialog_initial(init),
        )
        if p:
            touch_workspace_from_path(p)
            try:
                from wisdom_content_paths import default_jpg_dir

                jpg = default_jpg_dir()
                picked = str(jpg if jpg is not None else p)
            except ImportError:
                picked = p
            _sync_compose_paths_from_workspace(images=picked)
            timeline_refresh(silent=True)

    def pick_out() -> None:
        init = Path(out_var.get().strip()) if out_var.get().strip() else default_scenevid_compose_mp4()
        p = filedialog.asksaveasfilename(
            title="출력 MP4",
            initialdir=folder_dialog_initial(init.parent if init.parent.is_dir() else init),
            initialfile=init.name if init.name else default_scenevid_compose_mp4().name,
            defaultextension=".mp4",
            filetypes=[("MP4", "*.mp4")],
        )
        if p:
            out_var.set(p)

    _row_labeled(
        "오디오 MP3",
        audio_var,
        pick_audio,
        dnd_mode="file",
        dnd_ext=(".mp3", ".wav", ".m4a"),
        on_dnd_set=lambda _p: timeline_refresh(silent=True),
    )
    _row_labeled(
        "자막 SRT",
        srt_var,
        pick_srt,
        dnd_mode="file",
        dnd_ext=(".srt",),
        on_dnd_set=lambda _p: timeline_refresh(silent=True),
    )
    _row_labeled(
        "이미지·영상 폴더",
        images_var,
        pick_images_dir,
        entry_key="images",
        dnd_mode="dir",
        on_dnd_set=lambda _p: timeline_refresh(silent=True),
    )
    _row_labeled(
        "출력 MP4",
        out_var,
        pick_out,
        dnd_mode="file",
        dnd_ext=(".mp4",),
    )
    _outro_hint = (
        "엔딩 메시지 (비우면 자막 없음)"
        if not DEFAULT_OUTRO_TEXT.strip()
        else f"엔딩 메시지 (비우면 「{DEFAULT_OUTRO_TEXT}」)"
    )
    _outro_fr = ttk.Frame(tab_c)
    _outro_fr.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(0, 4))
    _outro_fr.grid_columnconfigure(1, weight=1)
    ttk.Label(_outro_fr, text=_outro_hint, width=14).grid(row=0, column=0, sticky="w")
    ttk.Entry(_outro_fr, textvariable=outro_msg_var).grid(row=0, column=1, sticky="ew", padx=(4, 0))
    r += 1

    _sub_fr = ttk.Frame(tab_c)
    _sub_fr.grid(row=r, column=0, columnspan=3, sticky="w", pady=(0, 4))
    ttk.Checkbutton(_sub_fr, text="영상에 자막추가", variable=add_sub_c).pack(anchor="w")
    r += 1

    def apply_pipeline_defaults() -> None:
        """콘텐츠 루트 기준: mp3/all.*, jpg/, 루트/yyyymmdd.mp4."""
        mp3_dir = default_tts_voice_output_dir()
        mp3_dir.mkdir(parents=True, exist_ok=True)
        default_srt_image_output_dir().mkdir(parents=True, exist_ok=True)
        default_scenevid_compose_mp4().parent.mkdir(parents=True, exist_ok=True)
        _sync_compose_paths_from_workspace()

    def _fmt_ms(t0: int, t1: int) -> str:
        return f"{seconds_to_srt_ts(t0 / 1000.0)} → {seconds_to_srt_ts(t1 / 1000.0)}"

    row_tl_toolbar = ttk.Frame(tab_c)
    row_tl_toolbar.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(4, 2))
    row_tl_toolbar.grid_columnconfigure(1, weight=1)
    r += 1

    row_tl = ttk.Frame(tab_c)
    row_tl.grid(row=r, column=0, columnspan=3, sticky="nsew", pady=(0, 4))
    tab_c.grid_rowconfigure(r, weight=3)
    r += 1
    row_tl.grid_columnconfigure(0, weight=3)
    row_tl.grid_columnconfigure(2, weight=1)
    row_tl.grid_rowconfigure(0, weight=1)

    cols = ("seq", "kind", "ref", "time", "img", "fx", "hint")
    tree = ttk.Treeview(row_tl, columns=cols, show="headings", height=16, selectmode="browse")
    tree.heading("seq", text="#")
    tree.heading("kind", text="구분")
    tree.heading("ref", text="시작초")
    tree.heading("time", text="구간/길이")
    tree.heading("img", text="이미지")
    tree.heading("fx", text="효과")
    tree.heading("hint", text="비고")
    tree.column("seq", width=36, anchor="center", stretch=False)
    tree.column("kind", width=52, anchor="center", stretch=False)
    tree.column("ref", width=72, anchor="center", stretch=False)
    tree.column("time", width=180, anchor="w", stretch=False)
    tree.column("img", width=180, anchor="w", stretch=True)
    tree.column("fx", width=72, anchor="center", stretch=False)
    tree.column("hint", width=120, anchor="w", stretch=True)
    ysb = ttk.Scrollbar(row_tl, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=ysb.set)
    tree.grid(row=0, column=0, sticky="nsew")
    ysb.grid(row=0, column=1, sticky="ns")

    right = ttk.Frame(row_tl)
    right.grid(row=0, column=2, sticky="nsew", padx=(10, 0))
    ttk.Label(right, text="이미지 폴더 (더블클릭=적용)").pack(anchor="w")
    lb_fr = ttk.Frame(right)
    lb_fr.pack(fill=tk.BOTH, expand=True)
    lb_paths: list[Path] = []
    lb = tk.Listbox(lb_fr, height=12, width=28, exportselection=0)

    def _selected_palette_path() -> Path | None:
        ix = lb.curselection()
        if not ix:
            return None
        p = lb_paths[int(ix[0])]
        return p if p.is_file() else None
    lbs = ttk.Scrollbar(lb_fr, orient="vertical", command=lb.yview)
    lb.configure(yscrollcommand=lbs.set)
    lb.grid(row=0, column=0, sticky="nsew")
    lbs.grid(row=0, column=1, sticky="ns")
    lb_fr.grid_columnconfigure(0, weight=1)
    lb_fr.grid_rowconfigure(0, weight=1)

    def timeline_refresh(*, silent: bool = False) -> None:
        for x in tree.get_children():
            tree.delete(x)
        lb.delete(0, tk.END)
        lb_paths.clear()
        tl_state["ready"] = False
        root_dir = _compose_assets_root()
        sp = Path(srt_var.get().strip()) if srt_var.get().strip() else None
        imd = Path(images_var.get().strip()) if images_var.get().strip() else None
        aud = Path(audio_var.get().strip()) if audio_var.get().strip() else None
        if aud is None or not aud.is_file():
            a_def, s_def = pick_default_compose_audio_srt()
            aud = a_def
            if sp is None or not sp.is_file():
                sp = s_def
        sr = sp if sp and sp.is_file() else default_compose_srt(root_dir, aud)
        img_dir = imd if imd and imd.is_dir() else default_srt_image_output_dir()
        if not sr or not sr.is_file():
            if not silent:
                messagebox.showwarning("타임라인", "자막 SRT 파일을 지정하세요.")
            tl_state["ready"] = False
            update_effect_summary()
            return
        if not img_dir.is_dir():
            if not silent:
                messagebox.showwarning("타임라인", f"이미지 폴더가 없습니다: {img_dir}")
            tl_state["ready"] = False
            update_effect_summary()
            return
        try:
            cues = load_srt_cues_ms(sr)
            imgs = list_compose_images(img_dir)
        except (OSError, ValueError) as e:
            if not silent:
                messagebox.showerror("타임라인", str(e))
            tl_state["ready"] = False
            update_effect_summary()
            return
        if not cues:
            if not silent:
                messagebox.showwarning("타임라인", "SRT에 큐가 없습니다.")
            tl_state["ready"] = False
            update_effect_summary()
            return
        prev_root = tl_state.get("root")
        try:
            same_assets = prev_root is not None and Path(prev_root).resolve() == root_dir
        except (OSError, TypeError):
            same_assets = False
        mem_ov = dict(tl_state.get("cue_ov") or {}) if same_assets else {}
        mem_fx = dict(tl_state.get("cue_fx") or {}) if same_assets else {}
        mem_ix = dict(tl_state.get("img_fx") or {}) if same_assets else {}

        ov_file = default_overrides_path(root_dir)
        cue_o, insl, cue_fx_disk, img_fx_disk = load_compose_overrides(
            ov_file if ov_file.is_file() else None, root_dir
        )

        json_path = find_srt_image_effects_json(img_dir, root_dir, default_srt_image_output_dir())
        json_fx: dict[int, str] = {}
        json_src_msg = ""
        if json_path:
            try:
                json_fx = load_cue_effects_from_srt_image_json(json_path)
                json_src_msg = f" · JSON 모션 {len(json_fx)}개 ({json_path.name})"
            except (OSError, ValueError) as e:
                if not silent:
                    log_line(f"효과 JSON 읽기 실패 ({json_path}): {e}")

        tl_state["root"] = root_dir
        tl_state["cues"] = cues
        tl_state["images"] = imgs
        tl_state["cue_ov"] = {**dict(cue_o), **mem_ov}
        tl_state["json_fx"] = dict(json_fx)
        tl_state["effects_json_path"] = str(json_path) if json_path else ""
        # 우선순위: JSON(2_2_srtToImage) → compose_overrides.json → GUI 세션 수동 편집
        tl_state["cue_fx"] = {**json_fx, **dict(cue_fx_disk), **mem_fx}
        tl_state["img_fx"] = {**dict(img_fx_disk), **mem_ix}
        tl_state["inserts"] = list(insl)

        cue_ov: dict[int, Path | None] = tl_state["cue_ov"]
        cue_fx: dict[int, str] = dict(tl_state["cue_fx"] or {})
        json_fx_map: dict[int, str] = dict(tl_state.get("json_fx") or {})
        img_fx: dict[str, str] = dict(tl_state["img_fx"] or {})
        inserts: list[InsertClipSpec] = tl_state["inserts"]
        n = len(cues)
        map_ids = [c[0] for c in cues]
        cue_starts = [c[1] for c in cues]
        resolved = per_cue_images_srt_mapping(
            map_ids, img_dir, cue_ov, cue_start_ms=cue_starts
        )
        eff_path = Path(effects_file_var.get().strip()) if effects_file_var.get().strip() else None
        eff_lines = effects_for_compose_cues(
            n,
            effects_file=eff_path,
            images_dir=img_dir,
            default_effect=normalize_effect(effect_var.get()),
        )
        carried_fx = resolved_motion_effects_per_cue(map_ids, resolved, cue_fx, img_fx, eff_lines)
        seq = 0

        def row(seq_v: str, kind: str, ref: str, tim: str, img: str, fx: str, hint: str, iid: str) -> None:
            tree.insert("", tk.END, iid=iid, values=(seq_v, kind, ref, tim, img, fx, hint))

        for j, ins in enumerate(inserts):
            if ins.after_cue_index != 0:
                continue
            seq += 1
            row(
                str(seq),
                "삽입",
                "앞",
                f"{ins.duration_sec:.2f}초",
                ins.image.name,
                _fx_disp(ins.effect),
                (ins.subtitle or "")[:36],
                f"ins-{j}",
            )
        prev_mapped_img: Path | None = None
        for i in range(1, n + 1):
            mid, t0, t1, _txt = cues[i - 1]
            start_sec = max(0, int(t0) // 1000)
            eff_img = resolved[i - 1]
            rfx_tok = carried_fx[i - 1]
            rfx = _fx_disp(rfx_tok)
            has_ov = i in cue_ov or mid in cue_ov
            if eff_img is None:
                if has_ov and ((i in cue_ov and cue_ov[i] is None) or (mid in cue_ov and cue_ov[mid] is None)):
                    disp, hint = "(검은 화면)", "검정"
                else:
                    disp, hint = "(검은 화면)", "이미지 없음"
                prev_mapped_img = None
            else:
                disp = eff_img.name
                try:
                    eff_resolved = eff_img.resolve()
                except OSError:
                    eff_resolved = eff_img
                if i in cue_ov and cue_ov[i] is not None:
                    hint = "교체(순번)"
                    prev_mapped_img = eff_resolved
                elif mid in cue_ov and cue_ov[mid] is not None:
                    hint = "교체(SRT번호)"
                    prev_mapped_img = eff_resolved
                else:
                    img_n = image_stem_number(eff_img)
                    same_image = prev_mapped_img is not None and eff_resolved == prev_mapped_img
                    if same_image:
                        hint = "이전 유지"
                    elif img_n is not None and img_n == start_sec:
                        hint = f"SRT_{img_n:03d} 매핑 ({start_sec}초)"
                    elif img_n is not None:
                        fx_label = rfx if rfx_tok != "none" else ""
                        hint = f"{fx_label} SRT_{img_n:03d} (≤{start_sec}초)".strip()
                    else:
                        hint = "이전 유지"
                    prev_mapped_img = eff_resolved
            if mid in json_fx_map:
                hint = f"{hint} · JSON"
            seq += 1
            row(str(seq), "큐", str(start_sec), _fmt_ms(t0, t1), disp, rfx, hint, f"cue-{i}")
            for j, ins in enumerate(inserts):
                if ins.after_cue_index != i:
                    continue
                seq += 1
                row(
                    str(seq),
                    "삽입",
                    f"{i}뒤",
                    f"{ins.duration_sec:.2f}초",
                    ins.image.name,
                    _fx_disp(ins.effect),
                    (ins.subtitle or "")[:36],
                    f"ins-{j}",
                )

        for p in imgs:
            lb.insert(tk.END, p.name)
            lb_paths.append(p)

        tl_state["ready"] = True
        status_var.set(
            f"타임라인 {seq}행 · SRT {n}큐 · 이미지 {len(imgs)}개 (시작초→SRT_NNN 매핑){json_src_msg}"
        )
        update_effect_summary()

    _images_path_refresh_job: list[str | None] = [None]

    def _refresh_timeline_if_images_dir_valid() -> None:
        p = images_var.get().strip()
        if not p:
            return
        try:
            if not Path(p).is_dir():
                return
        except OSError:
            return
        timeline_refresh(silent=True)

    def _schedule_timeline_refresh_on_images_path() -> None:
        job = _images_path_refresh_job[0]
        if job is not None:
            try:
                root.after_cancel(job)
            except tk.TclError:
                pass

        def _run() -> None:
            _images_path_refresh_job[0] = None
            _refresh_timeline_if_images_dir_valid()

        _images_path_refresh_job[0] = root.after(350, _run)

    def _bind_images_folder_auto_refresh() -> None:
        ent = _compose_entries.get("images")
        if ent is None:
            return
        ent.bind("<FocusOut>", lambda _e: _refresh_timeline_if_images_dir_valid())
        ent.bind("<Return>", lambda _e: _refresh_timeline_if_images_dir_valid())
        ent.bind("<KP_Enter>", lambda _e: _refresh_timeline_if_images_dir_valid())
        images_var.trace_add("write", lambda *_a: _schedule_timeline_refresh_on_images_path())

    _bind_images_folder_auto_refresh()

    def _selected_cue_no() -> int | None:
        sel = tree.selection()
        if not sel:
            return None
        iid = sel[0]
        if not str(iid).startswith("cue-"):
            return None
        return int(str(iid).split("-", 1)[1])

    def update_effect_summary() -> None:
        if not tl_state.get("ready"):
            effect_summary_var.set("기본 효과: " + _fx_disp(effect_var.get()) + " · 타임라인을 불러오세요.")
            return
        cues_l: list = tl_state["cues"]  # type: ignore[assignment]
        n2 = len(cues_l)
        img_dir2 = Path(images_var.get().strip()) if images_var.get().strip() else Path(tl_state["root"] or ".") / "images"
        eff_path2 = Path(effects_file_var.get().strip()) if effects_file_var.get().strip() else None
        eff_lines2 = effects_for_compose_cues(
            n2,
            effects_file=eff_path2,
            images_dir=img_dir2,
            default_effect=normalize_effect(effect_var.get()),
        )
        cue_fx2: dict[int, str] = dict(tl_state.get("cue_fx") or {})
        img_fx2: dict[str, str] = dict(tl_state.get("img_fx") or {})
        cue_ov2: dict[int, Path | None] = dict(tl_state.get("cue_ov") or {})
        base = _fx_disp(effect_var.get())
        cno = _selected_cue_no()
        if cno is None:
            effect_summary_var.set(f"기본(줄별 파일 없을 때): {base} · 선택 큐: 없음 (행을 클릭)")
            return
        mid = cues_l[cno - 1][0]
        map_ids2 = [c[0] for c in cues_l]
        cue_starts2 = [c[1] for c in cues_l]
        res2 = per_cue_images_srt_mapping(
            map_ids2, img_dir2, cue_ov2, cue_start_ms=cue_starts2
        )
        imgp = res2[cno - 1]
        carried2 = resolved_motion_effects_per_cue(map_ids2, res2, cue_fx2, img_fx2, eff_lines2)
        ov = resolve_cue_effect_override(cno, mid, cue_fx2)
        if ov is not None:
            tok0 = normalize_effect(ov)
        elif imgp is not None:
            ik = str(imgp.resolve())
            tok0 = normalize_effect(img_fx2[ik]) if ik in img_fx2 else normalize_effect(eff_lines2[cno - 1])
        else:
            tok0 = normalize_effect(eff_lines2[cno - 1])
        tok = carried2[cno - 1]
        json_fx2: dict[int, str] = dict(tl_state.get("json_fx") or {})
        if (
            mid in json_fx2
            and ov is not None
            and normalize_effect(ov) == normalize_effect(json_fx2[mid])
        ):
            src = "JSON 모션"
        elif ov is not None:
            src = "큐 지정"
        elif imgp is not None and tok != tok0:
            src = "동일 이미지 연속(효과 유지)"
        elif imgp is not None and str(imgp.resolve()) in img_fx2:
            src = "이미지 파일"
        else:
            src = "줄별/기본"
        effect_var.set(tok)
        effect_summary_var.set(f"기본: {base} · 큐 #{cno}: {_fx_disp(tok)} [{tok}] · 출처: {src}")

    def on_tree_pick_image(_e=None) -> None:
        apply_palette_image()

    def apply_palette_image() -> None:
        cue_no = _selected_cue_no()
        if cue_no is None:
            messagebox.showinfo("적용", "타임라인에서 「큐」행을 선택한 뒤 이미지를 더블클릭하세요.")
            return
        ix = lb.curselection()
        if not ix:
            messagebox.showinfo("적용", "오른쪽 목록에서 이미지를 선택하세요.")
            return
        p = lb_paths[int(ix[0])]
        if not p.is_file():
            messagebox.showerror("적용", f"파일 없음: {p}")
            return
        tl_state["cue_ov"][cue_no] = p.resolve()
        timeline_refresh(silent=True)

    ttk.Button(
        row_tl_toolbar,
        text="타임라인 새로고침",
        command=lambda: timeline_refresh(silent=False),
    ).grid(row=0, column=0, sticky="w")
    ttk.Label(row_tl_toolbar, textvariable=effect_summary_var, wraplength=720, justify="left").grid(
        row=0, column=1, sticky="ew", padx=(12, 0)
    )

    tree.bind("<Double-1>", on_tree_pick_image)
    lb.bind("<Double-1>", lambda _e: apply_palette_image())
    tree.bind("<<TreeviewSelect>>", lambda _e: update_effect_summary())

    def apply_image_random_effects() -> None:
        """videoPG: 이미지가 바뀔 때만 좌팬→우팬→상팬→하팬→줌인→줌아웃 순환 (큐마다 변경 안 함)."""
        if not tl_state.get("ready"):
            messagebox.showwarning("이미지랜덤효과", "먼저 타임라인을 불러오세요 (자막·이미지 경로 확인).")
            return
        cues_l: list = tl_state.get("cues") or []
        if not cues_l:
            return
        img_dir2 = Path(images_var.get().strip()) if images_var.get().strip() else Path(tl_state["root"] or ".")
        map_ids2 = [c[0] for c in cues_l]
        cue_starts_rand = [c[1] for c in cues_l]
        cue_ov2: dict[int, Path | None] = dict(tl_state.get("cue_ov") or {})
        resolved2 = per_cue_images_srt_mapping(
            map_ids2, img_dir2, cue_ov2, cue_start_ms=cue_starts_rand
        )

        base_fx = dict(tl_state.get("json_fx") or {})
        new_fx: dict[int, str] = dict(base_fx)
        seq = FX_CYCLE_ORDER
        cycle_i = 0
        prev_key: str | None = None

        for i, img in enumerate(resolved2):
            if img is None or is_compose_video_path(img):
                continue
            try:
                key = str(img.resolve())
            except OSError:
                key = str(img)
            if prev_key is not None and key == prev_key:
                continue
            e = normalize_effect(seq[cycle_i % len(seq)])
            cno = i + 1
            mid = map_ids2[i]
            new_fx[cno] = e
            new_fx[mid] = e
            cycle_i += 1
            prev_key = key

        tl_state["cue_fx"] = new_fx
        timeline_refresh(silent=True)
        update_effect_summary()

    row_btns = ttk.Frame(tab_c)
    row_btns.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(2, 4))
    row_btns.grid_columnconfigure(0, weight=1)
    r += 1

    grp_fx = ttk.LabelFrame(row_btns, text="이미지 모션", padding=6)
    grp_fx.grid(row=0, column=0, sticky="nsew", padx=(0, 8))

    btns_fx = ttk.Frame(grp_fx)
    btns_fx.pack(anchor="w", fill=tk.X)

    def _make_pick_effect(eid: str):
        def _pick() -> None:
            eff = normalize_effect(eid)
            pal = _selected_palette_path()
            if pal is not None:
                if is_compose_video_path(pal):
                    messagebox.showinfo("이미지 효과", "MP4 영상 구간에는 Ken Burns 효과를 적용할 수 없습니다.")
                    return
                tl_state["img_fx"][str(pal.resolve())] = eff
            else:
                cno = _selected_cue_no()
                if cno is not None:
                    tl_state["cue_fx"][cno] = eff
                else:
                    effect_var.set(eid)
            update_effect_summary()
            if tl_state.get("ready"):
                timeline_refresh(silent=True)

        return _pick

    ttk.Button(btns_fx, text="고정", command=_make_pick_effect("none"), width=8).pack(
        side=tk.LEFT, padx=2
    )
    for ei in FX_PALETTE_IDS:
        ttk.Button(btns_fx, text=FX_LABEL_KO.get(ei, ei), command=_make_pick_effect(ei), width=8).pack(
            side=tk.LEFT, padx=2
        )
    ttk.Button(btns_fx, text="이미지랜덤효과", command=apply_image_random_effects).pack(
        side=tk.LEFT, padx=(8, 2)
    )

    grp_out = ttk.LabelFrame(row_btns, text="출력", padding=6)
    grp_out.grid(row=0, column=1, sticky="nw", padx=(0, 8))
    out_row = ttk.Frame(grp_out)
    out_row.pack(anchor="w")
    ttk.Label(out_row, text="가로").grid(row=0, column=0, padx=(0, 4))
    ttk.Entry(out_row, textvariable=w_var, width=7).grid(row=0, column=1, padx=(0, 12))
    ttk.Label(out_row, text="세로").grid(row=0, column=2, padx=(0, 4))
    ttk.Entry(out_row, textvariable=h_var, width=7).grid(row=0, column=3)

    grp_run = ttk.LabelFrame(row_btns, text="합성", padding=6)
    grp_run.grid(row=0, column=2, sticky="nw")
    btn_compose = ttk.Button(grp_run, text="동영상 만들기")

    def run_compose_bg(progress_cb=None):
        prepend_local_ffmpeg_bin_to_os_path()
        root_dir = _compose_assets_root()
        ap = Path(audio_var.get().strip()) if audio_var.get().strip() else None
        sp = Path(srt_var.get().strip()) if srt_var.get().strip() else None
        imd = Path(images_var.get().strip()) if images_var.get().strip() else None
        outp = Path(out_var.get().strip()) if out_var.get().strip() else None

        aud = ap if ap and ap.is_file() else None
        sr = sp if sp and sp.is_file() else None
        if aud is None:
            a_def, s_def = pick_default_compose_audio_srt()
            aud = a_def
            if sr is None:
                sr = s_def
        if aud is None or not aud.is_file():
            aud = default_compose_audio(root_dir)
        if aud is None or not aud.is_file():
            raise FileNotFoundError("MP3를 찾을 수 없습니다.")
        if sr is None or not sr.is_file():
            sr = default_compose_srt(root_dir, aud)
        if sr is None or not sr.is_file():
            raise FileNotFoundError("SRT를 찾을 수 없습니다.")

        img_dir: Path | None = imd if imd and imd.is_dir() else None
        if img_dir is None:
            cand = default_srt_image_output_dir()
            img_dir = cand if cand.is_dir() else root_dir / "images"
        if not img_dir.is_dir():
            raise FileNotFoundError(f"이미지 폴더 없음: {img_dir}")
        ar_root = wisdom_repo_root()
        # videoPG: 산출물은 4_1_video/output (Temp 아님)
        out_p = outp if outp else default_scenevid_compose_mp4()
        if not out_p.is_absolute():
            out_p = default_scenevid_compose_mp4()
        try:
            out_resolved = out_p.resolve()
            temp_root = Path(os.environ.get("TEMP", "")).resolve()
            if temp_root.parts and out_resolved.is_relative_to(temp_root):
                out_p = default_scenevid_compose_mp4()
        except (ValueError, OSError):
            pass
        out_p.parent.mkdir(parents=True, exist_ok=True)
        w = int(w_var.get().strip() or "1920")
        h = int(h_var.get().strip() or "1080")
        st = RenderSettings(
            width=w,
            height=h,
            outro_text=outro_msg_var.get().strip(),
        )
        eff_path = Path(effects_file_var.get().strip()) if effects_file_var.get().strip() else None
        if bool(tl_state.get("ready")):
            fp = render_compose_from_assets(
                audio_mp3=aud,
                srt_path=sr,
                images_dir=img_dir,
                out_mp4=out_p,
                settings=st,
                burn_subtitles=bool(add_sub_c.get()),
                default_effect=normalize_effect(effect_var.get()),
                effects_file=eff_path,
                assets_root=ar_root,
                overrides_path=None,
                override_cue_images=dict(tl_state["cue_ov"]),
                override_inserts=list(tl_state["inserts"]),
                override_cue_effects=dict(tl_state.get("cue_fx") or {}),
                override_image_effects=dict(tl_state.get("img_fx") or {}),
                progress=progress_cb,
            )
        else:
            fp = render_compose_from_assets(
                audio_mp3=aud,
                srt_path=sr,
                images_dir=img_dir,
                out_mp4=out_p,
                settings=st,
                burn_subtitles=bool(add_sub_c.get()),
                default_effect=normalize_effect(effect_var.get()),
                effects_file=eff_path,
                assets_root=ar_root,
                overrides_path=None,
                override_cue_images=None,
                override_inserts=None,
                progress=progress_cb,
            )
        return fp

    def on_compose() -> None:
        btn_compose.configure(state=tk.DISABLED)
        progress_bar["value"] = 0
        progress_pct_var.set("0%")

        def report_progress(done: int, total: int, msg: str) -> None:
            mx = max(int(total), 1)
            pct = min(100, int(100.0 * float(done) / float(mx)))

            def ui() -> None:
                progress_bar["maximum"] = mx
                progress_bar["value"] = min(int(done), mx)
                progress_pct_var.set(f"{pct}%")
                status_var.set(msg[:240])

            safe_after(root, ui)

        def work() -> None:
            try:
                fp = run_compose_bg(progress_cb=report_progress)

                def ok() -> None:
                    btn_compose.configure(state=tk.NORMAL)
                    mx = max(progress_bar["maximum"], 1)
                    progress_bar["value"] = mx
                    progress_pct_var.set("100%")
                    status_var.set(f"완료: {fp}")
                    log_line(f"합성 완료: {fp}")
                    safe_messagebox(root, "showinfo", "4_1_video", f"완료\n{fp}")

                safe_after(root, ok)
            except Exception as e:
                tb = traceback.format_exc()

                def err() -> None:
                    btn_compose.configure(state=tk.NORMAL)
                    progress_bar["value"] = 0
                    progress_pct_var.set("0%")
                    status_var.set("오류")
                    log_line(tb)
                    safe_messagebox(root, "showerror", "4_1_video", str(e))

                safe_after(root, err)

        threading.Thread(target=work, daemon=True).start()

    btn_compose.configure(command=on_compose)
    btn_compose.pack(anchor="w")

    apply_pipeline_defaults()
    timeline_refresh(silent=True)

    if not standalone:
        bind_hub_destroy(root, lambda: None)

    run_mainloop(root, standalone)
