"""Windows에서 ffmpeg/ffprobe 등 자식 프로세스 콘솔(검은 창)이 뜨지 않도록 subprocess 래퍼."""

from __future__ import annotations

import subprocess
import sys
from typing import Any, Sequence

_WIN_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def subprocess_run_no_window(
    cmd: Sequence[str],
    **kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    if sys.platform == "win32" and _WIN_NO_WINDOW:
        cf = int(kwargs.pop("creationflags", 0))
        kwargs["creationflags"] = cf | _WIN_NO_WINDOW
    return subprocess.run(cmd, **kwargs)
