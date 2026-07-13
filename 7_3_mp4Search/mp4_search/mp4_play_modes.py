# -*- coding: utf-8 -*-
"""등록 MP4 재생·합성 모드 — 마지막 장면 유지 / 반복."""

from __future__ import annotations

MP4_MODE_HOLD = "hold"
MP4_MODE_LOOP = "loop"

MP4_MODE_OPTIONS: tuple[tuple[str, str], ...] = (
    (MP4_MODE_HOLD, "유지"),
    (MP4_MODE_LOOP, "반복"),
)

MP4_MODE_LABELS: dict[str, str] = {k: v for k, v in MP4_MODE_OPTIONS}
MP4_MODE_BY_LABEL: dict[str, str] = {v: k for k, v in MP4_MODE_OPTIONS}
MP4_MODE_LABELS_LIST: tuple[str, ...] = tuple(v for _, v in MP4_MODE_OPTIONS)


def normalize_mp4_play_mode(value: str | None) -> str:
    v = (value or MP4_MODE_LOOP).strip().lower()
    if v in MP4_MODE_LABELS:
        return v
    if v in MP4_MODE_BY_LABEL:
        return MP4_MODE_BY_LABEL[v]
    return MP4_MODE_LOOP


def mp4_play_mode_label(value: str | None) -> str:
    return MP4_MODE_LABELS.get(normalize_mp4_play_mode(value), "반복")
