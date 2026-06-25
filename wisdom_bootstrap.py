# -*- coding: utf-8 -*-
"""run_*_gui 진입점 — ``wisdom_root`` import 전 sys.path 설정."""

from __future__ import annotations

import sys
from pathlib import Path


def run(entry_file: str | Path) -> Path:
    """열린 wisdom 폴더를 찾아 작업 디렉터리·경로 기준으로 설정."""
    entry = Path(entry_file).resolve().parent
    for base in [Path.cwd(), entry.parent, entry, *entry.parents]:
        if (base / "wisdom_root.py").is_file():
            s = str(base)
            if s not in sys.path:
                sys.path.insert(0, s)
            break
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        mp = str(meipass)
        if mp not in sys.path:
            sys.path.insert(0, mp)
    from wisdom_root import install

    return install()
