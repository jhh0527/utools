# -*- coding: utf-8 -*-
"""기본 스캔 기준 (wisdom 루트)."""

from __future__ import annotations

from pathlib import Path

from wisdom_root import resolve_wisdom_root


def default_scan_root() -> Path:
    return resolve_wisdom_root()
