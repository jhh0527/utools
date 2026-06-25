# -*- coding: utf-8 -*-
"""원본 대본 vs STT 결과 diff (tk Text 태그)."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

import tkinter as tk


@dataclass
class DiffStats:
    equal_chars: int = 0
    diff_chars: int = 0
    missing_chars: int = 0
    extra_chars: int = 0

    @property
    def match_ratio(self) -> float:
        total = self.equal_chars + self.diff_chars + self.missing_chars + self.extra_chars
        if total <= 0:
            return 100.0
        return round(100.0 * self.equal_chars / total, 1)


def normalize_for_compare(text: str) -> str:
    """비교용 공백 정리."""
    return re.sub(r"\s+", " ", (text or "").strip())


def apply_diff_to_text(
    widget: tk.Text,
    original: str,
    transcribed: str,
    *,
    compare_normalized: bool = True,
) -> DiffStats:
    """STT 결과를 Text에 넣고 원본과 다른 구간을 색으로 표시합니다."""
    widget.configure(state=tk.NORMAL)
    widget.delete("1.0", tk.END)

    stats = DiffStats()
    if compare_normalized:
        left = normalize_for_compare(original)
        right = normalize_for_compare(transcribed)
    else:
        left = original or ""
        right = transcribed or ""

    sm = difflib.SequenceMatcher(None, left, right)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        chunk = right[j1:j2]
        if tag == "equal":
            widget.insert(tk.END, chunk)
            stats.equal_chars += len(chunk)
        elif tag == "replace":
            widget.insert(tk.END, chunk, ("diff_rep",))
            stats.diff_chars += max(i2 - i1, j2 - j1)
        elif tag == "insert":
            widget.insert(tk.END, chunk, ("diff_ins",))
            stats.extra_chars += len(chunk)
        elif tag == "delete":
            widget.insert(tk.END, f"⟨{left[i1:i2]}⟩", ("diff_del",))
            stats.missing_chars += i2 - i1

    if not right.strip() and left.strip():
        widget.insert(tk.END, "(STT 결과 없음)", ("diff_rep",))

    widget.configure(state=tk.DISABLED)
    return stats


def configure_diff_tags(widget: tk.Text) -> None:
    widget.tag_configure("diff_rep", background="#ffcdd2", foreground="#b71c1c")
    widget.tag_configure("diff_ins", background="#fff9c4", foreground="#f57f17")
    widget.tag_configure("diff_del", background="#e1bee7", foreground="#6a1b9a")
