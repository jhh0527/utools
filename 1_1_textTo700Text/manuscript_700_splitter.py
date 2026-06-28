#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""대본을 줄바꿈 없이 700자 단위(문장 종결 기준)로 나눠 여러 UTF-8 .txt로 저장합니다.

자르는 우선순위:
1) 700자 윈도우 안의 마지막 마침표(`.`) 또는 물음표(`?`) 직후
2) 위 둘이 없으면 같은 윈도우 안의 마지막 콤마(`,`) 직후
3) 그것도 없으면 700자를 초과해서라도 최초로 나오는 마침표/물음표 직후
4) 끝까지 종결 부호가 더 없으면 끝까지 한 청크

따라서 각 chunk 는 700자보다 짧거나 길 수 있으며, 항상 문장 종결 직후에서 끝납니다.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

CHUNK_SIZE = 700
PROJECT_DIRNAME = "1_1_textTo700Text"
OUTPUT_DIRNAME = "output"


def _ensure_wisdom_on_path(from_file: str | Path) -> None:
    for base in [Path.cwd(), *Path(from_file).resolve().parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            return
    raise ImportError("wisdom_root.py not found — wisdom 폴더를 워크스페이스 루트로 여세요.")


_ensure_wisdom_on_path(__file__)
from wisdom_root import bootstrap, module_output
from wisdom_workspace import resolve_module_output


def resolve_output_dir() -> Path:
    """``{작업폴더}/1_1_textTo700Text/output`` 또는 wisdom 기본."""
    return resolve_module_output(PROJECT_DIRNAME)


SENTENCE_END_CHARS = ".?"
FALLBACK_BREAK_CHARS = ","


def flatten_for_chunking(text: str) -> str:
    """줄바꿈·캐리지리턴을 제거한 뒤 공백 포함 연속 문자열로 만듭니다."""
    return text.replace("\r\n", "\n").replace("\r", "\n").replace("\n", "")


def count_chars_with_spaces(text: str) -> int:
    """편집기 본문 기준 공백 포함 글자 수."""
    return len(text)


def count_chars_flattened(text: str) -> int:
    """분할 저장 시 사용되는 연속 문자열(줄바꿈 제거)의 공백 포함 글자 수."""
    return len(flatten_for_chunking(text))


def _text_widget_content(widget) -> str:
    """Tk Text 위젯 본문(끝의 자동 개행 제외)."""
    return widget.get("1.0", "end-1c")


def _rfind_any(flat: str, chars: str, start: int, end: int) -> int:
    """flat[start:end] 안에서 chars 중 어느 글자든 가장 오른쪽 위치를 반환합니다.

    찾지 못하면 -1.
    """
    best = -1
    for ch in chars:
        p = flat.rfind(ch, start, end)
        if p > best:
            best = p
    return best


def _find_first_any(flat: str, chars: str, start: int) -> int:
    """flat[start:] 안에서 chars 중 어느 글자든 가장 왼쪽 위치를 반환합니다.

    찾지 못하면 -1.
    """
    best = -1
    for ch in chars:
        p = flat.find(ch, start)
        if p != -1 and (best == -1 or p < best):
            best = p
    return best


def _next_chunk_end(flat: str, start: int, size: int) -> int:
    """다음 chunk 의 끝 인덱스(=다음 chunk 의 시작 인덱스)를 반환합니다.

    - 남은 길이가 size 이하면 끝까지 한 번에 자릅니다(마지막 청크).
    - 그 외에는 [start, start+size) 윈도우 내 마지막 마침표/물음표 직후,
      없으면 마지막 콤마 직후,
      그것도 없으면 size 를 초과해서라도 최초의 마침표/물음표 직후,
      그것조차 끝까지 없으면 끝까지(마지막 청크) 반환합니다.
    """
    n = len(flat)
    if n - start <= size:
        return n
    window_end = start + size
    pos = _rfind_any(flat, SENTENCE_END_CHARS, start, window_end)
    if pos >= start:
        return pos + 1
    pos = _rfind_any(flat, FALLBACK_BREAK_CHARS, start, window_end)
    if pos >= start:
        return pos + 1
    pos = _find_first_any(flat, SENTENCE_END_CHARS, window_end)
    if pos != -1:
        return pos + 1
    return n


def split_into_chunks(text: str, size: int = CHUNK_SIZE) -> list[str]:
    """줄바꿈을 무시한 연속 문자열을 최대 size자씩, 문장 종결 기준으로 잘라 반환합니다."""
    if size <= 0:
        raise ValueError("size는 1 이상이어야 합니다.")
    if not text:
        return []
    flat = flatten_for_chunking(text)
    if not flat:
        return []
    chunks: list[str] = []
    i = 0
    n = len(flat)
    while i < n:
        j = _next_chunk_end(flat, i, size)
        chunk = flat[i:j].lstrip()
        if chunk:
            chunks.append(chunk)
        i = j
    return chunks


def write_chunk_files(chunks: list[str], out_dir: Path, stem: str) -> list[Path]:
    """chunks 를 out_dir 에 `{stem}{N}.txt` 형식으로 저장하고 경로 목록을 반환합니다.

    예) stem="part" → part1.txt, part2.txt, …
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    paths: list[Path] = []
    for idx, body in enumerate(chunks, start=1):
        name = f"{stem}{idx}.txt"
        path = out_dir / name
        path.write_text(body, encoding="utf-8", newline="\n")
        paths.append(path)
    return paths


def run_gui(*, container: tk.Misc | None = None) -> int:
    import threading
    import tkinter as tk
    from tkinter import filedialog, messagebox, font as tkfont
    from tkinter import ttk

    from genspark_chat import (
        chat_profile_dir,
        open_genspark_chat_in_chrome,
        run_submit_search_sync,
    )
    from wisdom_gui_host import (
        apply_window_chrome,
        bind_hub_destroy,
        bind_text_widget_file_dnd,
        run_mainloop,
        safe_after,
        tk_host,
    )

    root, standalone = tk_host(container)
    apply_window_chrome(
        root,
        standalone,
        title=f"대본 {CHUNK_SIZE}자 분할 저장 (문장 종결 기준)",
        minsize=(560, 520),
        geometry="760x620",
    )

    try:
        default_font = tkfont.nametofont("TkTextFont")
        text_font = (default_font.actual("family"), max(10, default_font.actual("size")))
    except tk.TclError:
        text_font = ("맑은 고딕", 11)

    output_dir = resolve_output_dir()
    output_dir.mkdir(parents=True, exist_ok=True)
    stem_var = tk.StringVar(value="part")

    frm = tk.Frame(root, padx=10, pady=8)
    frm.grid(row=0, column=0, sticky="nsew")
    root.grid_rowconfigure(0, weight=1)
    root.grid_columnconfigure(0, weight=1)
    frm.grid_rowconfigure(1, weight=1)
    frm.grid_columnconfigure(0, weight=1)

    ttk.Label(frm, text="대본 (붙여넣기 또는 아래에서 파일 불러오기)").grid(row=0, column=0, sticky="w")
    text = tk.Text(frm, wrap=tk.WORD, undo=True, font=text_font, padx=6, pady=6)
    scroll_y = tk.Scrollbar(frm, command=text.yview)
    text.configure(yscrollcommand=scroll_y.set)
    text.grid(row=1, column=0, sticky="nsew", pady=(4, 8))
    scroll_y.grid(row=1, column=1, sticky="ns", pady=(4, 8))

    row_opts = ttk.Frame(frm)
    row_opts.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(0, 6))
    row_opts.grid_columnconfigure(1, weight=1)

    ttk.Label(row_opts, text="저장 폴더(고정)").grid(row=0, column=0, sticky="nw", padx=(0, 6))
    ttk.Label(
        row_opts,
        text=str(output_dir.resolve()),
        wraplength=520,
        justify=tk.LEFT,
    ).grid(row=0, column=1, columnspan=2, sticky="ew")

    ttk.Label(row_opts, text="파일 이름 접두사").grid(row=1, column=0, sticky="w", padx=(0, 6), pady=(6, 0))
    ttk.Entry(row_opts, textvariable=stem_var).grid(row=1, column=1, columnspan=2, sticky="ew", pady=(6, 0))

    row_btns = ttk.Frame(frm)
    row_btns.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(4, 6))

    char_count_var = tk.StringVar(value="공백 포함 글자수: 0  |  분할 기준(줄바꿈 제거): 0")
    ttk.Label(frm, textvariable=char_count_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(0, 4))

    genspark_frm = ttk.LabelFrame(frm, text="Genspark 채팅 (사실 검증)", padding=(6, 4))
    genspark_frm.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(0, 8))
    genspark_frm.grid_columnconfigure(0, weight=1)

    ttk.Label(genspark_frm, text="검색어").grid(row=0, column=0, sticky="w")
    search_txt = tk.Text(genspark_frm, height=3, wrap=tk.WORD, font=text_font, padx=4, pady=4)
    search_txt.grid(row=1, column=0, sticky="ew", pady=(2, 6))

    genspark_btns = ttk.Frame(genspark_frm)
    genspark_btns.grid(row=2, column=0, sticky="w")
    _genspark_busy = {"open": False, "search": False}

    def _set_status(msg: str) -> None:
        status.config(text=msg)

    def _copy_search_clipboard(text: str) -> None:
        root.clipboard_clear()
        root.clipboard_append(text)
        root.update_idletasks()

    def open_chat_browser() -> None:
        try:
            open_genspark_chat_in_chrome()
        except Exception as e:
            messagebox.showerror("브라우저", str(e))
            _set_status(f"브라우저 열기 실패: {e}")
            return
        _set_status(
            "Chrome에서 Genspark 채팅을 열었습니다. "
            "검색어 조회: 자동 전송 또는 클립보드 복사 후 Ctrl+V"
        )

    def do_search_query() -> None:
        if _genspark_busy["search"]:
            return
        query = search_txt.get("1.0", "end-1c").strip()
        if not query:
            messagebox.showwarning("검색어", "검색어 입력란에 내용을 입력하세요.")
            return
        _genspark_busy["search"] = True
        btn_search.configure(state=tk.DISABLED)
        profile = chat_profile_dir(output_dir)

        def work() -> None:
            err: Exception | None = None
            mode = ""
            try:
                mode = run_submit_search_sync(
                    profile,
                    query,
                    on_status=lambda m: safe_after(root, lambda msg=m: _set_status(msg)),
                    copy_for_manual=_copy_search_clipboard,
                )
            except Exception as ex:
                err = ex

            def done() -> None:
                _genspark_busy["search"] = False
                try:
                    btn_search.configure(state=tk.NORMAL)
                except tk.TclError:
                    pass
                if err:
                    messagebox.showerror("검색어 조회", str(err))
                    _set_status(f"검색어 조회 실패: {err}")
                elif mode == "manual":
                    messagebox.showinfo(
                        "검색어 조회",
                        "검색어를 클립보드에 복사했습니다.\n"
                        "열린 Genspark 채팅 입력란에 Ctrl+V 로 붙여넣으세요.",
                    )
                    _set_status("검색어 복사 · Chrome 열림 — Ctrl+V 로 붙여넣기")
                else:
                    _set_status("Genspark 채팅에 검색어를 전송했습니다.")

            safe_after(root, done)

        _set_status("Genspark 채팅에 검색어 전송 중…")
        threading.Thread(target=work, daemon=True).start()

    btn_browser = ttk.Button(genspark_btns, text="브라우저 열기", command=open_chat_browser)
    btn_browser.pack(side=tk.LEFT, padx=(0, 8))
    btn_search = ttk.Button(genspark_btns, text="검색어 조회", command=do_search_query)
    btn_search.pack(side=tk.LEFT)

    status = tk.Label(frm, anchor=tk.W, justify=tk.LEFT, relief=tk.SUNKEN, padx=6, pady=4)

    def update_char_count(_event=None) -> None:
        body = _text_widget_content(text)
        char_count_var.set(
            f"공백 포함 글자수: {count_chars_with_spaces(body)}  |  "
            f"분할 기준(줄바꿈 제거): {count_chars_flattened(body)}"
        )

    def load_file() -> None:
        path = filedialog.askopenfilename(
            title="대본 열기",
            filetypes=[("텍스트", "*.txt"), ("마크다운", "*.md"), ("모든 파일", "*.*")],
        )
        if not path:
            return
        p = Path(path)
        try:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            messagebox.showerror("열기 오류", str(e))
            return
        text.delete("1.0", tk.END)
        text.insert("1.0", data)
        if not stem_var.get().strip():
            stem_var.set(p.stem)
        update_char_count()

    def _on_manuscript_drop(p: Path, _c: str) -> None:
        if not stem_var.get().strip():
            stem_var.set(p.stem)
        update_char_count()

    bind_text_widget_file_dnd(text, extensions=(".txt", ".md"), on_loaded=_on_manuscript_drop)
    root.after_idle(lambda: bind_text_widget_file_dnd(search_txt, extensions=(".txt", ".md")))

    text.bind("<KeyRelease>", update_char_count)
    text.bind("<<Paste>>", lambda _e: root.after_idle(update_char_count))

    def do_split_save() -> None:
        body = _text_widget_content(text)
        if not body.strip():
            messagebox.showwarning("내용 없음", "저장할 대본이 비어 있습니다.")
            return
        stem = stem_var.get().strip() or "part"
        bad = set('<>:"/\\|?*')
        if any(c in stem for c in bad):
            messagebox.showerror(
                "이름 오류",
                f'파일 이름에 사용할 수 없는 문자가 있습니다: {", ".join(sorted(bad & set(stem)))}',
            )
            return
        odir = resolve_output_dir()
        odir.mkdir(parents=True, exist_ok=True)
        try:
            chunks = split_into_chunks(body, CHUNK_SIZE)
            paths = write_chunk_files(chunks, odir, stem)
        except OSError as e:
            messagebox.showerror("저장 오류", str(e))
            return
        status.config(text=f"{len(paths)}개 파일 저장: {paths[0].parent}")
        messagebox.showinfo("완료", f"{len(paths)}개 파일을 저장했습니다.\n{odir.resolve()}")

    ttk.Button(row_btns, text="텍스트 파일 불러오기…", command=load_file).pack(side=tk.LEFT, padx=(0, 8))
    ttk.Button(
        row_btns,
        text=f"최대 {CHUNK_SIZE}자 (문장 종결 기준) 분할 저장",
        command=do_split_save,
    ).pack(side=tk.LEFT)

    status.grid(row=6, column=0, columnspan=2, sticky="ew")
    frm.grid_rowconfigure(6, weight=0)

    status.config(
        text=(
            f"대기 중 — 최대 {CHUNK_SIZE}자 안에서 마침표/물음표(없으면 콤마) 직후로 끊어 "
            f"{output_dir} 에 저장합니다."
        ),
    )
    update_char_count()
    if not standalone:
        bind_hub_destroy(root, lambda: None)
    run_mainloop(root, standalone)
    return 0


def run_cli(in_path: Path, out_dir: Path, stem: str) -> int:
    try:
        body = in_path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        print(f"읽기 오류: {e}", file=sys.stderr)
        return 1
    if not body.strip():
        print("내용이 비어 있습니다.", file=sys.stderr)
        return 1
    chunks = split_into_chunks(body, CHUNK_SIZE)
    try:
        paths = write_chunk_files(chunks, out_dir, stem)
    except OSError as e:
        print(f"저장 오류: {e}", file=sys.stderr)
        return 1
    for p in paths:
        print(p)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            f"대본을 줄바꿈 제거 후 최대 {CHUNK_SIZE}자 안에서 마침표/물음표(없으면 콤마) "
            "직후로 끊어 여러 UTF-8 .txt 로 저장합니다. 인자 없이 실행하면 편집 창이 열립니다."
        ),
    )
    parser.add_argument("input", nargs="?", type=Path, help="입력 텍스트 파일 (지정 시 콘솔만 사용)")
    parser.add_argument(
        "-o",
        "--out-dir",
        type=Path,
        default=None,
        help=f"출력 폴더 (기본: {PROJECT_DIRNAME}/{OUTPUT_DIRNAME})",
    )
    parser.add_argument(
        "-n",
        "--name",
        default="part",
        help="저장 파일 접두사 (기본: part) — 예) part + 1 → part1.txt",
    )
    parser.add_argument(
        "-g",
        "--gui",
        action="store_true",
        help="입력 파일이 있어도 GUI를 엽니다",
    )
    args = parser.parse_args()
    bootstrap()
    out = args.out_dir if args.out_dir is not None else resolve_output_dir()
    out.mkdir(parents=True, exist_ok=True)

    if args.gui or args.input is None:
        return run_gui()
    return run_cli(args.input, out, args.name)


if __name__ == "__main__":
    raise SystemExit(main())
