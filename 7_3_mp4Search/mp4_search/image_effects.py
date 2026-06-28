# -*- coding: utf-8 -*-
"""PNG 오버레이 효과 — 합성 시 줌인·줌아웃."""

from __future__ import annotations

PNG_EFFECT_FIXED = "fixed"
PNG_EFFECT_ZOOM_IN = "zoom_in"
PNG_EFFECT_ZOOM_OUT = "zoom_out"

PNG_EFFECT_OPTIONS: tuple[tuple[str, str], ...] = (
    (PNG_EFFECT_FIXED, "고정"),
    (PNG_EFFECT_ZOOM_IN, "줌인"),
    (PNG_EFFECT_ZOOM_OUT, "줌아웃"),
)

PNG_EFFECT_LABELS: dict[str, str] = {k: v for k, v in PNG_EFFECT_OPTIONS}
PNG_EFFECT_BY_LABEL: dict[str, str] = {v: k for k, v in PNG_EFFECT_OPTIONS}
PNG_EFFECT_LABELS_LIST: tuple[str, ...] = tuple(v for _, v in PNG_EFFECT_OPTIONS)


def normalize_png_effect(value: str | None) -> str:
    v = (value or PNG_EFFECT_FIXED).strip().lower()
    if v in PNG_EFFECT_LABELS:
        return v
    if v in PNG_EFFECT_BY_LABEL:
        return PNG_EFFECT_BY_LABEL[v]
    return PNG_EFFECT_FIXED


def png_effect_label(value: str | None) -> str:
    return PNG_EFFECT_LABELS.get(normalize_png_effect(value), "고정")


def _overlay_base_scale(w: int, h: int) -> str:
    """배경 MP4 — 캔버스 꽉 차게."""
    return (
        f"[0:v]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},setsar=1[base];"
    )


def _overlay_image_scale(w: int, h: int) -> str:
    """오버레이 이미지 — 전체가 보이도록 맞춤(레터박스)."""
    return (
        f"[1:v]scale={w}:{h}:force_original_aspect_ratio=decrease,"
        f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1[img];"
    )


def image_overlay_filters(
    w: int,
    h: int,
    *,
    effect: str = PNG_EFFECT_FIXED,
    duration_sec: float = 5.0,
    fps: int = 30,
) -> list[str]:
    """ffmpeg filter_complex — MP4 + 이미지 오버레이 (캔버스 크기 통일)."""
    w = max(16, int(w))
    h = max(16, int(h))
    effect = normalize_png_effect(effect)
    base = _overlay_base_scale(w, h)
    img = _overlay_image_scale(w, h)
    tail = "[base][img]overlay=0:0:format=auto,setsar=1[vout]"
    fixed = [base + img + tail]
    if effect == PNG_EFFECT_FIXED:
        return fixed

    frames = max(2, int(round(max(0.2, float(duration_sec)) * fps)))
    step = 0.15 / frames
    z_max = 1.0 + frames * step
    if effect == PNG_EFFECT_ZOOM_IN:
        z_expr = f"min(1+on*{step:.8f},{z_max:.4f})"
    else:
        z_expr = f"max({z_max:.4f}-on*{step:.8f},1)"
    inner_w = max(w + 2, int(w * 1.6))
    inner_h = max(h + 2, int(h * 1.6))
    animated = (
        base
        + f"[1:v]scale={inner_w}:{inner_h}:force_original_aspect_ratio=decrease,"
        f"pad={inner_w}:{inner_h}:(ow-iw)/2:(oh-ih)/2:color=black@0,"
        f"zoompan=z='{z_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={frames}:s={w}x{h}:fps={fps},"
        f"setsar=1[img];"
        + tail
    )
    return [animated, *fixed]


def image_effect_needs_loop(effect: str) -> bool:
    return normalize_png_effect(effect) != PNG_EFFECT_FIXED
