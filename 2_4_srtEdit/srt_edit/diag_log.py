# -*- coding: utf-8 -*-
"""보정 파이프라인 진단 로그 — 파일 + GUI 리스너."""

from __future__ import annotations

import threading
from datetime import datetime
from pathlib import Path
from typing import Callable

_lock = threading.Lock()
_path: Path | None = None
_listeners: list[Callable[[str], None]] = []


def log_path() -> Path | None:
    return _path


def add_listener(cb: Callable[[str], None]) -> None:
    with _lock:
        if cb not in _listeners:
            _listeners.append(cb)


def remove_listener(cb: Callable[[str], None]) -> None:
    with _lock:
        try:
            _listeners.remove(cb)
        except ValueError:
            pass


def start_session(path: Path | str, *, title: str = "") -> Path:
    """새 세션 시작. 기존 파일에 append."""
    global _path
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock:
        _path = p
        stamp = datetime.now().isoformat(timespec="seconds")
        hdr = f"\n===== {stamp} {title} =====\n"
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(hdr)
        except OSError:
            pass
    log(f"세션 시작 → {p}")
    return p


def log(msg: str) -> None:
    line = f"{datetime.now().strftime('%H:%M:%S')} {msg}"
    with _lock:
        p = _path
        listeners = list(_listeners)
    if p is not None:
        try:
            with p.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass
    for cb in listeners:
        try:
            cb(line)
        except Exception:
            pass


def preview(text: str, *, head: int = 120, tail: int = 80) -> str:
    """한 줄 미리보기 (개행→공백)."""
    s = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    flat = " ".join(s.split())
    if len(flat) <= head + tail + 3:
        return flat
    return flat[:head] + " … " + flat[-tail:]


def write_dump(path: Path | str, text: str, *, limit: int = 800_000) -> Path | None:
    """원문 덤프 (너무 길면 앞·뒤만)."""
    p = Path(path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        raw = text or ""
        if len(raw) > limit:
            half = limit // 2
            raw = (
                raw[:half]
                + f"\n\n… [중간 생략 {len(text) - limit}자] …\n\n"
                + raw[-half:]
            )
        p.write_text(raw, encoding="utf-8")
        log(f"덤프 저장 {p} ({len(text or '')}자 → 파일 {len(raw)}자)")
        return p
    except OSError as e:
        log(f"덤프 실패 {p}: {e}")
        return None
