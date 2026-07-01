# -*- coding: utf-8 -*-
"""기본 경로."""

from __future__ import annotations

from pathlib import Path

from wisdom_workspace import workspace_module_output

MODULE = "7_2_mp4Edit"


def default_output_dir() -> Path:
    return workspace_module_output(MODULE) / "download"
