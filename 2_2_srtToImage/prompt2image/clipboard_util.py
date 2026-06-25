# -*- coding: utf-8 -*-
"""클립보드 복사."""

from __future__ import annotations

import tkinter as tk


def copy_to_clipboard(host: tk.Misc, text: str) -> None:
    host.clipboard_clear()
    host.clipboard_append(text)
    host.update_idletasks()
