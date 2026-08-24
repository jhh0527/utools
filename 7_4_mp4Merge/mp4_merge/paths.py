# -*- coding: utf-8 -*-
"""기본 경로."""

from __future__ import annotations

from pathlib import Path

from wisdom_workspace import workspace_module_output

MODULE = "7_4_mp4Merge"
ALL_MP4_NAME = "all.mp4"
MERGE_LOG_NAME = "all.merge.log"
WORK_DIR_NAME = "_merge_work"


def default_mp4_folder() -> Path:
    return workspace_module_output(MODULE)
