# -*- coding: utf-8 -*-
"""2_1_ttsToVoice: ElevenLabs TTS 블록 → 파트별 MP3·SRT·JSON 합성 + 수동 `all` 병합.

- 각 파트(`1.{}`, `2.{}` …)별로 `part01`, `part02` … 이름으로 MP3·SRT·JSON 을 생성합니다.
- 파트·`all.mp3` 병합은 ffmpeg concat + libmp3lame 재인코딩(128k/44.1kHz/mono) 우선, 실패 시 바이너리 폴백입니다.
- 통합 `all.*` 파일은 **별도 버튼**으로 출력 폴더의 기존 `part*.` 파일만 읽어 생성합니다.
- 출력 폴더는 GUI에서 지정합니다 (기본 ``2_1_ttsToVoice/output/``).
- 입력은 붙여넣기 또는 **입력 폴더**의 ``*.txt`` (기본 ``1_2_textToTts/output/``).
- 자막 구간 길이는 세그먼트 MP3를 ffprobe 한 값을 사용하고, 파트 전체 길이에 맞게 미세 보정합니다.
- 문장부호로 끝나지 않은 줄은 다음 줄 TTS를 쉼 없이 붙여 한 API로 이어 읽습니다.
- ``[breathes]``·``[short pause]`` 등은 ElevenLabs SSML ``<break>`` 로 변환해 호흡·쉼을 넣습니다.
"""

from __future__ import annotations

from collections.abc import Callable
import json
import re
import threading
import traceback
import tkinter as tk
from collections import OrderedDict
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk

from elsub import __version__
from elsub.input_loader import load_tts_text_from_dir
from elsub.elevenlabs_client import (
    concat_mp3_files,
    concat_mp3_files_binary_from_paths,
    concat_mp3_files_ffmpeg,
    prepend_silence_mp3,
    strip_tts_tags,
    synthesize_mp3,
)
from elsub.media_probe import ffprobe_duration_sec
from elsub.parser import CaptionLine, parse_knowledgetts_block
from elsub.settings import (
    PRESET_CONFIG_FILENAMES,
    PROJECT_DIRNAME,
    config_dist_dir,
    config_file_path,
    copy_bundled_example_if_needed,
    default_input_dir,
    load_gui_settings,
    load_settings,
    resolve_output_dir,
    resolve_preset_config,
    save_gui_settings,
    set_config_path_override,
)
from wisdom_workspace import (
    folder_dialog_initial,
    touch_workspace_from_path,
    workspace_module_output,
)
from elsub.srt_gen import build_srt_from_durations, estimate_duration_ms, merge_srt_files
from elsub.tts_merge import (
    group_entries_for_synthesis,
    leading_pause_ms,
    merge_group_tts,
    remove_leading_pause_tags,
    split_duration_ms,
    tts_synthesis_weight,
)


_PART_MP3 = re.compile(r"^part(\d+)\.mp3$", re.IGNORECASE)


def _font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _group_by_part(entries: list[CaptionLine]) -> "OrderedDict[str, list[CaptionLine]]":
    groups: "OrderedDict[str, list[CaptionLine]]" = OrderedDict()
    for e in entries:
        groups.setdefault(e.part_id, []).append(e)
    return groups


def _part_label(part_id: str, max_pad: int) -> str:
    try:
        return f"part{int(part_id):0{max_pad}d}"
    except ValueError:
        return f"part{part_id}"


def discover_part_mp3_paths(output_dir: Path) -> list[Path]:
    """`part01.mp3`, `part02.mp3`, … 를 숫자 순으로 반환합니다."""
    found: list[tuple[int, Path]] = []
    for p in output_dir.iterdir():
        if not p.is_file():
            continue
        m = _PART_MP3.match(p.name)
        if m:
            found.append((int(m.group(1)), p))
    found.sort(key=lambda x: x[0])
    return [x[1] for x in found]


def build_merged_json_from_part_files(
    part_mp3_paths: list[Path],
    all_mp3: Path,
    all_srt: Path,
    *,
    all_merge_method: str = "",
) -> dict:
    """`partNN.json` 을 읽어 통합 JSON 문서를 만듭니다."""
    parts_meta: list[dict] = []
    all_segments: list[dict] = []
    cum_ms = 0
    model_id = ""

    for mp in part_mp3_paths:
        jp = mp.with_suffix(".json")
        raw = json.loads(jp.read_text(encoding="utf-8"))
        if not model_id:
            model_id = str(raw.get("model_id") or "").strip()
        pid = str(raw.get("part_id", ""))
        segs = raw.get("segments") or []
        if not isinstance(segs, list):
            segs = []
        parts_meta.append(
            {
                "part_id": pid,
                "lines": len(segs),
                "mp3": str(raw.get("part_mp3") or str(mp.resolve())),
                "srt": str(raw.get("part_srt") or str(mp.with_suffix(".srt").resolve())),
                "json": str(jp.resolve()),
                "merge_method": str(raw.get("merge_method") or ""),
            }
        )
        for s in segs:
            if not isinstance(s, dict):
                continue
            row = dict(s)
            row["part_id"] = pid
            sm = int(row.get("start_ms_estimate") or 0)
            em = int(row.get("end_ms_estimate") or 0)
            row["start_ms_estimate"] = cum_ms + sm
            row["end_ms_estimate"] = cum_ms + em
            all_segments.append(row)
        dur = int(raw.get("duration_ms_estimate") or 0)
        cum_ms += dur

    total_from_probe = 0
    probe_parts_ok = True
    for mp in part_mp3_paths:
        try:
            total_from_probe += int(round(ffprobe_duration_sec(mp) * 1000))
        except Exception:
            probe_parts_ok = False
            break
    if not probe_parts_ok or total_from_probe <= 0:
        total_from_probe = cum_ms

    return {
        "merged_mp3": str(all_mp3.resolve()),
        "subtitle_srt": str(all_srt.resolve()),
        "model_id": model_id or "eleven_multilingual_v2",
        "merge_method": all_merge_method or "manual: part*.json 기준 병합",
        "total_duration_ms_estimate": total_from_probe,
        "parts": parts_meta,
        "segments": all_segments,
    }


def _resolve_dir(raw: str, fallback: Path) -> Path:
    s = raw.strip()
    if s:
        p = Path(s).expanduser().resolve()
        if p.is_dir():
            return p
    return fallback.resolve()


def _coerce_saved_output(gui_cfg: dict[str, str], in_default: Path) -> Path:
    """저장 출력 경로가 없으면 입력(기본 mp3)과 동일."""
    out_saved = gui_cfg.get("output_dir", "").strip()
    if out_saved:
        p = Path(out_saved).expanduser()
        try:
            if p.is_dir():
                return p.resolve()
        except OSError:
            pass
    return in_default.resolve()


def main(
    *,
    container: tk.Misc | None = None,
    config_file_picker: bool = False,
    config_preset_selector: bool = True,
    window_title: str | None = None,
) -> None:
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_file_drop,
        bind_hub_destroy,
        bind_path_row_dnd,
        run_mainloop,
        safe_after,
        safe_messagebox,
        tk_host,
    )

    copy_bundled_example_if_needed()
    gui_cfg = load_gui_settings()
    if config_file_picker:
        if gui_cfg.get("config_file"):
            set_config_path_override(gui_cfg["config_file"])
    elif config_preset_selector:
        preset_initial = resolve_preset_config(gui_cfg.get("config_file"))
        set_config_path_override(preset_initial)
    elif gui_cfg.get("config_file"):
        set_config_path_override(gui_cfg["config_file"])
    cfg_path = config_file_path()
    if gui_cfg.get("input_dir"):
        touch_workspace_from_path(gui_cfg["input_dir"])
    in_default = _resolve_dir(gui_cfg.get("input_dir", ""), default_input_dir())
    out_default = _coerce_saved_output(gui_cfg, in_default)

    root, standalone = tk_host(container)
    title = window_title or f"2_1_ttsToVoice {__version__}"
    apply_window_chrome(
        root,
        standalone,
        title=title,
        minsize=(640, 620),
        geometry="820x700",
    )
    fam, sz = _font()
    root.option_add("*Font", (fam, sz))

    status = tk.StringVar()
    in_var = tk.StringVar(value=str(in_default))
    out_var = tk.StringVar(value=str(out_default))

    def _sync_output_to_workspace() -> None:
        """입력 폴더 지정 시 출력 폴더를 동일 경로로 맞춤 (출력은 이후 수동 변경 가능)."""
        inp = in_var.get().strip()
        if inp and Path(inp).is_dir():
            out_var.set(inp)
            return
        try:
            from wisdom_content_paths import default_mp3_dir

            mp3 = default_mp3_dir()
            if mp3 is not None:
                out_var.set(str(mp3))
                return
        except ImportError:
            pass
        ws_out = workspace_module_output(PROJECT_DIRNAME)
        if ws_out is not None:
            out_var.set(str(ws_out))

    cfg_label_var = tk.StringVar(value=f"API 키·Voice ID·모델: {cfg_path}")

    def refresh_cfg_status() -> None:
        p = config_file_path()
        cfg_label_var.set(f"API 키·Voice ID·모델: {p}")
        if p.is_file():
            status.set("대기 중")
        else:
            status.set(f"{p.name} 없음 — API 키·voice_id 등을 설정하세요.")

    if cfg_path.is_file():
        status.set("대기 중")
    else:
        status.set(f"{cfg_path.name} 없음 — API 키·voice_id 등을 설정하세요.")

    frm = ttk.Frame(root, padding=10)
    if standalone:
        frm.grid(row=0, column=0, sticky="nsew")
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)
    else:
        frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)

    def row_dir(
        label: str,
        var: tk.StringVar,
        row: int,
        *,
        pick_title: str,
        pick_fallback: Path,
        on_focus_out: Callable[[], None] | None = None,
    ) -> None:
        ttk.Label(frm, text=label).grid(row=row, column=0, sticky="w", pady=(0, 2))
        rf = ttk.Frame(frm)
        rf.grid(row=row + 1, column=0, sticky="ew", pady=(0, 8))
        rf.grid_columnconfigure(0, weight=1)
        ent = ttk.Entry(rf, textvariable=var)
        ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        if on_focus_out is not None:
            ent.bind("<FocusOut>", lambda _e: on_focus_out())

        def pick() -> None:
            initial = var.get().strip()
            init_dir = folder_dialog_initial(
                Path(initial) if initial and Path(initial).is_dir() else pick_fallback,
            )
            chosen = filedialog.askdirectory(title=pick_title, initialdir=init_dir)
            if chosen:
                touch_workspace_from_path(chosen)
                var.set(chosen)
                if var is in_var:
                    _sync_output_to_workspace()

        ttk.Button(rf, text="찾아보기…", command=pick).grid(row=0, column=1)
        bind_path_row_dnd(
            ent,
            rf,
            var,
            mode="dir",
            on_set=(lambda _p: on_focus_out()) if on_focus_out else None,
        )

    def on_input_path_committed() -> None:
        p = in_var.get().strip()
        if p and Path(p).is_dir():
            touch_workspace_from_path(p)
            _sync_output_to_workspace()

    row_dir(
        "입력 폴더 (*.txt)",
        in_var,
        0,
        pick_title="TTS 텍스트 입력 폴더",
        pick_fallback=in_default,
        on_focus_out=on_input_path_committed,
    )
    row_dir(
        "출력 폴더 (MP3·SRT·JSON)",
        out_var,
        2,
        pick_title="TTS 음성 출력 폴더",
        pick_fallback=out_default,
    )

    cfg_var = tk.StringVar(value=str(cfg_path))
    preset_name = (
        cfg_path.name
        if cfg_path.name in PRESET_CONFIG_FILENAMES
        else PRESET_CONFIG_FILENAMES[0]
    )
    cfg_choice_var = tk.StringVar(value=preset_name)
    next_row = 4

    if config_preset_selector and not config_file_picker:
        ttk.Label(frm, text="Voice ID 설정 파일").grid(
            row=next_row, column=0, sticky="w", pady=(0, 2),
        )
        cfg_fr = ttk.Frame(frm)
        cfg_fr.grid(row=next_row + 1, column=0, sticky="ew", pady=(0, 8))
        cfg_fr.grid_columnconfigure(0, weight=1)

        def apply_preset(_event: object | None = None) -> None:
            name = cfg_choice_var.get().strip()
            if name not in PRESET_CONFIG_FILENAMES:
                return
            p = config_dist_dir() / name
            cfg_var.set(str(p))
            set_config_path_override(p)
            refresh_cfg_status()
            persist_dirs()

        cfg_cb = ttk.Combobox(
            cfg_fr,
            textvariable=cfg_choice_var,
            values=list(PRESET_CONFIG_FILENAMES),
            state="readonly",
        )
        cfg_cb.grid(row=0, column=0, sticky="ew")
        cfg_cb.bind("<<ComboboxSelected>>", apply_preset)
        next_row += 2

    if config_file_picker:
        ttk.Label(frm, text="Voice ID 설정 파일 (JSON)").grid(
            row=next_row, column=0, sticky="w", pady=(0, 2),
        )
        cfg_fr = ttk.Frame(frm)
        cfg_fr.grid(row=next_row + 1, column=0, sticky="ew", pady=(0, 8))
        cfg_fr.grid_columnconfigure(0, weight=1)
        cfg_ent = ttk.Entry(cfg_fr, textvariable=cfg_var)
        cfg_ent.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        def pick_config() -> None:
            initial = cfg_var.get().strip()
            init_path = Path(initial) if initial else cfg_path.parent
            init_dir = init_path.parent if init_path.is_file() else init_path
            chosen = filedialog.askopenfilename(
                title="Voice ID 설정 파일 (JSON)",
                initialdir=str(folder_dialog_initial(init_dir)),
                filetypes=[("JSON", "*.json"), ("모든 파일", "*.*")],
            )
            if chosen:
                cfg_var.set(chosen)
                set_config_path_override(chosen)
                refresh_cfg_status()

        def on_config_committed() -> None:
            p = cfg_var.get().strip()
            if p:
                set_config_path_override(p)
                refresh_cfg_status()

        cfg_ent.bind("<FocusOut>", lambda _e: on_config_committed())
        ttk.Button(cfg_fr, text="찾아보기…", command=pick_config).grid(row=0, column=1)
        bind_path_row_dnd(
            cfg_ent,
            cfg_fr,
            cfg_var,
            mode="file",
            extensions=(".json",),
            on_set=lambda _p: on_config_committed(),
        )
        next_row += 2

    ttk.Label(
        frm,
        textvariable=cfg_label_var,
        foreground="gray",
        justify="left",
    ).grid(row=next_row, column=0, sticky="w", pady=(0, 4))

    head_fr = ttk.Frame(frm)
    head_fr.grid(row=next_row + 1, column=0, sticky="ew", pady=(0, 4))
    ttk.Label(head_fr, text="TTS 변환 결과 (붙여넣기 또는 입력 폴더 불러오기)").pack(side=tk.LEFT)

    def persist_dirs() -> None:
        save_gui_settings(
            input_dir=in_var.get(),
            output_dir=out_var.get(),
            config_file=cfg_var.get()
            if (config_file_picker or config_preset_selector)
            else "",
        )

    def load_from_input_dir(*, quiet: bool = False) -> bool:
        folder = _resolve_dir(in_var.get(), default_input_dir())
        try:
            text = load_tts_text_from_dir(folder)
        except FileNotFoundError as e:
            if not quiet:
                messagebox.showerror("입력 폴더", str(e))
            return False
        txt.delete("1.0", tk.END)
        txt.insert("1.0", text)
        touch_workspace_from_path(folder)
        _sync_output_to_workspace()
        persist_dirs()
        status.set(f"입력 불러옴: {folder} ({len(list(folder.glob('*.txt')))}개 txt)")
        return True

    ttk.Button(head_fr, text="입력 폴더 불러오기", command=load_from_input_dir).pack(side=tk.RIGHT)

    txt = scrolledtext.ScrolledText(frm, height=16, wrap="word", font=(fam, sz))
    txt.grid(row=next_row + 2, column=0, sticky="nsew", pady=(4, 6))
    frm.grid_rowconfigure(next_row + 2, weight=1)

    def _on_tts_text_drop(paths: list[str]) -> None:
        p = Path(paths[0])
        if p.is_dir():
            in_var.set(str(p))
            touch_workspace_from_path(p)
            _sync_output_to_workspace()
            load_from_input_dir(quiet=True)
            return
        if p.is_file() and p.suffix.lower() == ".txt":
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = p.read_text(encoding="cp949", errors="replace")
            txt.delete("1.0", tk.END)
            txt.insert("1.0", content)
            touch_workspace_from_path(p.parent)
            status.set(f"파일 불러옴: {p.name}")

    bind_file_drop(txt, _on_tts_text_drop)

    log_fr = ttk.LabelFrame(frm, text="실행 로그", padding=4)
    log_fr.grid(row=next_row + 3, column=0, sticky="nsew", pady=(0, 6))
    log_fr.grid_rowconfigure(0, weight=1)
    log_fr.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(next_row + 3, weight=0)
    log = scrolledtext.ScrolledText(log_fr, height=8, wrap="word", font=(fam, max(9, sz - 1)))

    def log_line(s: str) -> None:
        log.insert(tk.END, s.rstrip() + "\n")
        log.see(tk.END)

    log.grid(row=0, column=0, sticky="nsew")

    busy = {"v": False}
    gen_cancel = threading.Event()

    def _output_dir() -> Path:
        return _resolve_dir(out_var.get(), resolve_output_dir())

    def _finalize_part(
        *,
        part_lbl: str,
        part_entries: list,
        part_seg_paths: list[Path],
        part_seg_blobs: list[bytes],
        seg_durs_ms: list[int],
        line_segment_mp3: list[str],
        model: str,
        output_dir: Path,
    ) -> None:
        part_mp3 = output_dir / f"{part_lbl}.mp3"
        part_srt = part_mp3.with_suffix(".srt")
        part_json = part_mp3.with_suffix(".json")

        part_merge_note = ""
        try:
            concat_mp3_files_ffmpeg(part_seg_paths, part_mp3)
            part_merge_note = "ffmpeg-reencode"
        except Exception as ff_err:
            concat_mp3_files(part_seg_blobs, str(part_mp3))
            part_merge_note = f"binary-fallback ({ff_err})"

        try:
            merged_ms = int(round(ffprobe_duration_sec(part_mp3) * 1000))
        except Exception:
            merged_ms = sum(seg_durs_ms)
        ssum = sum(seg_durs_ms)
        if merged_ms > 0 and ssum > 0 and merged_ms != ssum:
            scaled = [max(1, int(round(d * merged_ms / ssum))) for d in seg_durs_ms]
            drift = merged_ms - sum(scaled)
            scaled[-1] = max(1, scaled[-1] + drift)
            seg_durs_ms = scaled

        part_cur_ms = 0
        part_seg_json: list[dict] = []
        for i, (e, dur) in enumerate(zip(part_entries, seg_durs_ms), start=1):
            part_seg_json.append(
                {
                    "index": i,
                    "caption_id": e.caption_id,
                    "original": e.original,
                    "tts": e.tts,
                    "segment_mp3": line_segment_mp3[i - 1],
                    "duration_ms_estimate": dur,
                    "start_ms_estimate": part_cur_ms,
                    "end_ms_estimate": part_cur_ms + dur,
                }
            )
            part_cur_ms += dur

        part_srt_body, _, _ = build_srt_from_durations(
            [(e.original, d) for e, d in zip(part_entries, seg_durs_ms)]
        )
        part_srt.write_text(part_srt_body, encoding="utf-8")

        part_doc = {
            "part_id": part_entries[0].part_id if part_entries else "",
            "part_mp3": str(part_mp3.resolve()),
            "part_srt": str(part_srt.resolve()),
            "model_id": model,
            "merge_method": part_merge_note,
            "segment_count": len(part_seg_paths),
            "duration_ms_estimate": part_cur_ms,
            "segments": part_seg_json,
        }
        part_json.write_text(
            json.dumps(part_doc, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        def log_part(p: str = part_lbl, m: str = part_merge_note) -> None:
            log_line(f"[{p}] mp3/srt/json 생성 완료 (mp3 병합: {m})")

        safe_after(root, log_part)

    def stop_gen() -> None:
        if busy["v"]:
            gen_cancel.set()
            status.set("중지 요청… (현재 세그먼트 완료 후 멈춤)")

    def run_gen() -> None:
        if busy["v"]:
            return
        persist_dirs()
        s = load_settings()
        key = s.elevenlabs_api_key.strip()
        vid = s.voice_id.strip()
        model = (s.model_id or "eleven_multilingual_v2").strip()

        if not key:
            messagebox.showwarning(
                "설정",
                f"{cfg_path.name} 에 elevenlabs_api_key 를 넣으세요.\n\n{cfg_path}",
            )
            return
        if not vid:
            messagebox.showwarning("설정", f"{cfg_path.name} 에 voice_id 를 넣으세요.")
            return

        block = txt.get("1.0", "end-1c").strip()
        if not block:
            if not load_from_input_dir(quiet=True):
                messagebox.showwarning(
                    "입력",
                    "TTS 텍스트를 붙여넣거나, 입력 폴더를 지정한 뒤 「입력 폴더 불러오기」를 누르세요.",
                )
                return
            block = txt.get("1.0", "end-1c")
        entries = parse_knowledgetts_block(block)
        if not entries:
            messagebox.showerror(
                "파싱",
                "유효한 줄이 없습니다.\n"
                "한 줄: `1-1 원본: … TTS: …` / `1-1 原稿: … TTS: …` / `1-1 Original: … TTS: …`\n"
                "여러 줄: `1-1` 다음 `Original:` · `TTS:` · `STT_Reference:`(선택) 형식인지 확인하세요.",
            )
            return

        groups = _group_by_part(entries)
        total_lines = len(entries)

        busy["v"] = True
        gen_cancel.clear()
        btn_run.state(["disabled"])
        btn_merge.state(["disabled"])
        btn_stop.state(["!disabled"])
        status.set(f"처리 중… (0/{total_lines})")
        log.delete("1.0", tk.END)

        def work() -> None:
            cancelled = False
            completed_parts = 0
            try:
                output_dir = _output_dir()
                output_dir.mkdir(parents=True, exist_ok=True)
                seg_root = output_dir / "segments"
                seg_root.mkdir(parents=True, exist_ok=True)

                pad = max(2, len(str(len(groups))))
                done = 0

                for pid, group_entries in groups.items():
                    if gen_cancel.is_set():
                        cancelled = True
                        break

                    part_lbl = _part_label(pid, pad)
                    part_seg_paths: list[Path] = []
                    part_seg_blobs: list[bytes] = []
                    seg_durs_ms: list[int] = []
                    line_segment_mp3: list[str] = []

                    synth_groups = group_entries_for_synthesis(group_entries)
                    for gidx, grp in enumerate(synth_groups, start=1):
                        if gen_cancel.is_set():
                            cancelled = True
                            break

                        merged_tts = merge_group_tts(grp)
                        pre_pause_ms = leading_pause_ms(merged_tts)
                        api_tts = (
                            remove_leading_pause_tags(merged_tts)
                            if pre_pause_ms
                            else merged_tts
                        )

                        def upd(n: int = done) -> None:
                            status.set(f"음성 합성… {part_lbl} ({n}/{total_lines})")

                        safe_after(root, upd)
                        blob = synthesize_mp3(key, vid, api_tts, model_id=model)
                        seg_p = seg_root / f"{part_lbl}_{gidx:04d}.mp3"
                        seg_p.write_bytes(blob)
                        if pre_pause_ms:
                            prepend_silence_mp3(seg_p, pre_pause_ms / 1000.0)
                        part_seg_paths.append(seg_p)
                        part_seg_blobs.append(blob)

                        try:
                            group_ms = int(round(ffprobe_duration_sec(seg_p) * 1000))
                        except Exception:
                            group_ms = estimate_duration_ms(api_tts) + pre_pause_ms
                        group_ms = max(1, group_ms)
                        weights = [tts_synthesis_weight(e.tts) for e in grp]
                        line_durs = split_duration_ms(group_ms, weights)
                        seg_path = str(seg_p.resolve())
                        for e, dms in zip(grp, line_durs):
                            done += 1
                            safe_after(root, upd)
                            seg_durs_ms.append(dms)
                            line_segment_mp3.append(seg_path)

                    n_done = len(seg_durs_ms)
                    if n_done > 0:
                        _finalize_part(
                            part_lbl=part_lbl,
                            part_entries=group_entries[:n_done],
                            part_seg_paths=part_seg_paths,
                            part_seg_blobs=part_seg_blobs,
                            seg_durs_ms=seg_durs_ms,
                            line_segment_mp3=line_segment_mp3,
                            model=model,
                            output_dir=output_dir,
                        )
                        completed_parts += 1

                    if cancelled:
                        break

                if cancelled:

                    def stopped() -> None:
                        status.set(
                            f"중지됨 — {done}/{total_lines}줄, {completed_parts}개 파트 저장"
                        )
                        log_line("")
                        log_line(f"출력 폴더: {output_dir}")
                        log_line("중지 시점까지 완료된 파트·세그먼트만 저장되었습니다.")
                        safe_messagebox(
                            root,
                            "showinfo",
                            "중지",
                            f"음성 합성을 중지했습니다.\n\n"
                            f"처리 줄: {done}/{total_lines}\n"
                            f"저장 파트: {completed_parts}개\n"
                            f"출력 폴더: {output_dir}",
                        )

                    safe_after(root, stopped)
                else:

                    def ok() -> None:
                        status.set("완료")
                        log_line("")
                        log_line(f"출력 폴더: {output_dir}")
                        log_line(f"세그먼트 폴더: {seg_root}")
                        log_line("통합 all.* 은 「병합 파일 생성」 버튼으로 만드세요.")
                        safe_messagebox(
                            root,
                            "showinfo",
                            "완료",
                            f"파트 수: {len(groups)}\n"
                            f"출력 폴더: {output_dir}\n\n"
                            "통합 all.{mp3,srt,json} 은 「병합 파일 생성」으로 수동 생성할 수 있습니다.\n"
                            "자막 시간은 각 세그먼트 MP3(ffprobe) 길이에 맞춥니다. ffprobe 없으면 글자 수 추정으로 대체됩니다.",
                        )

                    safe_after(root, ok)
            except Exception:
                err = traceback.format_exc()

                def fail() -> None:
                    status.set("오류")
                    log_line(err)
                    safe_messagebox(
                        root,
                        "showerror",
                        "오류",
                        "실패했습니다. 하단 실행 로그를 복사해 확인하세요.",
                    )

                safe_after(root, fail)
            finally:

                def fin() -> None:
                    busy["v"] = False
                    btn_run.state(["!disabled"])
                    btn_merge.state(["!disabled"])
                    btn_stop.state(["disabled"])

                safe_after(root, fin)

        threading.Thread(target=work, daemon=True).start()

    def run_merge_all() -> None:
        if busy["v"]:
            return
        persist_dirs()
        output_dir = _output_dir()
        part_mp3s = discover_part_mp3_paths(output_dir)
        if not part_mp3s:
            messagebox.showerror(
                "병합",
                f"{output_dir} 에 part01.mp3, part02.mp3 … 가 없습니다.\n먼저 파트 생성을 실행하세요.",
            )
            return
        missing: list[str] = []
        for mp in part_mp3s:
            if not mp.with_suffix(".srt").is_file():
                missing.append(f"{mp.stem}.srt")
            if not mp.with_suffix(".json").is_file():
                missing.append(f"{mp.stem}.json")
        if missing:
            messagebox.showerror("병합", "다음 파일이 없습니다:\n" + "\n".join(missing))
            return

        busy["v"] = True
        btn_run.state(["disabled"])
        btn_merge.state(["disabled"])
        status.set("병합 중…")
        log.delete("1.0", tk.END)

        def work() -> None:
            try:
                all_mp3 = output_dir / "all.mp3"
                all_srt = output_dir / "all.srt"
                all_json = output_dir / "all.json"

                all_merge_note = ""
                try:
                    concat_mp3_files_ffmpeg(part_mp3s, all_mp3)
                    all_merge_note = "ffmpeg-reencode"
                except Exception as ff_err:
                    concat_mp3_files_binary_from_paths(part_mp3s, all_mp3)
                    all_merge_note = f"binary-fallback ({ff_err})"

                srt_paths = [p.with_suffix(".srt") for p in part_mp3s]
                merged_srt, _timeline_end = merge_srt_files(srt_paths, part_mp3_paths=part_mp3s)
                all_srt.write_text(merged_srt, encoding="utf-8")

                merged_doc = build_merged_json_from_part_files(
                    part_mp3s, all_mp3, all_srt, all_merge_method=all_merge_note
                )
                all_json.write_text(json.dumps(merged_doc, ensure_ascii=False, indent=2), encoding="utf-8")

                def ok() -> None:
                    status.set("병합 완료")
                    log_line(f"all.mp3 ← {len(part_mp3s)}개 파트 ({all_merge_note})")
                    log_line(f"all.srt ← part*.srt 병합 (큐 번호=시작 시각 초, 예: 00:07:29→449)")
                    log_line(f"all.json ← part*.json 메타 병합")
                    log_line(f"MP3: {all_mp3}")
                    log_line(f"SRT: {all_srt}")
                    log_line(f"JSON: {all_json}")
                    safe_messagebox(
                        root,
                        "showinfo",
                        "병합 완료",
                        f"all.mp3\nall.srt\nall.json\n\n폴더: {output_dir}",
                    )

                safe_after(root, ok)
            except Exception:
                err = traceback.format_exc()

                def fail() -> None:
                    status.set("병합 오류")
                    log_line(err)
                    safe_messagebox(
                        root,
                        "showerror",
                        "병합 오류",
                        "실패했습니다. 실행 로그를 확인하세요.",
                    )

                safe_after(root, fail)
            finally:

                def fin() -> None:
                    busy["v"] = False
                    btn_run.state(["!disabled"])
                    btn_merge.state(["!disabled"])

                safe_after(root, fin)

        threading.Thread(target=work, daemon=True).start()

    btn_row = ttk.Frame(frm)
    btn_row.grid(row=next_row + 4, column=0, sticky="w", pady=(0, 4))
    btn_run = ttk.Button(
        btn_row,
        text="파트별 MP3·SRT·JSON 생성 (TTS 합성)",
        command=run_gen,
    )
    btn_run.grid(row=0, column=0, sticky="w", padx=(0, 8))
    btn_stop = ttk.Button(btn_row, text="중지", command=stop_gen, state=tk.DISABLED)
    btn_stop.grid(row=0, column=1, sticky="w", padx=(0, 8))
    btn_merge = ttk.Button(
        btn_row,
        text="병합 파일 생성 (all.mp3 / all.srt / all.json)",
        command=run_merge_all,
    )
    btn_merge.grid(row=0, column=2, sticky="w")
    ttk.Label(frm, textvariable=status).grid(row=next_row + 5, column=0, sticky="w")

    hint = (
        f"{config_file_path().name} 은 Git·공유에 넣지 마세요. "
        "작업 폴더는 wisdom/config/wisdom_workspace.json 에 저장됩니다."
    )
    ttk.Label(
        frm,
        text=hint,
        foreground="gray",
    ).grid(row=next_row + 6, column=0, sticky="w", pady=(10, 0))

    if not standalone:
        bind_hub_destroy(root, lambda: None)

    run_mainloop(root, standalone)


if __name__ == "__main__":
    main()
