# -*- coding: utf-8 -*-
"""7_2_mp4Edit 디버그 로그 — exe 옆 dist/mp4_edit_debug.log."""

from __future__ import annotations

import traceback
from datetime import datetime
from pathlib import Path

from mp4_edit.settings import config_path

LOG_NAME = "mp4_edit_debug.log"


def log_path() -> Path:
    return config_path().parent / LOG_NAME


def log_file_display() -> str:
    return str(log_path())


def mp4_edit_log(message: str) -> None:
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        line = f"[{ts}] {message}\n"
        p = log_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def mp4_edit_log_exc(prefix: str, exc: BaseException) -> None:
    mp4_edit_log(f"{prefix}: {exc}")
    mp4_edit_log(traceback.format_exc().rstrip())
