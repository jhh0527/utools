# -*- coding: utf-8 -*-
"""모듈 GUI — 단독 창(Tk) 또는 wisdom 허브 탭(Frame) 에 붙일 때 공통 처리."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Literal

import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

_hub_shutting_down = False
_drop_hooked: set[int] = set()

PathDropMode = Literal["dir", "file", "path"]


def is_hub_shutting_down() -> bool:
    return _hub_shutting_down


def ui_alive(root: tk.Misc, *, closing: bool = False) -> bool:
    """허브·모듈 종료 중이면 UI 갱신·팝업을 막습니다."""
    if closing or is_hub_shutting_down():
        return False
    try:
        return bool(root.winfo_exists())
    except tk.TclError:
        return False


def safe_after(root: tk.Misc, fn: Callable[[], None], *, closing: bool = False) -> None:
    """``after(0, …)`` — 허브 종료 후 새 Tk 창이 뜨지 않도록 보호합니다."""

    def wrapper() -> None:
        if not ui_alive(root, closing=closing):
            return
        try:
            fn()
        except tk.TclError:
            pass

    if not ui_alive(root, closing=closing):
        return
    try:
        root.after(0, wrapper)
    except tk.TclError:
        pass


def safe_messagebox(
    root: tk.Misc,
    kind: str,
    title: str,
    message: str,
    **kwargs: object,
) -> None:
    """허브 종료 중 ``messagebox`` 가 새 루트 창을 만들지 않도록 합니다."""
    if not ui_alive(root):
        return
    func = getattr(messagebox, kind, None)
    if func is None:
        return
    try:
        func(title, message, parent=root, **kwargs)
    except tk.TclError:
        pass


def bind_hub_destroy(root: tk.Misc, on_close: Callable[[], None]) -> None:
    """허브 탭(Frame) 에 붙은 모듈 — 허브 창 닫힐 때 정리 콜백 실행."""
    hub_root = root.winfo_toplevel()

    def _on_hub_destroy(event: tk.Event) -> None:
        if event.widget is hub_root:
            on_close()

    hub_root.bind("<Destroy>", _on_hub_destroy, add="+")


def request_shutdown(root: tk.Misc) -> None:
    """허브 종료 시 예약 콜백·Toplevel·기본 루트 정리 (다른 창이 뜨는 현상 방지)."""
    global _hub_shutting_down
    _hub_shutting_down = True
    top = root.winfo_toplevel()
    try:
        for aid in top.tk.call("after", "info"):
            try:
                top.after_cancel(aid)
            except tk.TclError:
                pass
    except tk.TclError:
        pass
    _destroy_toplevels(top)
    try:
        tk._default_root = None  # type: ignore[attr-defined]
    except Exception:
        pass


def _destroy_toplevels(widget: tk.Misc) -> None:
    for child in list(widget.winfo_children()):
        _destroy_toplevels(child)
        try:
            if child.winfo_class() == "Toplevel":
                child.destroy()
        except tk.TclError:
            pass


def configure_notebook_tabs(host: tk.Misc, *, font_size: int | None = None) -> None:
    """Notebook 탭 글꼴·패딩 — 허브·모듈 공통 (작은 굵은 글꼴로 라벨 잘림 방지)."""
    try:
        f = tkfont.nametofont("TkDefaultFont")
        fam = f.actual("family")
        raw_sz = int(f.actual("size"))
        base_sz = abs(raw_sz) if raw_sz else 9
    except tk.TclError:
        fam, base_sz = "맑은 고딕", 9
    sz = font_size if font_size is not None else max(9, base_sz - 1)
    style = ttk.Style(host)
    style.configure("TNotebook.Tab", font=(fam, sz, "bold"), padding=(12, 3))


def _decode_drop_path(raw: bytes | str) -> str:
    if isinstance(raw, str):
        return raw
    for enc in ("utf-8", "mbcs", "cp949"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def _normalize_dropped_paths(files: Sequence[bytes | str]) -> list[str]:
    out: list[str] = []
    for raw in files:
        p = _decode_drop_path(raw).strip().strip('"')
        if p:
            out.append(p)
    return out


def _read_text_file(path: Path) -> str:
    for enc in ("utf-8-sig", "utf-8", "cp949"):
        try:
            return path.read_text(encoding=enc)
        except (OSError, UnicodeDecodeError):
            continue
    return path.read_text(encoding="utf-8", errors="replace")


def _resolve_drop_path(
    raw_path: str,
    *,
    mode: PathDropMode,
    extensions: Sequence[str],
) -> str | None:
    p = Path(raw_path)
    try:
        p = p.resolve()
    except OSError:
        return None
    ext_set = {e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions}

    if mode == "dir":
        if p.is_dir():
            return str(p)
        if p.is_file():
            return str(p.parent)
        return None

    if mode == "file":
        if not p.is_file():
            return None
        if ext_set and p.suffix.lower() not in ext_set:
            return None
        return str(p)

    if p.exists():
        return str(p)
    return None


def bind_file_drop(widget: tk.Misc, on_paths: Callable[[list[str]], None]) -> None:
    """Windows 탐색기에서 파일·폴더 드롭 (미지원 환경은 무시)."""
    try:
        import windnd
    except ImportError:
        return

    def _handler(files: Sequence[bytes | str]) -> None:
        paths = _normalize_dropped_paths(files)
        if paths:
            on_paths(paths)

    def _install() -> None:
        wid = widget.winfo_id()
        if wid in _drop_hooked:
            return
        try:
            windnd.hook_dropfiles(widget, func=_handler)
            _drop_hooked.add(wid)
        except Exception:
            pass

    try:
        widget.after_idle(_install)
    except tk.TclError:
        pass


def bind_path_entry_dnd(
    entry: tk.Misc,
    var: tk.StringVar,
    *,
    mode: PathDropMode = "path",
    extensions: Sequence[str] = (),
    on_set: Callable[[str], None] | None = None,
) -> None:
    """경로 Entry 에 파일·폴더 드롭."""

    def _apply(paths: list[str]) -> None:
        target = _resolve_drop_path(paths[0], mode=mode, extensions=extensions)
        if not target:
            return
        var.set(target)
        if on_set:
            on_set(target)

    bind_file_drop(entry, _apply)


def bind_path_row_dnd(
    entry: tk.Misc,
    row: tk.Misc | None,
    var: tk.StringVar,
    *,
    mode: PathDropMode = "path",
    extensions: Sequence[str] = (),
    on_set: Callable[[str], None] | None = None,
) -> None:
    """경로 Entry 와 그 행 Frame 에 드롭 영역 연결."""
    bind_path_entry_dnd(
        entry,
        var,
        mode=mode,
        extensions=extensions,
        on_set=on_set,
    )
    if row is not None:
        bind_path_entry_dnd(
            row,
            var,
            mode=mode,
            extensions=extensions,
            on_set=on_set,
        )


def bind_text_widget_file_dnd(
    text_widget: tk.Text,
    *,
    extensions: Sequence[str] = (".txt", ".md", ".srt"),
    on_loaded: Callable[[Path, str], None] | None = None,
) -> None:
    """Text·ScrolledText 에 텍스트 파일 드롭 시 내용 로드."""

    def _apply(paths: list[str]) -> None:
        p = Path(paths[0])
        if not p.is_file():
            return
        if extensions and p.suffix.lower() not in {e.lower() for e in extensions}:
            return
        try:
            content = _read_text_file(p)
        except OSError:
            return
        text_widget.delete("1.0", tk.END)
        text_widget.insert("1.0", content)
        if on_loaded:
            on_loaded(p, content)

    bind_file_drop(text_widget, _apply)


def tk_host(container: tk.Misc | None) -> tuple[tk.Misc, bool]:
    """자식 위젯의 부모. ``standalone`` 이면 ``tk.Tk()``."""
    standalone = container is None
    host = tk.Tk() if standalone else container
    return host, standalone


def apply_window_chrome(
    host: tk.Misc,
    standalone: bool,
    *,
    title: str | None = None,
    geometry: str | None = None,
    minsize: tuple[int, int] | None = None,
) -> None:
    if not standalone:
        return
    if title:
        host.title(title)
    if minsize:
        host.minsize(*minsize)
    if geometry:
        host.geometry(geometry)


def bind_close(
    host: tk.Misc,
    standalone: bool,
    on_close: Callable[[], None],
) -> None:
    if not standalone:
        return

    def _wrapped() -> None:
        on_close()
        try:
            host.destroy()
        except tk.TclError:
            pass

    host.protocol("WM_DELETE_WINDOW", _wrapped)


def run_mainloop(host: tk.Misc, standalone: bool) -> None:
    if standalone:
        host.mainloop()
