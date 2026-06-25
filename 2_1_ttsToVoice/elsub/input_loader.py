# -*- coding: utf-8 -*-
"""입력 폴더의 TTS 텍스트 파일을 knowledgetts 블록으로 합칩니다."""

from __future__ import annotations

from pathlib import Path


def load_tts_text_from_dir(folder: Path) -> str:
    """``folder`` 아래 ``*.txt`` 를 파일명 순으로 이어 붙입니다."""
    root = folder.expanduser().resolve()
    if not root.is_dir():
        raise FileNotFoundError(f"입력 폴더가 없습니다: {root}")
    txts = sorted(root.glob("*.txt"), key=lambda p: p.name.lower())
    if not txts:
        raise FileNotFoundError(f"입력 폴더에 .txt 파일이 없습니다: {root}")
    return "\n".join(t.read_text(encoding="utf-8") for t in txts)
