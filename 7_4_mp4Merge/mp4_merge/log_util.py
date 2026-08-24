# -*- coding: utf-8 -*-
"""병합 로그 — dist 디버그 + 폴더 all.merge.log."""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path
from typing import Callable

from mp4_merge.settings import config_path

LOG_NAME = "mp4_merge_debug.log"


def log_path() -> Path:
    return config_path().parent / LOG_NAME


def log_file_display() -> str:
    return str(log_path())


def mp4_merge_log(message: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}\n"
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def mp4_merge_log_exc(prefix: str, exc: BaseException) -> None:
    mp4_merge_log(f"{prefix}: {exc}")
    mp4_merge_log(traceback.format_exc().rstrip())


class MergeSessionLog:
    """폴더 쪽 세션 로그 + 콜백 + dist 디버그."""

    def __init__(
        self,
        folder_log: Path | None = None,
        *,
        on_line: Callable[[str], None] | None = None,
    ) -> None:
        self.folder_log = Path(folder_log) if folder_log else None
        self.on_line = on_line
        if self.folder_log is not None:
            try:
                self.folder_log.parent.mkdir(parents=True, exist_ok=True)
                self.folder_log.write_text("", encoding="utf-8")
            except OSError:
                self.folder_log = None

    def line(self, message: str) -> None:
        msg = (message or "").rstrip()
        if not msg:
            return
        mp4_merge_log(msg)
        if self.on_line:
            try:
                self.on_line(msg)
            except Exception:
                pass
        if self.folder_log is None:
            return
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with self.folder_log.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except OSError:
            pass
