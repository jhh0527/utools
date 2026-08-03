# -*- coding: utf-8 -*-
"""2_3_sceneImage GUI — 씬 스크립트 textarea → Genspark Nano banana pro → SRT_XXX.png."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from scene_image import __version__
from scene_image.download import save_images
from scene_image.credentials import load_credentials, save_credentials
from scene_image.genspark_image import (
    get_image_session,
    has_playwright,
    image_profile_dir,
    open_browser_for_account,
    open_browser_for_manual_login,
    preferred_genspark_url,
)
from scene_image.image_log import append_image_log
from scene_image.paths import GENSPARK_AI_IMAGE_URL, default_png_dir, default_script_file
from scene_image.pipeline_config import load_pipeline_config, model_name_variants
from scene_image.scene_parse import (
    SceneLine,
    parse_scene_script,
    png_already_exists,
    srt_png_name,
)
from scene_image.settings import load_gui_settings, load_model_selector, save_gui_settings
from wisdom_workspace import folder_dialog_initial, touch_workspace_from_path


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
    if not standalone and getattr(root, "_scene_image_gui_built", False):
        return
    if not standalone:
        setattr(root, "_scene_image_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_3 sceneImage {__version__}",
        minsize=(780, 560),
        geometry="960x700",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    png_default = cfg.get("png_dir") or str(default_png_dir())
    url_default = cfg.get("genspark_url") or GENSPARK_AI_IMAGE_URL
    script_default = cfg.get("scene_script") or ""
    if not script_default.strip():
        sf = default_script_file()
        if sf and sf.is_file():
            try:
                script_default = sf.read_text(encoding="utf-8-sig")
            except OSError:
                script_default = ""

    cred_email, cred_pw = load_credentials()
    png_var = tk.StringVar(value=png_default)
    url_var = tk.StringVar(value=url_default)
    email_var = tk.StringVar(value=cred_email)
    pw_var = tk.StringVar(value=cred_pw)
    status_var = tk.StringVar(
        value="씬 스크립트 입력 후 「브라우저 열기」— 로그인·생성·png 저장까지 진행합니다."
    )
    scene_var = tk.StringVar(value="")
    busy = {"v": False}
    scenes: list[SceneLine] = []
    collected: list[tuple[int | None, str]] = []

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(3, weight=1)

    def persist() -> None:
        save_gui_settings(
            png_dir=png_var.get().strip(),
            genspark_url=url_var.get().strip(),
            scene_script=script_txt.get("1.0", tk.END),
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
        for b in (
            btn_browser,
            btn_start,
            btn_all,
            btn_collect,
            btn_save,
            btn_parse,
            btn_next,
        ):
            try:
                b.configure(state=state)
            except tk.TclError:
                pass

    # --- paths ---
    path_fr = ttk.LabelFrame(frm, text="경로", padding=(8, 6))
    path_fr.grid(row=0, column=0, sticky="ew", pady=(0, 8))
    path_fr.grid_columnconfigure(1, weight=1)

    def pick_png() -> None:
        init = folder_dialog_initial(
            Path(png_var.get()) if png_var.get().strip() else default_png_dir()
        )
        p = filedialog.askdirectory(parent=root, title="png 저장 폴더", initialdir=init)
        if p:
            png_var.set(p)
            touch_workspace_from_path(p)
            persist()

    ttk.Label(path_fr, text="png 폴더", width=12).grid(row=0, column=0, sticky="w")
    png_ent = ttk.Entry(path_fr, textvariable=png_var)
    png_ent.grid(row=0, column=1, sticky="ew", padx=(4, 6), pady=2)
    ttk.Button(path_fr, text="찾기…", width=8, command=pick_png).grid(
        row=0, column=2, sticky="e"
    )
    bind_path_entry_dnd(png_ent, png_var, mode="dir")
    bind_path_row_dnd(png_ent, path_fr, png_var, mode="dir")

    ttk.Label(path_fr, text="브라우저 주소", width=12).grid(row=1, column=0, sticky="w")
    url_ent = ttk.Entry(path_fr, textvariable=url_var)
    url_ent.grid(row=1, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2)

    ttk.Label(path_fr, text="Chrome 계정", width=12).grid(row=2, column=0, sticky="w")
    ttk.Entry(path_fr, textvariable=email_var).grid(
        row=2, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2
    )
    ttk.Label(path_fr, text="비밀번호(선택)", width=12).grid(row=3, column=0, sticky="w")
    ttk.Entry(path_fr, textvariable=pw_var, show="*").grid(
        row=3, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2
    )

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

    def profile_dir() -> Path:
        base = Path(__file__).resolve().parents[1] / "dist"
        if not standalone:
            try:
                from wisdom_root import resolve_wisdom_root

                base = resolve_wisdom_root() / "2_3_sceneImage" / "dist"
            except Exception:
                pass
        base.mkdir(parents=True, exist_ok=True)
        return image_profile_dir(base)

    def reload_scenes() -> None:
        nonlocal scenes
        text = script_txt.get("1.0", tk.END)
        scenes = parse_scene_script(text)
        scene_list.delete(0, tk.END)
        for sc in scenes:
            scene_list.insert(tk.END, sc.list_label())
        if scenes:
            idx = 0
            raw = cfg.get("scene_index", "0")
            try:
                idx = max(0, min(len(scenes) - 1, int(raw)))
            except ValueError:
                idx = 0
            scene_list.selection_set(idx)
            on_scene_select()
            set_status(f"씬 {len(scenes)}개 파싱됨 · 예: {scenes[0].png_name}")
        else:
            scene_var.set("")
            set_status("SRT_XXX: 형식의 씬 스크립트가 없습니다.")
        persist()

    def open_browser() -> None:
        """ChromeDebug(9222) 열기 → 자동 로그인 → 씬 생성 → SRT_XXX.png 저장."""
        if busy["v"]:
            return
        url = preferred_genspark_url(url_var.get().strip())
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
                root,
                "showwarning",
                "2_3 sceneImage",
                "계정 이메일을 입력하세요.",
            )
            return
        reload_scenes()
        png_dir = Path(png_var.get().strip())
        if not png_dir:
            safe_messagebox(root, "showwarning", "2_3 sceneImage", "png 폴더를 지정하세요.")
            return
        persist()
        pipe = load_pipeline_config()
        model_sel = load_model_selector()
        model_texts = model_name_variants(str(pipe.get("model") or "Nano Banana Pro"))
        all_scenes = list(scenes)
        skipped = [sc for sc in all_scenes if png_already_exists(png_dir, sc.sec)]
        todo = [sc for sc in all_scenes if not png_already_exists(png_dir, sc.sec)]
        url = (url_var.get().strip() or str(pipe.get("genspark_url") or url)).strip()

        def work() -> None:
            try:
                import time

                if skipped:
                    append_image_log(
                        png_dir,
                        "기존 PNG 건너뜀 — "
                        + ", ".join(s.png_name for s in skipped),
                    )
                if not todo and all_scenes:
                    def all_skip() -> None:
                        set_busy(False)
                        set_status(
                            f"모두 존재 — 건너뜀 {len(skipped)}개 → {png_dir}"
                        )
                        safe_messagebox(
                            root,
                            "showinfo",
                            "2_3 sceneImage",
                            f"PNG 폴더에 이미 있어 생성을 건너뛰었습니다.\n"
                            f"건너뜀 {len(skipped)}개\n{png_dir}",
                        )

                    safe_after(root, all_skip)
                    return

                info = open_browser_for_account(url, email=email)
                time.sleep(2.5)

                if not has_playwright():
                    msg = (
                        f"ChromeDebug 열림 (port {info.get('debug_port')} · "
                        f"{info.get('user_data')}). Playwright 없음 — 수동 생성하세요."
                    )
                    safe_after(root, lambda: (set_status(msg), set_busy(False)))
                    return

                sess = get_image_session(profile_dir())
                result = sess.open_and_select_model(
                    url=url,
                    model_selector=model_sel,
                    email=email,
                    password=password,
                    model_texts=model_texts,
                )
                logged_in = bool(isinstance(result, dict) and result.get("logged_in"))
                filled = bool(isinstance(result, dict) and result.get("login_filled"))
                model_ok = bool(isinstance(result, dict) and result.get("model_auto"))
                append_image_log(
                    png_dir,
                    f"세션 준비 — login={'OK' if logged_in else '재시도'} "
                    f"filled={filled} model={pipe.get('model')} "
                    f"ChromeDebug={info.get('user_data')} port={info.get('debug_port')} "
                    f"skip={len(skipped)} todo={len(todo)}",
                )

                if not todo:
                    msg = (
                        f"ChromeDebug:{info.get('debug_port')} · {email} · "
                        f"로그인 {'OK' if logged_in else '확인'} "
                        f"(자동입력 {'함' if filled else '세션유지'}) · "
                        f"{pipe.get('model')} {'선택됨' if model_ok else '수동'} · "
                        "씬 스크립트 입력 후 「이미지 생성」"
                    )
                    safe_after(root, lambda: (set_status(msg), set_busy(False)))
                    return

                saved_n = 0
                retry_n = int(pipe.get("retry_count") or 3)
                retry_wait = int(pipe.get("retry_wait_sec") or 30)
                gen_timeout = int(pipe.get("generate_timeout_sec") or 180)
                for i, sc in enumerate(todo):
                    if png_already_exists(png_dir, sc.sec):
                        append_image_log(png_dir, f"{sc.label} 건너뜀 (기존 PNG)")
                        continue
                    safe_after(
                        root,
                        lambda s=sc, n=i: set_status(
                            f"생성 {n + 1}/{len(todo)} — {s.label} "
                            f"(완료대기·재시도 {retry_n}회)…"
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
                            try_model_select=(i == 0 and not model_ok),
                            retry_count=retry_n,
                            retry_wait_sec=retry_wait,
                            generate_timeout_sec=gen_timeout,
                        )
                        paths = list((out or {}).get("saved") or [])
                        saved_n += len(paths)
                        append_image_log(
                            png_dir,
                            f"{sc.label} 생성 완료 (attempt={(out or {}).get('attempt')})\n"
                            + "\n".join(paths),
                        )
                    except Exception as scene_err:
                        append_image_log(png_dir, f"{sc.label} 실패: {scene_err}")
                        raise

                def done() -> None:
                    set_busy(False)
                    set_status(
                        f"완료 — 저장 {saved_n} · 건너뜀 {len(skipped)} → {png_dir}"
                    )
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_3 sceneImage",
                        f"저장 {saved_n}개 · 기존 PNG 건너뜀 {len(skipped)}개\n{png_dir}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)
                try:
                    append_image_log(png_dir, f"오류: {err}")
                except Exception:
                    pass

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_3 sceneImage", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(
            f"ChromeDebug(9222) · {email} · 세션/자동로그인 준비 중…"
        )
        threading.Thread(target=work, daemon=True).start()

    def _submit_scene(sc: SceneLine) -> None:
        url = preferred_genspark_url(url_var.get().strip())
        model_sel = load_model_selector()
        persist()

        if not has_playwright():
            try:
                root.clipboard_clear()
                root.clipboard_append(sc.prompt)
            except tk.TclError:
                pass
            open_browser_for_manual_login(url, profile_dir())
            set_status(
                f"{sc.label} 프롬프트를 클립보드에 복사했습니다. "
                "Nano Banana Pro 선택 후 Ctrl+V → 생성하세요."
            )
            return

        def work() -> None:
            try:
                sess = get_image_session(profile_dir())
                result = sess.submit_prompt(
                    url=url,
                    prompt=sc.prompt,
                    model_selector=model_sel,
                    try_model_select=True,
                )
                model_ok = bool(
                    isinstance(result, dict) and result.get("model_auto")
                )
                if model_ok:
                    msg = (
                        f"{sc.label} 전송 완료 (Nano Banana Pro). "
                        "생성 후 「이미지 수집」→「저장」"
                    )
                else:
                    msg = (
                        f"{sc.label} 전송 완료 (모델 수동 확인). "
                        "생성 후 「이미지 수집」→「저장」"
                    )
                safe_after(root, lambda: (set_status(msg), set_busy(False)))
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_3 sceneImage", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(f"{sc.label} — Nano Banana Pro로 이미지 생성 중…")
        threading.Thread(target=work, daemon=True).start()

    def start_generation() -> None:
        if busy["v"]:
            return
        reload_scenes()
        sc = selected_scene()
        if sc is None:
            safe_messagebox(
                root, "showwarning", "2_3 sceneImage", "씬을 선택하거나 스크립트를 입력하세요."
            )
            return
        png_dir = Path(png_var.get().strip())
        if png_dir and png_already_exists(png_dir, sc.sec):
            set_status(f"{sc.label} 건너뜀 — 기존 {sc.png_name}")
            safe_messagebox(
                root,
                "showinfo",
                "2_3 sceneImage",
                f"이미 존재합니다. 재생성하지 않습니다.\n{png_dir / sc.png_name}",
            )
            return
        _submit_scene(sc)

    def generate_all() -> None:
        if busy["v"]:
            return
        reload_scenes()
        if not scenes:
            safe_messagebox(
                root, "showwarning", "2_3 sceneImage", "씬 스크립트가 없습니다."
            )
            return
        pipe = load_pipeline_config()
        url = preferred_genspark_url(
            url_var.get().strip() or str(pipe.get("genspark_url") or "")
        )
        model_sel = load_model_selector()
        model_texts = model_name_variants(str(pipe.get("model") or "Nano Banana Pro"))
        png_dir = Path(png_var.get().strip())
        if not png_dir:
            safe_messagebox(root, "showwarning", "2_3 sceneImage", "png 폴더를 지정하세요.")
            return
        if not has_playwright():
            safe_messagebox(
                root,
                "showinfo",
                "2_3 sceneImage",
                "전체 생성에는 Playwright가 필요합니다.\n"
                "씬을 하나씩 「이미지 생성」하세요.",
            )
            return
        persist()
        all_scenes = list(scenes)
        skipped = [sc for sc in all_scenes if png_already_exists(png_dir, sc.sec)]
        todo = [sc for sc in all_scenes if not png_already_exists(png_dir, sc.sec)]
        retry_n = int(pipe.get("retry_count") or 3)
        retry_wait = int(pipe.get("retry_wait_sec") or 30)
        gen_timeout = int(pipe.get("generate_timeout_sec") or 180)

        if skipped:
            append_image_log(
                png_dir,
                "기존 PNG 건너뜀 — " + ", ".join(s.png_name for s in skipped),
            )
        if not todo:
            set_status(f"모두 존재 — 건너뜀 {len(skipped)}개 → {png_dir}")
            safe_messagebox(
                root,
                "showinfo",
                "2_3 sceneImage",
                f"PNG 폴더에 이미 있어 생성을 건너뛰었습니다.\n"
                f"건너뜀 {len(skipped)}개\n{png_dir}",
            )
            return

        def work() -> None:
            try:
                sess = get_image_session(profile_dir())
                saved_n = 0
                for i, sc in enumerate(todo):
                    if png_already_exists(png_dir, sc.sec):
                        append_image_log(png_dir, f"{sc.label} 건너뜀 (기존 PNG)")
                        continue
                    safe_after(
                        root,
                        lambda s=sc, n=i: set_status(
                            f"전체 생성 {n + 1}/{len(todo)} — {s.label}…"
                        ),
                    )
                    out = sess.run_scene_with_retry(
                        url=url,
                        prompt=sc.prompt,
                        png_dir=png_dir,
                        srt_sec=sc.sec,
                        model_selector=model_sel,
                        model_texts=model_texts,
                        try_model_select=(i == 0),
                        retry_count=retry_n,
                        retry_wait_sec=retry_wait,
                        generate_timeout_sec=gen_timeout,
                    )
                    paths = list((out or {}).get("saved") or [])
                    saved_n += len(paths)
                    append_image_log(
                        png_dir,
                        f"{sc.label} 생성 완료\n" + "\n".join(paths),
                    )

                def done() -> None:
                    set_busy(False)
                    set_status(
                        f"전체 생성 완료 — 저장 {saved_n} · 건너뜀 {len(skipped)} → {png_dir}"
                    )
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_3 sceneImage",
                        f"저장 {saved_n}개 · 기존 PNG 건너뜀 {len(skipped)}개\n{png_dir}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)
                try:
                    append_image_log(png_dir, f"전체 생성 오류: {err}")
                except Exception:
                    pass

                def fail() -> None:
                    set_busy(False)
                    set_status(f"전체 생성 오류: {err}")
                    safe_messagebox(root, "showerror", "2_3 sceneImage", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(
            f"전체 생성 — {len(todo)}개 남음 (건너뜀 {len(skipped)})…"
        )
        threading.Thread(target=work, daemon=True).start()

    def collect_images() -> None:
        if busy["v"]:
            return
        if not has_playwright():
            safe_messagebox(
                root,
                "showinfo",
                "2_3 sceneImage",
                "이미지 자동 수집에는 Playwright가 필요합니다.",
            )
            return

        def work() -> None:
            nonlocal collected
            try:
                sess = get_image_session(profile_dir())
                items = sess.collect_images(wait_ms=3000)
                collected = items

                def done() -> None:
                    set_busy(False)
                    link_list.delete(0, tk.END)
                    for sec, url in items:
                        label = f"SRT_{sec:03d}" if sec is not None else "(번호미정)"
                        short = url if len(url) < 90 else url[:87] + "…"
                        link_list.insert(tk.END, f"{label}  |  {short}")
                    if items:
                        set_status(f"이미지 URL {len(items)}개 수집됨 → 「저장」")
                    else:
                        set_status(
                            "이미지 URL을 찾지 못했습니다. "
                            "생성이 끝난 뒤 다시 「이미지 수집」하세요."
                        )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"수집 오류: {err}")
                    safe_messagebox(root, "showerror", "2_3 sceneImage", err)

                safe_after(root, fail)

        set_busy(True)
        set_status("페이지에서 이미지 URL 수집 중…")
        threading.Thread(target=work, daemon=True).start()

    def save_images_to_png() -> None:
        if busy["v"]:
            return
        if not collected:
            safe_messagebox(
                root,
                "showwarning",
                "2_3 sceneImage",
                "먼저 「이미지 수집」으로 URL을 모으세요.",
            )
            return
        png_dir = Path(png_var.get().strip())
        if not png_dir:
            safe_messagebox(root, "showwarning", "2_3 sceneImage", "png 폴더를 지정하세요.")
            return
        sc = selected_scene()
        fb = [s.sec for s in scenes] if scenes else None
        default_sec = sc.sec if sc else (scenes[0].sec if scenes else None)
        persist()

        def work() -> None:
            try:
                if has_playwright():
                    sess = get_image_session(profile_dir())
                    saved_paths = sess.download_via_page(
                        list(collected),
                        png_dir,
                        fallback_secs=fb,
                        default_start_sec=default_sec,
                    )
                    n = len(saved_paths)
                else:
                    paths = save_images(
                        list(collected),
                        png_dir,
                        fallback_secs=fb,
                        default_start_sec=default_sec,
                    )
                    n = len(paths)

                def done() -> None:
                    set_busy(False)
                    set_status(f"{n}개 저장 완료 → {png_dir}")
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_3 sceneImage",
                        f"{n}개 이미지를 저장했습니다.\n{png_dir}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"저장 오류: {err}")
                    safe_messagebox(root, "showerror", "2_3 sceneImage", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(f"이미지 {len(collected)}개 저장 중…")
        threading.Thread(target=work, daemon=True).start()

    def next_scene() -> None:
        sel = scene_list.curselection()
        i = int(sel[0]) + 1 if sel else 0
        if i >= len(scenes):
            set_status("마지막 씬입니다.")
            return
        scene_list.selection_clear(0, tk.END)
        scene_list.selection_set(i)
        scene_list.see(i)
        on_scene_select()
        start_generation()

    btn_browser = ttk.Button(act, text="브라우저 열기", command=open_browser)
    btn_browser.pack(side=tk.LEFT, padx=(0, 6))
    btn_start = ttk.Button(act, text="이미지 생성", command=start_generation)
    btn_start.pack(side=tk.LEFT, padx=(0, 6))
    btn_all = ttk.Button(act, text="전체 생성·저장", command=generate_all)
    btn_all.pack(side=tk.LEFT, padx=(0, 6))
    btn_collect = ttk.Button(act, text="이미지 수집", command=collect_images)
    btn_collect.pack(side=tk.LEFT, padx=(0, 6))
    btn_save = ttk.Button(act, text="저장", command=save_images_to_png)
    btn_save.pack(side=tk.LEFT, padx=(0, 6))
    btn_next = ttk.Button(act, text="다음 씬", command=next_scene)
    btn_next.pack(side=tk.LEFT, padx=(0, 6))
    btn_parse = ttk.Button(act, text="스크립트 파싱", command=reload_scenes)
    btn_parse.pack(side=tk.LEFT)

    ttk.Label(frm, textvariable=scene_var).grid(row=2, column=0, sticky="w", pady=(0, 4))

    # --- main panes ---
    paned = ttk.Panedwindow(frm, orient=tk.VERTICAL)
    paned.grid(row=3, column=0, sticky="nsew")

    script_fr = ttk.LabelFrame(paned, text="씬 스크립트 (SRT_XXX: …)", padding=4)
    lists_fr = ttk.Frame(paned)
    paned.add(script_fr, weight=2)
    paned.add(lists_fr, weight=2)

    script_fr.grid_columnconfigure(0, weight=1)
    script_fr.grid_rowconfigure(0, weight=1)
    script_txt = tk.Text(script_fr, wrap=tk.WORD, height=10)
    script_sb = ttk.Scrollbar(script_fr, orient=tk.VERTICAL, command=script_txt.yview)
    script_txt.configure(yscrollcommand=script_sb.set)
    script_txt.grid(row=0, column=0, sticky="nsew")
    script_sb.grid(row=0, column=1, sticky="ns")
    if script_default.strip():
        script_txt.insert("1.0", script_default)

    lists_fr.grid_columnconfigure(0, weight=1)
    lists_fr.grid_columnconfigure(1, weight=1)
    lists_fr.grid_rowconfigure(0, weight=1)

    left = ttk.LabelFrame(lists_fr, text="파싱된 씬", padding=4)
    right = ttk.LabelFrame(lists_fr, text="수집된 이미지 링크", padding=4)
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
        scene_var.set(f"{sc.label} → {sc.png_name}  |  {len(sc.prompt)}자")
        persist()

    scene_list.bind("<<ListboxSelect>>", on_scene_select)

    ttk.Label(frm, textvariable=status_var).grid(row=4, column=0, sticky="ew", pady=(8, 0))
    tip = (
        "흐름: 씬 스크립트 → 브라우저 열기 "
        "(storageState 세션 → 모델 선택 → 생성완료대기·재시도 → png/SRT_XXX.png · log/image.log)"
    )
    ttk.Label(frm, text=tip, foreground="#555").grid(row=5, column=0, sticky="w", pady=(4, 0))

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    root.after(150, reload_scenes)
    run_mainloop(root, standalone)
