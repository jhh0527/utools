"""장면 리스트를 순회해 이미지 파일로 저장합니다."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path

from prompt2image.backends.base import ImageBackend
from prompt2image.prompt_parser import Scene


def generate_scenes(
    scenes: Sequence[Scene],
    backend: ImageBackend,
    out_dir: Path,
    *,
    file_prefix: str = "",
    on_progress: Callable[[int, int, Scene, Path | None, Exception | None], None] | None = None,
    stop_check: Callable[[], bool] | None = None,
) -> list[Path]:
    """선택한 장면을 순서대로 합성합니다. 실패한 장면은 건너뜁니다."""
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total = len(scenes)
    for i, scene in enumerate(scenes, start=1):
        if stop_check is not None and stop_check():
            break

        target = out_dir / f"{file_prefix}{scene.safe_stem}{backend.file_ext}"
        try:
            data = backend.generate(scene.prompt, negative=scene.negative)
            target.write_bytes(data)
            saved.append(target)
            if on_progress is not None:
                on_progress(i, total, scene, target, None)
        except Exception as e:
            if on_progress is not None:
                on_progress(i, total, scene, None, e)
    return saved
