# -*- coding: utf-8 -*-
"""이미지 배치 → MP4 변환."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from image_to_mp4.comfyui_client import ComfyUIError, animate_image_to_mp4, check_server
from image_to_mp4.paths import list_input_images


@dataclass
class BatchResult:
    ok: list[Path]
    failed: list[tuple[Path, str]]


def run_batch(
    *,
    url: str,
    input_dir: Path,
    output_dir: Path,
    positive: str,
    negative: str,
    checkpoint: str,
    motion_module: str,
    frames: int,
    fps: int,
    seed: int,
    steps: int,
    cfg: float,
    denoise: float,
    workflow_path: Path | None = None,
    recursive: bool = False,
    on_item_start: Callable[[int, int, Path], None] | None = None,
    on_item_progress: Callable[[str], None] | None = None,
) -> BatchResult:
    if not check_server(url):
        raise ComfyUIError(
            f"ComfyUI 서버에 연결할 수 없습니다: {url}\n"
            "ComfyUI가 실행 중인지 확인하세요."
        )

    images = list_input_images(input_dir, recursive=recursive)
    if not images:
        sub = len(list_input_images(input_dir, recursive=True))
        if sub and not recursive:
            raise ComfyUIError(
                f"현재 폴더에 이미지가 없습니다: {input_dir}\n"
                f"하위 폴더에 {sub}개 있습니다. 「하위 폴더 포함」을 체크하세요."
            )
        raise ComfyUIError(f"입력 폴더에 이미지가 없습니다: {input_dir}")

    output_dir.mkdir(parents=True, exist_ok=True)
    ok: list[Path] = []
    failed: list[tuple[Path, str]] = []
    total = len(images)

    for i, img in enumerate(images, start=1):
        if on_item_start:
            on_item_start(i, total, img)

        def progress(msg: str, _img: Path = img) -> None:
            if on_item_progress:
                on_item_progress(f"[{i}/{total}] {_img.name}: {msg}")

        try:
            out = animate_image_to_mp4(
                url=url,
                image_path=img,
                output_dir=output_dir,
                positive=positive,
                negative=negative,
                checkpoint=checkpoint,
                motion_module=motion_module,
                frames=frames,
                fps=fps,
                seed=seed,
                steps=steps,
                cfg=cfg,
                denoise=denoise,
                workflow_path=workflow_path,
                on_progress=progress,
            )
            ok.append(out)
        except Exception as e:
            failed.append((img, str(e)))

    return BatchResult(ok=ok, failed=failed)
