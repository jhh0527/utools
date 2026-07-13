# -*- coding: utf-8 -*-
"""2_2_imgDown GUI — SRT → Genspark AI 이미지 → png/SRT_XXX.png."""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, font as tkfont, messagebox, ttk

from img_down import __version__
from img_down.download import save_images
from img_down.genspark_image import (
    GENSPARK_GPT_IMAGE_2_URL,
    build_submit_text,
    get_image_session,
    has_playwright,
    image_profile_dir,
    open_browser_for_manual_login,
    preferred_genspark_url,
)
from img_down.paths import (
    FIXED_PROMPT,
    default_guide_file,
    default_png_dir,
    default_srt_file,
)
from img_down.settings import load_gui_settings, load_model_selector, save_gui_settings
from img_down.srt_chunks import SrtChunk, load_chunks, load_timeline, srt_png_name
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
    if not standalone and getattr(root, "_img_down_gui_built", False):
        return
    if not standalone:
        setattr(root, "_img_down_gui_built", True)

    apply_window_chrome(
        root,
        standalone,
        title=f"2_2 imgDown {__version__}",
        minsize=(760, 520),
        geometry="920x640",
    )
    fam, sz = _default_font()
    root.option_add("*Font", (fam, sz))

    cfg = load_gui_settings()
    srt_default = cfg.get("srt_file") or (
        str(default_srt_file()) if default_srt_file() else ""
    )
    png_default = cfg.get("png_dir") or str(default_png_dir())
    guide_default = cfg.get("guide_file") or str(default_guide_file())
    url_default = cfg.get("genspark_url") or GENSPARK_GPT_IMAGE_2_URL

    srt_var = tk.StringVar(value=srt_default)
    png_var = tk.StringVar(value=png_default)
    guide_var = tk.StringVar(value=guide_default)
    url_var = tk.StringVar(value=url_default)
    status_var = tk.StringVar(
        value="「브라우저 열기」로 Genspark·구글 인증을 수동 입력한 뒤 「이미지 생성 시작」하세요."
    )
    chunk_var = tk.StringVar(value="")
    timeline_var = tk.StringVar(value="SRT 타임라인: (파일 미지정)")
    busy = {"v": False}
    chunks: list[SrtChunk] = []
    collected: list[tuple[int | None, str]] = []
    page_collected: list[tuple[str, str | None]] = []

    frm = ttk.Frame(root, padding=10)
    frm.pack(fill=tk.BOTH, expand=True)
    frm.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(4, weight=1)

    def persist() -> None:
        save_gui_settings(
            srt_file=srt_var.get().strip(),
            png_dir=png_var.get().strip(),
            guide_file=guide_var.get().strip(),
            genspark_url=url_var.get().strip(),
            chunk_index=str(max(0, chunk_list.curselection()[0]) if chunk_list.curselection() else 0),
        )

    def set_status(msg: str) -> None:
        status_var.set(msg)

    def set_busy(v: bool) -> None:
        busy["v"] = v
        state = tk.DISABLED if v else tk.NORMAL
        for b in (
            btn_browser,
            btn_start,
            btn_collect,
            btn_addr_download,
            btn_save,
            btn_reload,
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

    def _row(r: int, label: str, var: tk.StringVar, pick, *, mode: str = "file") -> ttk.Entry:
        ttk.Label(path_fr, text=label, width=10).grid(row=r, column=0, sticky="w")
        ent = ttk.Entry(path_fr, textvariable=var)
        ent.grid(row=r, column=1, sticky="ew", padx=(4, 6), pady=2)
        ttk.Button(path_fr, text="찾기…", width=8, command=pick).grid(
            row=r, column=2, sticky="e"
        )
        drop_mode = "dir" if mode == "dir" else "file"
        ext = (".srt",) if label.startswith("SRT") else ()
        bind_path_entry_dnd(ent, var, mode=drop_mode, extensions=ext)
        bind_path_row_dnd(ent, path_fr, var, mode=drop_mode, extensions=ext)
        return ent

    def pick_srt() -> None:
        init = folder_dialog_initial(
            Path(srt_var.get()) if srt_var.get().strip() else default_srt_file()
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="SRT 대본 선택",
            initialdir=init,
            filetypes=[("SRT", "*.srt"), ("모든 파일", "*.*")],
        )
        if p:
            srt_var.set(p)
            touch_workspace_from_path(p)
            reload_chunks()
            persist()

    def pick_png() -> None:
        init = folder_dialog_initial(
            Path(png_var.get()) if png_var.get().strip() else default_png_dir()
        )
        p = filedialog.askdirectory(parent=root, title="png 저장 폴더", initialdir=init)
        if p:
            png_var.set(p)
            touch_workspace_from_path(p)
            persist()

    def pick_guide() -> None:
        init = folder_dialog_initial(
            Path(guide_var.get()) if guide_var.get().strip() else default_guide_file()
        )
        p = filedialog.askopenfilename(
            parent=root,
            title="지침 파일 선택",
            initialdir=init,
            filetypes=[("텍스트", "*.txt;*.md"), ("모든 파일", "*.*")],
        )
        if p:
            guide_var.set(p)
            persist()

    _row(0, "SRT 대본", srt_var, pick_srt)
    _row(1, "png 폴더", png_var, pick_png, mode="dir")
    _row(2, "지침 MD", guide_var, pick_guide)
    ttk.Label(path_fr, text="브라우저 주소", width=10).grid(row=3, column=0, sticky="w")
    url_ent = ttk.Entry(path_fr, textvariable=url_var)
    url_ent.grid(row=3, column=1, columnspan=2, sticky="ew", padx=(4, 0), pady=2)

    timeline_fr = ttk.LabelFrame(frm, text="SRT 타임라인", padding=(8, 4))
    timeline_fr.grid(row=1, column=0, sticky="ew", pady=(0, 6))
    ttk.Label(timeline_fr, textvariable=timeline_var, wraplength=860).pack(
        anchor=tk.W, fill=tk.X
    )

    # --- actions ---
    act = ttk.Frame(frm)
    act.grid(row=2, column=0, sticky="ew", pady=(0, 6))

    def selected_chunk() -> SrtChunk | None:
        sel = chunk_list.curselection()
        if not sel:
            return None
        i = int(sel[0])
        if 0 <= i < len(chunks):
            return chunks[i]
        return None

    def profile_dir() -> Path:
        base = Path(__file__).resolve().parents[1] / "dist"
        if not standalone:
            try:
                from wisdom_root import resolve_wisdom_root

                base = resolve_wisdom_root() / "2_2_imgDown" / "dist"
            except Exception:
                pass
        base.mkdir(parents=True, exist_ok=True)
        return image_profile_dir(base)

    def open_browser() -> None:
        if busy["v"]:
            return
        user_url = url_var.get().strip()
        url = user_url or GENSPARK_GPT_IMAGE_2_URL
        persist()

        def work() -> None:
            try:
                open_browser_for_manual_login(url, profile_dir())
                msg = (
                    "Chrome이 열렸습니다. Genspark·구글 인증정보를 수동으로 입력하세요. "
                    "완료 후 「이미지 생성 시작」을 누르세요."
                )
                safe_after(root, lambda: (set_status(msg), set_busy(False)))
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 imgDown", err)

                safe_after(root, fail)

        set_busy(True)
        set_status("브라우저 여는 중… (구글 수동 인증)")
        threading.Thread(target=work, daemon=True).start()

    def download_address_images() -> None:
        if busy["v"]:
            return
        url = url_var.get().strip()
        if not url:
            safe_messagebox(root, "showwarning", "2_2 imgDown", "브라우저 주소를 입력하세요.")
            return
        if not (url.startswith("http://") or url.startswith("https://")):
            safe_messagebox(
                root,
                "showwarning",
                "2_2 imgDown",
                "주소는 http:// 또는 https:// 로 시작해야 합니다.",
            )
            return
        png_dir = Path(png_var.get().strip())
        if not png_dir:
            safe_messagebox(root, "showwarning", "2_2 imgDown", "png 폴더를 지정하세요.")
            return
        if not has_playwright():
            safe_messagebox(
                root,
                "showinfo",
                "2_2 imgDown",
                "주소 이미지 자동 다운로드에는 Playwright가 필요합니다.",
            )
            return
        persist()

        def work() -> None:
            nonlocal page_collected
            try:
                sess = get_image_session(profile_dir())
                items = sess.collect_page_images(url=url, wait_ms=3000)
                page_collected = items
                saved = sess.download_named_via_page(items, png_dir)

                def done() -> None:
                    set_busy(False)
                    link_list.delete(0, tk.END)
                    for i, (img_url, hint) in enumerate(items, start=1):
                        name = hint or f"image_{i:03d}.png"
                        short = img_url if len(img_url) < 90 else img_url[:87] + "…"
                        link_list.insert(tk.END, f"{name}  |  {short}")
                    set_status(f"주소 이미지 {len(saved)}개 저장 완료 → {png_dir}")
                    safe_messagebox(
                        root,
                        "showinfo",
                        "2_2 imgDown",
                        f"{len(saved)}개 이미지를 저장했습니다.\n{png_dir}",
                    )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"주소 이미지 저장 오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 imgDown", err)

                safe_after(root, fail)

        set_busy(True)
        set_status("브라우저 주소의 이미지 수집·저장 중…")
        threading.Thread(target=work, daemon=True).start()

    def start_generation() -> None:
        if busy["v"]:
            return
        ch = selected_chunk()
        if ch is None:
            safe_messagebox(root, "showwarning", "2_2 imgDown", "청크를 선택하세요.")
            return
        user_url = url_var.get().strip()
        url = preferred_genspark_url(user_url)
        guide = Path(guide_var.get().strip()) if guide_var.get().strip() else None
        model_sel = load_model_selector()
        persist()

        if not has_playwright():
            text = build_submit_text(ch.as_srt_text())
            try:
                root.clipboard_clear()
                root.clipboard_append(text)
            except tk.TclError:
                pass
            open_browser_for_manual_login(url, profile_dir())
            set_status(
                "Playwright 없음 — Chrome·클립보드 복사. "
                "구글 인증·모델 선택 후 붙여넣기(Ctrl+V)하세요."
            )
            return

        def work() -> None:
            try:
                sess = get_image_session(profile_dir())
                result = sess.start_generation(
                    user_url=user_url,
                    guide_path=guide if guide and guide.is_file() else None,
                    chunk_text=ch.as_srt_text(),
                    prompt=FIXED_PROMPT,
                    attach_guide=True,
                    model_selector=model_sel,
                )
                model_auto = bool(
                    isinstance(result, dict) and result.get("model_auto")
                )
                if model_auto:
                    msg = (
                        f"청크 {ch.index + 1}/{len(chunks)} — GPT Image 2 선택·전송 완료. "
                        "생성 후 「이미지 수집」→「저장」"
                    )
                else:
                    msg = (
                        f"청크 {ch.index + 1}/{len(chunks)} — 명령어 입력란에 전송 완료 "
                        "(모델 자동 선택 실패·수동 확인). "
                        "생성 후 「이미지 수집」→「저장」"
                    )
                safe_after(root, lambda: (set_status(msg), set_busy(False)))
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 imgDown", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(f"청크 {ch.index + 1} — GPT Image 2 선택·이미지 생성 시작…")
        threading.Thread(target=work, daemon=True).start()

    def collect_images() -> None:
        if busy["v"]:
            return
        if not has_playwright():
            safe_messagebox(
                root,
                "showinfo",
                "2_2 imgDown",
                "이미지 자동 수집에는 Playwright가 필요합니다.\n"
                "pip install playwright && playwright install chromium",
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
                        set_status(
                            f"이미지 URL {len(items)}개 수집됨 → 링크 더블클릭·「저장」"
                        )
                    else:
                        set_status(
                            "실제 이미지 URL을 찾지 못했습니다. "
                            "Genspark에서 생성이 완료된 뒤 다시 「이미지 수집」하세요."
                        )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"수집 오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 imgDown", err)

                safe_after(root, fail)

        set_busy(True)
        set_status("페이지에서 이미지 URL 수집 중…")
        threading.Thread(target=work, daemon=True).start()

    def _save_kwargs() -> dict:
        ch = selected_chunk()
        fb = ch.cue_start_secs() if ch else None
        default_sec = ch.start_sec if ch else None
        return {"fallback_secs": fb, "default_start_sec": default_sec}

    def _download_items(
        items: list[tuple[int | None, str]],
        *,
        quiet: bool = False,
    ) -> None:
        if not items:
            if not quiet:
                safe_messagebox(root, "showwarning", "2_2 imgDown", "저장할 이미지가 없습니다.")
            return
        png_dir = Path(png_var.get().strip())
        if not png_dir:
            safe_messagebox(root, "showwarning", "2_2 imgDown", "png 폴더를 지정하세요.")
            return
        skw = _save_kwargs()
        persist()

        def work() -> None:
            try:
                if has_playwright():
                    sess = get_image_session(profile_dir())
                    saved_paths = sess.download_via_page(items, png_dir, **skw)
                    n = len(saved_paths)
                else:
                    paths = save_images(items, png_dir, **skw)
                    n = len(paths)

                def done() -> None:
                    set_busy(False)
                    set_status(f"{n}개 저장 완료 → {png_dir}")
                    if not quiet:
                        safe_messagebox(
                            root,
                            "showinfo",
                            "2_2 imgDown",
                            f"{n}개 이미지를 저장했습니다.\n{png_dir}",
                        )

                safe_after(root, done)
            except Exception as e:
                err = str(e)

                def fail() -> None:
                    set_busy(False)
                    set_status(f"저장 오류: {err}")
                    safe_messagebox(root, "showerror", "2_2 imgDown", err)

                safe_after(root, fail)

        set_busy(True)
        set_status(f"이미지 {len(items)}개 저장 중…")
        threading.Thread(target=work, daemon=True).start()

    def save_images_to_png() -> None:
        if busy["v"]:
            return
        if not collected:
            safe_messagebox(
                root,
                "showwarning",
                "2_2 imgDown",
                "먼저 「이미지 수집」으로 URL을 모으세요.",
            )
            return
        _download_items(list(collected))

    def next_chunk() -> None:
        sel = chunk_list.curselection()
        i = int(sel[0]) + 1 if sel else 0
        if i >= len(chunks):
            set_status("마지막 청크입니다.")
            return
        chunk_list.selection_clear(0, tk.END)
        chunk_list.selection_set(i)
        chunk_list.see(i)
        on_chunk_select()
        start_generation()

    btn_browser = ttk.Button(act, text="브라우저 열기", command=open_browser)
    btn_browser.pack(side=tk.LEFT, padx=(0, 6))
    btn_start = ttk.Button(act, text="이미지 생성 시작", command=start_generation)
    btn_start.pack(side=tk.LEFT, padx=(0, 6))
    btn_collect = ttk.Button(act, text="이미지 수집", command=collect_images)
    btn_collect.pack(side=tk.LEFT, padx=(0, 6))
    btn_addr_download = ttk.Button(act, text="주소 이미지 다운로드", command=download_address_images)
    btn_addr_download.pack(side=tk.LEFT, padx=(0, 6))
    btn_save = ttk.Button(act, text="저장", command=save_images_to_png)
    btn_save.pack(side=tk.LEFT, padx=(0, 6))
    btn_next = ttk.Button(act, text="다음 청크", command=next_chunk)
    btn_next.pack(side=tk.LEFT, padx=(0, 6))
    btn_reload = ttk.Button(act, text="청크 새로고침", command=lambda: reload_chunks())
    btn_reload.pack(side=tk.LEFT)

    ttk.Label(frm, textvariable=chunk_var).grid(row=3, column=0, sticky="w", pady=(0, 4))

    # --- lists ---
    paned = ttk.Panedwindow(frm, orient=tk.HORIZONTAL)
    paned.grid(row=4, column=0, sticky="nsew")

    left = ttk.LabelFrame(paned, text="2분 청크", padding=4)
    right = ttk.LabelFrame(paned, text="수집된 이미지 링크", padding=4)
    paned.add(left, weight=1)
    paned.add(right, weight=1)
    left.grid_columnconfigure(0, weight=1)
    left.grid_rowconfigure(0, weight=1)
    right.grid_columnconfigure(0, weight=1)
    right.grid_rowconfigure(0, weight=1)

    chunk_list = tk.Listbox(left, activestyle="dotbox", exportselection=False)
    chunk_sb = ttk.Scrollbar(left, orient=tk.VERTICAL, command=chunk_list.yview)
    chunk_list.configure(yscrollcommand=chunk_sb.set)
    chunk_list.grid(row=0, column=0, sticky="nsew")
    chunk_sb.grid(row=0, column=1, sticky="ns")

    preview = tk.Text(left, height=8, wrap=tk.WORD)
    preview.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(6, 0))

    link_list = tk.Listbox(right, activestyle="dotbox", exportselection=False)
    link_sb = ttk.Scrollbar(right, orient=tk.VERTICAL, command=link_list.yview)
    link_list.configure(yscrollcommand=link_sb.set)
    link_list.grid(row=0, column=0, sticky="nsew")
    link_sb.grid(row=0, column=1, sticky="ns")

    def on_chunk_select(_event: tk.Event | None = None) -> None:
        ch = selected_chunk()
        preview.delete("1.0", tk.END)
        if ch is None:
            chunk_var.set("")
            return
        secs = ch.cue_start_secs()
        sec_hint = (
            f" | 대본초 {secs[0]}→{srt_png_name(secs[0])} … {secs[-1]}→{srt_png_name(secs[-1])}"
            if secs
            else ""
        )
        chunk_var.set(ch.label + sec_hint)
        preview.insert("1.0", build_submit_text(ch.as_srt_text())[:4000])
        persist()

    chunk_list.bind("<<ListboxSelect>>", on_chunk_select)

    def selected_link_index() -> int | None:
        sel = link_list.curselection()
        if not sel:
            return None
        idx = int(sel[0])
        if 0 <= idx < len(collected):
            return idx
        return None

    def on_link_activate(_event: tk.Event | None = None) -> None:
        """링크 클릭(더블클릭) — 해당 이미지를 png 폴더에 저장."""
        if busy["v"]:
            return
        idx = selected_link_index()
        if idx is None:
            return
        _download_items([collected[idx]], quiet=True)

    link_list.bind("<Double-Button-1>", on_link_activate)

    def reload_chunks() -> None:
        nonlocal chunks
        path = Path(srt_var.get().strip()) if srt_var.get().strip() else None
        chunk_list.delete(0, tk.END)
        preview.delete("1.0", tk.END)
        chunks = []
        if path is None or not path.is_file():
            timeline_var.set("SRT 타임라인: (파일 미지정)")
            set_status("SRT 파일을 지정하세요.")
            chunk_var.set("")
            return
        try:
            tl = load_timeline(path)
            chunks = load_chunks(path)
        except Exception as e:
            timeline_var.set("SRT 타임라인: 파싱 오류")
            set_status(f"SRT 파싱 오류: {e}")
            return
        if tl is not None:
            timeline_var.set(tl.summary())
        else:
            timeline_var.set("SRT 타임라인: 큐 없음")
        for ch in chunks:
            chunk_list.insert(tk.END, ch.label)
        if chunks:
            idx = 0
            raw = cfg.get("chunk_index", "0")
            try:
                idx = max(0, min(len(chunks) - 1, int(raw)))
            except ValueError:
                idx = 0
            chunk_list.selection_set(idx)
            on_chunk_select()
            first = chunks[0].start_sec
            set_status(
                f"SRT 청크 {len(chunks)}개 (2분 간격) · "
                f"첫 대본초 {first} ({srt_png_name(first)})"
            )
        else:
            set_status("SRT 큐가 없습니다.")

    ttk.Label(frm, textvariable=status_var).grid(row=5, column=0, sticky="ew", pady=(8, 0))

    tip = (
        "흐름: 주소 입력 → 주소 이미지 다운로드(파일명 힌트로 png 폴더 저장) / "
        "또는 Genspark 이미지 생성 → 이미지 수집 → 저장"
    )
    ttk.Label(frm, text=tip, foreground="#555").grid(row=6, column=0, sticky="w", pady=(4, 0))

    def on_close() -> None:
        persist()

    if standalone:
        bind_close(root, standalone, on_close)
    else:
        bind_hub_destroy(root, on_close)

    if srt_var.get().strip():
        root.after(200, reload_chunks)

    run_mainloop(root, standalone)
