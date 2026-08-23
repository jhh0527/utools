# -*- coding: utf-8 -*-
"""등록 MP4 재생·합성 모드 — 마지막 장면 유지 / 반복 · 음소거."""

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

MP4_MUTE_OFF = "sound"
MP4_MUTE_ON = "mute"

MP4_MUTE_OPTIONS: tuple[tuple[str, str], ...] = (
    (MP4_MUTE_OFF, "소리"),
    (MP4_MUTE_ON, "음소거"),
)

MP4_MUTE_LABELS: dict[str, str] = {k: v for k, v in MP4_MUTE_OPTIONS}
MP4_MUTE_BY_LABEL: dict[str, str] = {v: k for k, v in MP4_MUTE_OPTIONS}
MP4_MUTE_LABELS_LIST: tuple[str, ...] = tuple(v for _, v in MP4_MUTE_OPTIONS)


def normalize_mp4_play_mode(value: str | None) -> str:
    v = (value or MP4_MODE_LOOP).strip().lower()
    if v in MP4_MODE_LABELS:
        return v
    if v in MP4_MODE_BY_LABEL:
        return MP4_MODE_BY_LABEL[v]
    return MP4_MODE_LOOP


def mp4_play_mode_label(value: str | None) -> str:
    return MP4_MODE_LABELS.get(normalize_mp4_play_mode(value), "반복")


def normalize_mp4_mute(value: str | bool | None) -> str:
    if isinstance(value, bool):
        return MP4_MUTE_ON if value else MP4_MUTE_OFF
    v = (value or MP4_MUTE_OFF).strip().lower()
    if v in MP4_MUTE_LABELS:
        return v
    if v in MP4_MUTE_BY_LABEL:
        return MP4_MUTE_BY_LABEL[v]
    if v in ("1", "true", "yes", "on", "silent", "muted"):
        return MP4_MUTE_ON
    if v in ("0", "false", "no", "off", "audio"):
        return MP4_MUTE_OFF
    return MP4_MUTE_OFF


def mp4_mute_label(value: str | bool | None) -> str:
    return MP4_MUTE_LABELS.get(normalize_mp4_mute(value), "소리")


def is_mp4_muted(value: str | bool | None) -> bool:
    return normalize_mp4_mute(value) == MP4_MUTE_ON
