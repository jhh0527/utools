#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CLI 실행 파일 진입점."""

from __future__ import annotations

import sys
import traceback


def _pause_on_crash() -> None:
    if not getattr(sys, "frozen", False):
        return
    try:
        input("\n오류가 발생했습니다. Enter 키를 누르면 종료합니다...")
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    try:
        from prompt2image.cli import main

        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        _pause_on_crash()
        raise SystemExit(1)
