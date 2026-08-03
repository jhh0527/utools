# -*- coding: utf-8 -*-
"""이미지 생성 로그 — log/image.log."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def log_dir_for_png(png_dir: Path) -> Path:
    """png 폴더와 형제 log/ 또는 png 상위/log."""
    png_dir = Path(png_dir)
    parent = png_dir.parent
    # …/png → …/log , 그 외 → png_dir/log
    if png_dir.name.lower() == "png":
        d = parent / "log"
    else:
        d = png_dir / "log"
    d.mkdir(parents=True, exist_ok=True)
    return d


def append_image_log(png_dir: Path, message: str) -> None:
    path = log_dir_for_png(png_dir) / "image.log"
    ts = datetime.now().strftime("%H:%M")
    line = f"{ts}\n{message.strip()}\n\n"
    try:
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass
