# -*- coding: utf-8 -*-
"""모듈 GUI — 단독 창(Tk) 또는 wisdom 허브 탭(Frame) 에 붙일 때 공통 처리."""

from __future__ import annotations

from typing import Callable

import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk

_hub_shutting_down = False


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
    """Notebook 탭 글꼴·패딩 — 허브·모듈 공통."""
    try:
        f = tkfont.nametofont("TkDefaultFont")
        fam = f.actual("family")
        base_sz = max(10, int(f.actual("size")))
    except tk.TclError:
        fam, base_sz = "맑은 고딕", 10
    sz = font_size if font_size is not None else max(12, base_sz + 2)
    style = ttk.Style(host)
    style.configure("TNotebook.Tab", font=(fam, sz), padding=(20, 4))


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
