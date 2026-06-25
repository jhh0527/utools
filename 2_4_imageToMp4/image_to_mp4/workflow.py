# -*- coding: utf-8 -*-
"""ComfyUI AnimateDiff 기본 워크플로 (AnimateDiff Evolved + VHS 필요)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Any


def resolve_seed(seed: int) -> int:
    if seed < 0:
        return random.randint(0, 2**32 - 1)
    return seed


def build_animatediff_workflow(
    *,
    image_name: str,
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
) -> dict[str, Any]:
    """이미지 1장 → AnimateDiff → MP4 (VHS_VideoCombine)."""
    seed = resolve_seed(seed)
    frames = max(8, min(frames, 64))
    return {
        "1": {
            "class_type": "CheckpointLoaderSimple",
            "inputs": {"ckpt_name": checkpoint},
        },
        "2": {
            "class_type": "LoadImage",
            "inputs": {"image": image_name},
        },
        "3": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": positive, "clip": ["1", 1]},
        },
        "4": {
            "class_type": "CLIPTextEncode",
            "inputs": {"text": negative, "clip": ["1", 1]},
        },
        "5": {
            "class_type": "ADE_LoadAnimateDiffModel",
            "inputs": {"model_name": motion_module},
        },
        "6": {
            "class_type": "ADE_ApplyAnimateDiffModelSimple",
            "inputs": {
                "motion_model": ["5", 0],
                "start_percent": 0.0,
                "end_percent": 1.0,
                "model": ["1", 0],
            },
        },
        "7": {
            "class_type": "ADE_StandardStaticContextOptions",
            "inputs": {
                "context_length": min(16, frames),
                "context_stride": 1,
                "context_overlap": 4,
                "closed_loop": False,
                "fuse_method": "flat",
                "use_on_equal_length": False,
                "start_percent": 0.0,
                "guarantee_steps": 1,
            },
        },
        "8": {
            "class_type": "VAEEncode",
            "inputs": {"pixels": ["2", 0], "vae": ["1", 2]},
        },
        "9": {
            "class_type": "RepeatLatentBatch",
            "inputs": {"samples": ["8", 0], "amount": frames},
        },
        "10": {
            "class_type": "KSampler",
            "inputs": {
                "seed": seed,
                "steps": steps,
                "cfg": cfg,
                "sampler_name": "euler",
                "scheduler": "normal",
                "denoise": denoise,
                "model": ["6", 0],
                "positive": ["3", 0],
                "negative": ["4", 0],
                "latent_image": ["9", 0],
            },
        },
        "11": {
            "class_type": "VAEDecode",
            "inputs": {"samples": ["10", 0], "vae": ["1", 2]},
        },
        "12": {
            "class_type": "VHS_VideoCombine",
            "inputs": {
                "frame_rate": fps,
                "loop_count": 0,
                "filename_prefix": "imageToMp4",
                "format": "video/h264-mp4",
                "pix_fmt": "yuv420p",
                "crf": 19,
                "save_metadata": True,
                "pingpong": False,
                "save_output": True,
                "images": ["11", 0],
            },
        },
    }


def load_custom_workflow(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"워크플로 JSON 형식 오류: {path}")
    return data


def patch_custom_workflow(
    workflow: dict[str, Any],
    *,
    image_name: str,
    positive: str,
    negative: str,
    frames: int,
    fps: int,
    seed: int,
) -> dict[str, Any]:
    """플레이스홀더 치환 + LoadImage/CLIPTextEncode 자동 패치."""
    seed = resolve_seed(seed)
    raw = json.dumps(workflow, ensure_ascii=False)
    repl = {
        "__IMAGE__": image_name,
        "__POSITIVE__": positive,
        "__NEGATIVE__": negative,
        "__FRAMES__": str(frames),
        "__FPS__": str(fps),
        "__SEED__": str(seed),
    }
    for key, val in repl.items():
        raw = raw.replace(key, val)
    patched: dict[str, Any] = json.loads(raw)

    load_nodes = [
        n for n in patched.values() if isinstance(n, dict) and n.get("class_type") == "LoadImage"
    ]
    if load_nodes:
        load_nodes[0].setdefault("inputs", {})["image"] = image_name

    clip_nodes = [
        n for n in patched.values() if isinstance(n, dict) and n.get("class_type") == "CLIPTextEncode"
    ]
    if clip_nodes:
        clip_nodes[0].setdefault("inputs", {})["text"] = positive
    if len(clip_nodes) > 1:
        clip_nodes[1].setdefault("inputs", {})["text"] = negative

    return patched
