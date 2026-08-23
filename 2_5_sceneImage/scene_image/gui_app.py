# -*- coding: utf-8 -*-
"""2_5_sceneImage GUI — 루트/stt·mp3·png + 모듈 md → Genspark 생성."""

from __future__ import annotations

import re
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, ttk

from scene_image import __version__
from scene_image.credentials import load_credentials, save_credentials
from scene_image.genspark_image import (
    build_generate_command_from_sources,
    get_image_session,
    has_playwright,
    image_profile_dir,
    open_browser_for_account,
    preferred_genspark_url,
    set_tab_log_png_dir,
)
from scene_image.image_log import append_image_log
from scene_image.paths import (
    GENSPARK_AI_IMAGE_URL,
    build_paste_payload,
    default_png_dir,
    default_root_dir,
    ensure_root_layout,
    find_default_srt,
    find_image_prompt_file,
    load_scene_text,
    module_md_dir,
    paste_payload_stats,
    png_dir_under_root,
)
from scene_image.pipeline_config import load_pipeline_config, model_name_variants
from scene_image.scene_parse import (
    SceneLine,
    build_interval_scenes,
    parse_scene_script,
    png_already_exists,
    scene_png_path,
)
from scene_image.settings import load_gui_settings, load_model_selector, save_gui_settings
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path

_INTERVAL_CHOICES = ("10", "15", "20")
_REQUEST_WAIT_CHOICES = ("0", "1", "2", "3", "5")
_SEC_SPLIT_RE = re.compile(r"[,;\s]+")


def _default_font() -> tuple[str, int]:
    try:
        f = tkfont.nametofont("TkDefaultFont")
        return (f.actual("family"), max(10, int(f.actual("size"))))
    except tk.TclError:
        return ("맑은 고딕", 10)


def _parse_manual_secs(text: str) -> list[int]:
    out: list[int] = []
    seen: set[int] = set()
    for part in _SEC_SPLIT_RE.split((text or "").strip()):
        if not part:
            continue
        try:
            sec = int(part)
        except ValueError:
            continue
        if sec < 0 or sec in seen:
            continue
        seen.add(sec)
        out.append(sec)
    return out


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
    if not standalone and getattr(root, "_scene_image_gui_built", False):
        return
    if not standalone:
        setattr(root, "_scene_image_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_5 sceneImage {__version__}",
        minsize=(780, 560),
        geometry="960x700",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    root_default = cfg.get("root_dir") or str(default_root_dir())
    png_default = cfg.get("png_dir") or str(png_dir_under_root(root_default))
    url_default = cfg.get("genspark_url") or GENSPARK_AI_IMAGE_URL
    srt_default = cfg.get("srt_path") or ""
    prompt_default = cfg.get("prompt_path") or ""
    interval_default = cfg.get("interval_sec") or "20"
    if interval_default not in _INTERVAL_CHOICES:
        interval_default = "20"
    request_wait_default = cfg.get("request_wait_sec") or "0"
    if request_wait_default not in _REQUEST_WAIT_CHOICES:
        request_wait_default = "0"
    manual_default = cfg.get("manual_secs") or ""
    scene_cache = cfg.get("scene_script") or ""

    if not srt_default:
        found = find_default_srt(root_default)
        if found is not None:
            srt_default = str(found)
    if not prompt_default:
        found_p = find_image_prompt_file()
        if found_p is not None:
            prompt_default = str(found_p)
    elif not Path(prompt_default).is_file():
        found_p = find_image_prompt_file()
        if found_p is not None:
            prompt_default = str(found_p)

    cred_email, cred_pw = load_credentials()
    root_var = tk.StringVar(value=root_default)
    png_var = tk.StringVar(value=png_default)
    url_var = tk.StringVar(value=url_default)
    srt_var = tk.StringVar(value=srt_default)
    prompt_var = tk.StringVar(value=prompt_default)
    interval_var = tk.StringVar(value=interval_default)
    request_wait_var = tk.StringVar(value=request_wait_default)
    manual_var = tk.StringVar(value=manual_default)
    email_var = tk.StringVar(value=cred_email)
    pw_var = tk.StringVar(value=cred_pw)
    status_var = tk.StringVar(
        value="「브라우저 열기」= 재오픈·붙여넣기·생성·다운로드 일괄"
    )
    scene_var = tk.StringVar(value="")
    busy = {"v": False}
    browser_ready = {"v": False}
    # 브라우저 열기로 입력창에 SRT·프롬프트+명령이 준비됨(미전송)
    input_prepared = {"v": False, "cmd_sec": None}
    scenes: list[SceneLine] = []
    collected: list[tuple[int | None, str]] = []
    scene_text_cache = {"v": scene_cache}

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(3, weight=1)

    def persist() -> None:
        save_gui_settings(
            root_dir=root_var.get().strip(),
            png_dir=png_var.get().strip(),
            genspark_url=url_var.get().strip(),
            srt_path=srt_var.get().strip(),
            prompt_path=prompt_var.get().strip(),
            interval_sec=interval_var.get().strip() or "20",
            request_wait_sec=request_wait_var.get().strip() or "0",
            manual_secs=manual_var.get().strip(),
            scene_script=scene_text_cache["v"],
            scene_index=str(
                max(0, scene_list.curselection()[0]) if scene_list.curselection() else 0
            ),
        )
        if email_var.get().strip() and pw_var.get():
            save_credentials(email_var.get().strip(), pw_var.get())

    def set_status(msg: str) -> None:
        status_var.set(msg)

    def set_busy(v: bool) -> None:
        busy["v"] = v
        state = tk.DISABLED if v else tk.NORMAL
        for b in (btn_browser, btn_manual):
            try:
                b.configure(state=state)
            except tk.TclError:
                pass

    def profile_dir() -> Path:
        base = Path(__file__).resolve().parents[1] / "dist"
        if not standalone:
            try:
                from wisdom_root import resolve_wisdom_root

                base = resolve_wisdom_root() / "2_5_sceneImage" / "dist"
            except Exception:
                pass
        base.mkdir(parents=True, exist_ok=True)
        return image_profile_dir(base)

    def interval_sec() -> int:
        try:
            n = int(interval_var.get().strip() or "20")
        except ValueError:
            n = 20
        return n if n in (10, 15, 20) else 20

    def request_wait_sec() -> int:
        try:
            n = int(request_wait_var.get().strip() or "0")
        except ValueError:
            n = 0
        return n if n in (0, 1, 2, 3, 5) else 0

    def append_collected_path(sec: int, path: str) -> None:
        label = f"SRT_{sec:03d}"
        short = path if len(path) < 90 else path[:87] + "…"
        link_list.insert(tk.END, f"{label}  |  {short}")
        collected.append((sec, path))

    def apply_root(*, force: bool = True) -> None:
        r = Path(root_var.get().strip() or ".")
        layout = ensure_root_layout(r)
        png_var.set(str(layout["png"]))
        if force or not srt_var.get().strip():
            srt = find_default_srt(r)
            if srt is not None:
                srt_var.set(str(srt))
        if not prompt_var.get().strip():
            prompt = find_image_prompt_file()
            if prompt is not None:
                prompt_var.set(str(prompt))
        reload_scenes()
        persist()
        set_status(f"루트 — mp3/stt/png → {r}")

    def auto_assign_from_png(*, force: bool = False) -> None:
        # 호환: png 변경 시 부모를 루트로 간주
        png = png_var.get().strip()
        if not png:
            return
        p = Path(png)
        r = p.parent if p.name.casefold() == "png" else p
        root_var.set(str(r))
        apply_root(force=force)

    def pick_root() -> None:
        init = folder_dialog_initial(
            Path(root_var.get()) if root_var.get().strip() else default_root_dir()
        )
        p = filedialog.askdirectory(parent=root, title="루트 폴더", initialdir=init)
        if p:
            root_var.set(p)
            touch_workspace_from_path(p)
            apply_root(force=True)

    def pick_png() -> None:
        init = folder_dialog_initial(
            Path(png_var.get()) if png_var.get().strip() else default_png_dir()
        )
        p = filedialog.askdirectory(parent=root, title="png 저장 폴더", initialdir=init)
        if p:
            png_var.set(p)
            touch_workspace_from_path(p)
            auto_assign_from_png(force=False)
            set_status(f"png 지정 → {p}")

    def pick_srt() -> None:
        root_p = Path(root_var.get().strip()) if root_var.get().strip() else default_root_dir()
        init = folder_dialog_initial(
            Path(srt_var.get()).parent
            if srt_var.get().strip()
            else (root_p / "mp3" if (root_p / "mp3").is_dir() else root_p / "stt")
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="대본 SRT (new.srt / all.srt)",
            initialdir=init,
            filetypes=[("SRT", "*.srt"), ("모든 파일", "*.*")],
        )
        if p:
            srt_var.set(p)
            persist()

    def pick_prompt() -> None:
        md = module_md_dir()
        md.mkdir(parents=True, exist_ok=True)
        init = folder_dialog_initial(
            Path(prompt_var.get()).parent if prompt_var.get().strip() else md
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="이미지프롬프트 (모듈 md)",
            initialdir=init,
            filetypes=[("텍스트", "*.txt;*.md"), ("모든 파일", "*.*")],
        )
        if p:
            prompt_var.set(p)
            reload_scenes()
            persist()

    # --- paths ---
    path_fr = ttk.LabelFrame(frm, text="경로", padding=(8, 6))
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    path_fr.grid_columnconfigure(1, weight=1)

    ttk.Label(path_fr, text="루트 폴더", width=14).grid(row=0, column=0, sticky="w")
    root_ent = ttk.Entry(path_fr, textvariable=root_var)
    root_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6), pady=2)
    ttk.Button(path_fr, text="찾기…", width=8, command=pick_root).grid(
        row=0, column=2, sticky="e"
    )
    bind_path_entry_dnd(root_ent, root_var, mode="dir")
    bind_path_row_dnd(root_ent, path_fr, root_var, mode="dir")

    ttk.Label(path_fr, text="png 폴더", width=14).grid(row=1, column=0, sticky="w")
    png_ent = ttk.Entry(path_fr, textvariable=png_var)
    png_ent.grid(row=1, column=1, sticky="ew", padx=(4, 6), pady=2)
    ttk.Button(path_fr, text="찾기…", width=8, command=pick_png).grid(
        row=1, column=2, sticky="e"
    )
    bind_path_entry_dnd(png_ent, png_var, mode="dir")
    bind_path_row_dnd(png_ent, path_fr, png_var, mode="dir")

    ttk.Label(path_fr, text="대본 (new.srt)", width=14).grid(row=2, column=0, sticky="w")
    srt_ent = ttk.Entry(path_fr, textvariable=srt_var)
    srt_ent.grid(row=2, column=1, sticky="ew", padx=(4, 6), pady=2)
    ttk.Button(path_fr, text="찾기…", width=8, command=pick_srt).grid(
        row=2, column=2, sticky="e"
    )
    bind_path_entry_dnd(srt_ent, srt_var, mode="file")

    ttk.Label(path_fr, text="이미지프롬프트", width=14).grid(row=3, column=0, sticky="w")
    prompt_ent = ttk.Entry(path_fr, textvariable=prompt_var)
    prompt_ent.grid(row=3, column=1, sticky="ew", padx=(4, 6), pady=2)
    ttk.Button(path_fr, text="찾기…", width=8, command=pick_prompt).grid(
        row=3, column=2, sticky="e"
    )
    bind_path_entry_dnd(prompt_ent, prompt_var, mode="file")

    ttk.Label(path_fr, text="씬 간격(초)", width=14).grid(row=4, column=0, sticky="w")
    interval_row = ttk.Frame(path_fr)
    interval_row.grid(row=4, column=1, columnspan=2, sticky="w", padx=(4, 0), pady=2)
    interval_cb = ttk.Combobox(
        interval_row,
        textvariable=interval_var,
        values=_INTERVAL_CHOICES,
        width=6,
        state="readonly",
    )
    interval_cb.pack(side=tk.LEFT)
    ttk.Label(interval_row, text="요청 대기(초)").pack(side=tk.LEFT, padx=(16, 4))
    request_cb = ttk.Combobox(
        interval_row,
        textvariable=request_wait_var,
        values=_REQUEST_WAIT_CHOICES,
        width=4,
        state="readonly",
    )
    request_cb.pack(side=tk.LEFT)

    ttk.Label(path_fr, text="브라우저 주소", width=14).grid(row=5, column=0, sticky="w")
    url_ent = ttk.Entry(path_fr, textvariable=url_var)
    url_ent.grid(row=5, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2)

    ttk.Label(path_fr, text="Chrome 계정", width=14).grid(row=6, column=0, sticky="w")
    ttk.Entry(path_fr, textvariable=email_var).grid(
        row=6, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2
    )
    ttk.Label(path_fr, text="비밀번호(선택)", width=14).grid(row=7, column=0, sticky="w")
    ttk.Entry(path_fr, textvariable=pw_var, show="*").grid(
        row=7, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2
    )

    def on_root_path_change(*_a: object) -> None:
        p = root_var.get().strip()
        if p:
            apply_root(force=False)

    def on_png_path_change(*_a: object) -> None:
        p = png_var.get().strip()
        if p:
            persist()
            touch_workspace_from_path(p)

    png_var.trace_add("write", on_png_path_change)
    root_var.trace_add("write", on_root_path_change)

    # --- actions ---
    act = ttk.Frame(frm)
    act.grid(row=1, column=0, sticky="ew", pady=(0, 6))

    def selected_scene() -> SceneLine | None:
        sel = scene_list.curselection()
        if not sel:
            return None
        i = int(sel[0])
        if 0 <= i < len(scenes):
            return scenes[i]
        return None

    def reload_scenes() -> None:
        nonlocal scenes
        text = load_scene_text(
            prompt_path=prompt_var.get().strip() or None,
            png_dir=png_var.get().strip() or None,
            fallback_text=scene_text_cache["v"],
        )
        if text.strip():
            scene_text_cache["v"] = text
        parsed = parse_scene_script(text)
        scenes = build_interval_scenes(
            parsed,
            srt_path=srt_var.get().strip() or None,
            interval_sec=interval_sec(),
        )
        scene_list.delete(0, tk.END)
        png_dir = Path(png_var.get().strip() or ".")
        for sc in scenes:
            mark = "✓ " if png_already_exists(png_dir, sc.sec) else ""
            scene_list.insert(tk.END, f"{mark}{sc.list_label()}")
        if scenes:
            idx = 0
            raw = cfg.get("scene_index", "0")
            try:
                idx = max(0, min(len(scenes) - 1, int(raw)))
            except ValueError:
                idx = 0
            scene_list.selection_set(idx)
            on_scene_select()
            set_status(
                f"씬 {len(scenes)}개 · {scenes[0].label}…{scenes[-1].label} "
                f"· 씬간격 {interval_sec()}초"
            )
        else:
            scene_var.set("")
            set_status(
                "생성할 씬이 없습니다. 이미지프롬프트·SRT(new.srt)를 확인하세요."
            )
        persist()

    def _account() -> tuple[str, str] | None:
        email = email_var.get().strip() or "dream7515@gmail.com"
        password = pw_var.get()
        if not password:
            _e, _p = load_credentials()
            if _p:
                password = _p
                pw_var.set(_p)
            if not email_var.get().strip() and _e:
                email = _e
                email_var.set(_e)
        if not email:
            safe_messagebox(
                root, "showwarning", "2_5 sceneImage", "계정 이메일을 입력하세요."
            )
            return None
        return email, password

    def _ensure_browser_and_paste(
        *,
        email: str,
        password: str,
        url: str,
        model_sel: str,
        model_texts: list[str] | tuple[str, ...],
        pipe: dict,
        png_dir: Path,
        force_paste: bool = True,
        first_command_sec: int | None = None,
        first_scene_prompt: str | None = None,
        submit_context: bool = True,
        force_reopen: bool = False,
        interval_for_cmd: int = 20,
    ) -> tuple[object, bool]:
        """브라우저 오픈 + 프롬프트/대본 붙여넣기 (+ 선택: 첫 명령 입력).

        ``force_reopen=True`` 이면 기존 ChromeDebug·세션을 종료하고 새로 연다.
        """
        if force_reopen:
            browser_ready["v"] = False
            info = open_browser_for_account(
                url, email=email, restart_chrome=True
            )
            # CDP 준비는 open_chrome_debug 내부에서 대기함
            time.sleep(0.5)
            append_image_log(
                png_dir,
                f"ChromeDebug 재시작 port={info.get('debug_port')} "
                f"user_data={info.get('user_data')}",
            )
        elif not browser_ready["v"]:
            info = open_browser_for_account(url, email=email)
            time.sleep(0.5)
            append_image_log(
                png_dir,
                f"ChromeDebug 열림 port={info.get('debug_port')} "
                f"user_data={info.get('user_data')}",
            )
        if not has_playwright():
            raise RuntimeError("Playwright가 필요합니다.")

        sess = get_image_session(profile_dir())
        if not browser_ready["v"]:
            safe_after(root, lambda: set_status("Genspark 페이지 연결·로그인…"))
            result = sess.open_and_select_model(
                url=url,
                model_selector=model_sel,
                email=email,
                password=password,
                model_texts=model_texts,
            )
            logged_in = bool(isinstance(result, dict) and result.get("logged_in"))
            model_ok = bool(isinstance(result, dict) and result.get("model_auto"))
            append_image_log(
                png_dir,
                f"세션 준비 — login={'OK' if logged_in else '확인'} "
                f"model={pipe.get('model')} auto={model_ok}",
            )
            browser_ready["v"] = True
        else:
            model_ok = True

        # 붙여넣기 직전: 없는 SRT/프롬프트 경로를 루트·모듈에서 재탐색
        prompt_path = prompt_var.get().strip()
        srt_path = srt_var.get().strip()
        if not prompt_path or not Path(prompt_path).is_file():
            found_p = find_image_prompt_file(preferred=prompt_path or None)
            if found_p is not None:
                prompt_path = str(found_p)
                prompt_var.set(prompt_path)
        if not srt_path or not Path(srt_path).is_file():
            found_s = find_default_srt(root_var.get().strip() or ".")
            if found_s is not None:
                srt_path = str(found_s)
                srt_var.set(srt_path)
                append_image_log(png_dir, f"SRT 경로 재지정 → {srt_path}")

        stats = paste_payload_stats(prompt_path, srt_path)
        paste = build_paste_payload(prompt_path, srt_path)
        if force_paste:
            if not stats["prompt_ok"]:
                raise RuntimeError(
                    "이미지프롬프트 파일을 읽을 수 없습니다.\n"
                    f"경로: {prompt_path or '(비어 있음)'}"
                )
            if not stats["srt_ok"]:
                raise RuntimeError(
                    "SRT 파일을 읽을 수 없습니다. (프롬프트만 붙여넣히던 원인)\n"
                    f"경로: {srt_path or '(비어 있음)'}\n"
                    "루트/mp3 또는 stt 의 new.srt · all.srt 를 확인하세요."
                )
            if not stats["has_srt_timecode"]:
                raise RuntimeError(
                    f"SRT에 타임코드(-->)가 없습니다.\n{srt_path}"
                )
            safe_after(
                root,
                lambda: set_status(
                    f"SRT·프롬프트 붙여넣기 중… ({stats['prompt_chars']}+{stats['srt_chars']}자)"
                ),
            )
            # 동일 입력창에 SRT·프롬프트만 붙여넣기 (실행은 SRT_XXX 명령에서)
            if submit_context:
                sess.submit_prompt(
                    url=url,
                    prompt=paste,
                    model_selector=model_sel,
                    try_model_select=not model_ok,
                    model_texts=model_texts,
                )
            else:
                sess.paste_text(
                    url=url,
                    text=paste,
                    model_selector=model_sel,
                    try_model_select=not model_ok,
                    model_texts=model_texts,
                )
            append_image_log(
                png_dir,
                f"입력창 붙여넣기 — 프롬프트 {stats['prompt_chars']}자"
                f" + SRT {stats['srt_chars']}자"
                f" = 합계 {len(paste)}자"
                f"\n  prompt={prompt_path}\n  srt={srt_path}",
            )
            time.sleep(1.0)

        if first_command_sec is not None:
            cmd = build_generate_command_from_sources(
                first_command_sec,
                scene_prompt=first_scene_prompt,
                srt_path=srt_path,
                interval_sec=interval_for_cmd,
                png_dir=png_dir,
            )
            # SRT·프롬프트가 들어 있는 동일 입력창 끝에 명령만 추가 (실행 안 함)
            sess.paste_text(
                url=url,
                text=cmd,
                model_selector=model_sel,
                try_model_select=False,
                model_texts=model_texts,
                append=True,
            )
            append_image_log(
                png_dir,
                f"동일 입력창에 명령 추가(미실행): {cmd[:180]}"
                + ("…" if len(cmd) > 180 else ""),
            )
            input_prepared["v"] = True
            input_prepared["cmd_sec"] = int(first_command_sec)
            time.sleep(0.5)
        return sess, model_ok

    def _run_scenes(
        todo: list[SceneLine],
        *,
        open_browser_first: bool,
        title: str,
        force_reopen: bool = False,
    ) -> None:
        if busy["v"] and not force_reopen:
            safe_messagebox(
                root,
                "showinfo",
                "2_5 sceneImage",
                "이미 작업 중입니다. 끝난 뒤 「브라우저 열기」를 다시 누르세요.",
            )
            return
        acc = _account()
        if acc is None:
            return
        email, password = acc
        png_dir = Path(png_var.get().strip())
        if not str(png_dir):
            safe_messagebox(root, "showwarning", "2_5 sceneImage", "png 폴더를 지정하세요.")
            return
        if not todo:
            safe_messagebox(
                root, "showinfo", "2_5 sceneImage", "생성할 씬이 없거나 모두 이미 있습니다."
            )
            return
        pipe = load_pipeline_config()
        url = preferred_genspark_url(
            url_var.get().strip() or str(pipe.get("genspark_url") or "")
        )
        model_sel = load_model_selector()
        model_texts = model_name_variants(str(pipe.get("model") or "Nano Banana Pro"))
        gap = interval_sec()
        wait_gap = request_wait_sec()
        gen_timeout = max(120, int(pipe.get("generate_timeout_sec") or 120))
        first_sec = int(todo[0].sec)
        # 입력창에 컨텍스트+명령이 없으면 붙여넣기 준비 (전송은 run_scene에서)
        need_prepare = (
            force_reopen
            or open_browser_first
            or (not browser_ready["v"])
            or (not input_prepared["v"])
            or (input_prepared.get("cmd_sec") != first_sec)
        )
        persist()

        def work() -> None:
            try:
                if not has_playwright():
                    raise RuntimeError(
                        "Playwright가 없습니다. 수동으로 생성하세요."
                    )
                set_tab_log_png_dir(png_dir)
                append_image_log(
                    png_dir,
                    f"탭로그 ON — {title} · 씬 {len(todo)}개 · reopen={force_reopen}",
                )
                sess, model_ok = _ensure_browser_and_paste(
                    email=email,
                    password=password,
                    url=url,
                    model_sel=model_sel,
                    model_texts=model_texts,
                    pipe=pipe,
                    png_dir=png_dir,
                    force_paste=need_prepare,
                    first_command_sec=first_sec if need_prepare else None,
                    first_scene_prompt=(
                        todo[0].prompt if need_prepare and todo else None
                    ),
                    # 컨텍스트+명령은 입력만 — 전송은 아래 run_scene(첫 씬)
                    submit_context=False,
                    force_reopen=force_reopen,
                    interval_for_cmd=gap,
                )
                saved_n = 0
                skipped_n = 0
                ran_n = 0
                failed_n = 0
                for i, sc in enumerate(todo):
                    if png_already_exists(png_dir, sc.sec):
                        skipped_n += 1
                        path = str(scene_png_path(png_dir, sc.sec))
                        append_image_log(png_dir, f"{sc.label} 건너뜀 (기존 PNG) {path}")

                        def _skip(s=sc, p=path) -> None:
                            append_collected_path(s.sec, p)

                        safe_after(root, _skip)
                        continue
                    # 이전 씬 후 요청 대기 (씬 간격과 별개 · 첫 실행 씬은 바로)
                    if ran_n > 0 and wait_gap > 0:
                        safe_after(
                            root,
                            lambda g=wait_gap, s=sc: set_status(
                                f"요청 대기 {g}초 → {s.label}…"
                            ),
                        )
                        time.sleep(wait_gap)
                    cmd = build_generate_command_from_sources(
                        sc.sec,
                        scene_prompt=sc.prompt,
                        srt_path=srt_var.get().strip() or None,
                        interval_sec=gap,
                        png_dir=png_dir,
                    )
                    # 첫 실행 씬: 입력창(SRT·프롬프트+명령) 그대로 전송
                    use_box = ran_n == 0 and bool(input_prepared["v"])
                    safe_after(
                        root,
                        lambda s=sc, n=i, c=cmd, u=use_box: set_status(
                            f"{title} {n + 1}/{len(todo)} — "
                            + ("입력창 전송 · " if u else "")
                            + c[:80]
                            + ("…" if len(c) > 80 else "")
                        ),
                    )
                    try:
                        out = sess.run_scene_with_retry(
                            url=url,
                            prompt=sc.prompt,
                            png_dir=png_dir,
                            srt_sec=sc.sec,
                            model_selector=model_sel,
                            model_texts=model_texts,
                            try_model_select=(ran_n == 0),
                            retry_count=1,
                            retry_wait_sec=0,
                            generate_timeout_sec=gen_timeout,
                            use_existing_input=use_box,
                            srt_path=srt_var.get().strip() or None,
                            interval_sec=gap,
                            prompt_path=prompt_var.get().strip() or None,
                        )
                    except Exception as scene_err:
                        # Failure 등으로 한 씬이 실패해도 다음 씬 계속
                        failed_n += 1
                        if use_box:
                            input_prepared["v"] = False
                            input_prepared["cmd_sec"] = None
                        ran_n += 1
                        err_s = str(scene_err)
                        append_image_log(
                            png_dir,
                            f"{sc.label} 실패 — 다음 씬 계속\n{err_s}",
                        )
                        safe_after(
                            root,
                            lambda s=sc, e=err_s: set_status(
                                f"{s.label} 실패 · 다음 씬 계속 — {e[:80]}"
                            ),
                        )
                        continue
                    if use_box:
                        input_prepared["v"] = False
                        input_prepared["cmd_sec"] = None
                    ran_n += 1
                    paths = list((out or {}).get("saved") or [])
                    saved_n += len(paths)
                    show_paths = paths or [str(scene_png_path(png_dir, sc.sec))]
                    append_image_log(
                        png_dir,
                        f"{sc.label} 생성·다운로드 완료\n" + "\n".join(show_paths),
                    )

                    def _done_paths(s=sc, ps=list(show_paths)) -> None:
                        for p in ps:
                            append_collected_path(s.sec, p)

                    safe_after(root, _done_paths)

                def done() -> None:
                    set_busy(False)
                    reload_scenes()
                    set_status(
                        f"{title} 완료 — 저장 {saved_n} · 건너뜀 {skipped_n}"
                        + (f" · 실패 {failed_n}" if failed_n else "")
                        + f" → {png_dir}"
                    )
                    msg = (
                        f"저장 {saved_n}개 · 건너뜀 {skipped_n}개"
                        + (f" · 실패 {failed_n}개" if failed_n else "")
                        + f"\n{png_dir}"
                    )
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_5 sceneImage",
                        msg,
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)
                try:
                    append_image_log(png_dir, f"{title} 오류: {err}")
                except Exception:
                    pass

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_5 sceneImage", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(
            f"{title} 준비 — 씬간격 {gap}초 · 요청대기 {wait_gap}초 · {len(todo)}개"
            + (" · 입력창 준비" if need_prepare else " · 입력창 전송")
        )
        threading.Thread(target=work, daemon=True).start()

    def open_browser() -> None:
        """재오픈 → SRT·프롬프트·명령 → 생성·다운로드·요청대기 반복까지 일괄."""
        if busy["v"]:
            safe_messagebox(
                root,
                "showinfo",
                "2_5 sceneImage",
                "이미 작업 중입니다. 끝난 뒤 다시 누르세요.",
            )
            return
        browser_ready["v"] = False
        input_prepared["v"] = False
        input_prepared["cmd_sec"] = None
        try:
            apply_root(force=True)
        except Exception:
            reload_scenes()
        png_dir = Path(png_var.get().strip() or ".")
        if not str(png_dir).strip() or png_dir == Path("."):
            safe_messagebox(root, "showwarning", "2_5 sceneImage", "png 폴더를 지정하세요.")
            return
        srt_now = srt_var.get().strip()
        if not srt_now or not Path(srt_now).is_file():
            found = find_default_srt(root_var.get().strip() or ".")
            if found is not None:
                srt_var.set(str(found))
            else:
                safe_messagebox(
                    root,
                    "showwarning",
                    "2_5 sceneImage",
                    "SRT 파일이 없습니다.\n"
                    "루트 하위 mp3/new.srt 또는 all.srt 를 지정하세요.",
                )
                return
        todo = [sc for sc in scenes if not png_already_exists(png_dir, sc.sec)]
        _run_scenes(
            todo,
            open_browser_first=True,
            title="브라우저 열기·생성",
            force_reopen=True,
        )

    def manual_generate() -> None:
        if busy["v"]:
            return
        reload_scenes()
        secs = _parse_manual_secs(manual_var.get())
        if not secs:
            safe_messagebox(
                root,
                "showwarning",
                "2_5 sceneImage",
                "초 번호를 입력하세요. 예: 10,20,120",
            )
            return
        by_sec = {sc.sec: sc for sc in scenes}
        todo: list[SceneLine] = []
        missing: list[int] = []
        for sec in secs:
            sc = by_sec.get(sec)
            if sc is None:
                missing.append(sec)
            else:
                todo.append(sc)
        if missing:
            safe_messagebox(
                root,
                "showwarning",
                "2_5 sceneImage",
                "씬 목록에 없는 초: "
                + ", ".join(str(s) for s in missing)
                + "\n이미지프롬프트·SRT 간격을 확인하세요.",
            )
            if not todo:
                return
        persist()
        _run_scenes(todo, open_browser_first=False, title="수동 생성")

    btn_browser = ttk.Button(act, text="브라우저 열기", command=open_browser)
    btn_browser.pack(side=tk.LEFT, padx=(0, 6))

    ttk.Label(frm, textvariable=scene_var).grid(row=2, column=0, sticky="w", pady=(0, 4))

    # --- main panes ---
    paned = ttk.Panedwindow(frm, orient=tk.VERTICAL)
    paned.grid(row=3, column=0, sticky="nsew")

    manual_fr = ttk.LabelFrame(
        paned, text="이미지수동생성 (초 번호: 10,20,120 …)", padding=4
    )
    lists_fr = ttk.Frame(paned)
    paned.add(manual_fr, weight=1)
    paned.add(lists_fr, weight=3)

    manual_fr.grid_columnconfigure(0, weight=1)
    ttk.Label(
        manual_fr,
        text="특정 초만 생성 — 완료 문구 확인 후 다운로드.",
        foreground="#555",
    ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
    manual_ent = ttk.Entry(manual_fr, textvariable=manual_var)
    manual_ent.grid(row=1, column=0, sticky="ew", padx=(0, 6))
    btn_manual = ttk.Button(manual_fr, text="선택 생성", width=10, command=manual_generate)
    btn_manual.grid(row=1, column=1, sticky="e")

    lists_fr.grid_columnconfigure(0, weight=1)
    lists_fr.grid_columnconfigure(1, weight=1)
    lists_fr.grid_rowconfigure(0, weight=1)

    left = ttk.LabelFrame(lists_fr, text="파싱된 씬", padding=4)
    right = ttk.LabelFrame(lists_fr, text="저장된 경로", padding=4)
    left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    right.grid(row=0, column=1, sticky="nsew")
    left.grid_columnconfigure(0, weight=1)
    left.grid_rowconfigure(0, weight=1)
    right.grid_columnconfigure(0, weight=1)
    right.grid_rowconfigure(0, weight=1)

    scene_list = tk.Listbox(left, activestyle="dotbox", exportselection=False)
    scene_sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=scene_list.yview)
    scene_list.configure(yscrollcommand=scene_sb.set)
    scene_list.grid(row=0, column=0, sticky="nsew")
    scene_sb.grid(row=0, column=1, sticky="ns")

    link_list = tk.Listbox(right, activestyle="dotbox", exportselection=False)
    link_sb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=link_list.yview)
    link_list.configure(yscrollcommand=link_sb.set)
    link_list.grid(row=0, column=0, sticky="nsew")
    link_sb.grid(row=0, column=1, sticky="ns")

    def on_scene_select(_event: tk.Event | None = None) -> None:
        sc = selected_scene()
        if sc is None:
            scene_var.set("")
            return
        exists = png_already_exists(Path(png_var.get().strip() or "."), sc.sec)
        mark = " · 이미 있음" if exists else ""
        scene_var.set(f"{sc.label} → {sc.png_name}  |  {len(sc.prompt)}자{mark}")
        persist()

    scene_list.bind("<<ListboxSelect>>", on_scene_select)

    ttk.Label(frm, textvariable=status_var).grid(row=4, column=0, sticky="ew", pady=(8, 0))
    tip = (
        "「브라우저 열기」= 재오픈 → SRT·프롬프트·명령 → 생성·다운로드·간격 반복"
    )
    ttk.Label(frm, text=tip, foreground="#555").grid(row=5, column=0, sticky="w", pady=(4, 0))

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    def _boot() -> None:
        if root_var.get().strip():
            apply_root(force=False)
        elif png_var.get().strip():
            auto_assign_from_png(force=False)
        else:
            reload_scenes()

    root.after(150, _boot)
    run_mainloop(root, standalone)
