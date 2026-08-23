# -*- coding: utf-8 -*-
"""GUI 설정 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "mp4_search_gui_config.json"


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def load_download_mp4_inputs() -> dict[str, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("download_mp4_inputs")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip():
            out[k.strip()] = v.strip()
    return out


def load_mp4_play_modes() -> dict[int, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("mp4_play_modes")
    if not isinstance(raw, dict):
        return {}
    from mp4_search.mp4_play_modes import MP4_MODE_HOLD, MP4_MODE_LOOP, normalize_mp4_play_mode

    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            n = int(str(k).strip())
        except ValueError:
            continue
        if isinstance(v, bool):
            out[n] = normalize_mp4_play_mode(MP4_MODE_LOOP if v else MP4_MODE_HOLD)
            continue
        if isinstance(v, str) and v.strip():
            out[n] = normalize_mp4_play_mode(v)
    return out


def save_mp4_play_modes(modes: dict[int, str]) -> None:
    from mp4_search.mp4_play_modes import normalize_mp4_play_mode

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError):
            base = {}
    base["mp4_play_modes"] = {
        str(k): normalize_mp4_play_mode(v) for k, v in sorted(modes.items())
    }
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_mp4_mute() -> dict[int, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("mp4_mute")
    if not isinstance(raw, dict):
        return {}
    from mp4_search.mp4_play_modes import normalize_mp4_mute

    out: dict[int, str] = {}
    for k, v in raw.items():
        try:
            n = int(str(k).strip())
        except ValueError:
            continue
        out[n] = normalize_mp4_mute(v)
    return out


def save_mp4_mute(modes: dict[int, str]) -> None:
    from mp4_search.mp4_play_modes import normalize_mp4_mute

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError):
            base = {}
    base["mp4_mute"] = {
        str(k): normalize_mp4_mute(v) for k, v in sorted(modes.items())
    }
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_mp4_mute_files() -> dict[str, str]:
    """파일명(소문자) → 음소거 — 폴더 병합(``1장.mp4`` 등)용."""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("mp4_mute_files")
    if not isinstance(raw, dict):
        return {}
    from mp4_search.mp4_play_modes import normalize_mp4_mute

    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip():
            out[k.strip().lower()] = normalize_mp4_mute(v)
    return out


def save_mp4_mute_files(modes: dict[str, str]) -> None:
    from mp4_search.mp4_play_modes import normalize_mp4_mute

    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError):
            base = {}
    base["mp4_mute_files"] = {
        str(k).lower(): normalize_mp4_mute(v) for k, v in sorted(modes.items())
    }
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_download_mp4_inputs(inputs: dict[str, str]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError):
            base = {}
    base["download_mp4_inputs"] = inputs
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_gui_settings() -> dict[str, str]:
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in (
        "srt_file",
        "mp4_dir",
        "download_dir",
        "mp3_file",
        "preview_pane_width",
        "announcer_file",
    ):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    pl = data.get("play_loop")
    if isinstance(pl, bool):
        out["play_loop"] = "1" if pl else "0"
    elif isinstance(pl, str) and pl.strip():
        out["play_loop"] = pl.strip()
    else:
        out["play_loop"] = "0"
    if "burn_subtitles" in data:
        out["burn_subtitles"] = "1" if bool(data.get("burn_subtitles")) else "0"
    else:
        out["burn_subtitles"] = "1"
    if "add_announcer" in data:
        out["add_announcer"] = "1" if bool(data.get("add_announcer")) else "0"
    else:
        out["add_announcer"] = "1"
    if "folder_merge" in data:
        out["folder_merge"] = "1" if bool(data.get("folder_merge")) else "0"
    else:
        out["folder_merge"] = "0"
    return out


def save_gui_settings(
    *,
    srt_file: str = "",
    mp4_dir: str = "",
    download_dir: str = "",
    mp3_file: str = "",
    preview_pane_width: str = "",
    play_loop: bool | None = None,
    burn_subtitles: bool | None = None,
    add_announcer: bool | None = None,
    announcer_file: str | None = None,
    folder_merge: bool | None = None,
) -> None:
    p = config_path()
    data: dict = {}
    if p.is_file():
        try:
            old = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(old, dict):
                data = old
        except (OSError, json.JSONDecodeError):
            pass
    if srt_file.strip():
        data["srt_file"] = srt_file.strip()
    if mp4_dir.strip():
        data["mp4_dir"] = mp4_dir.strip()
    if download_dir.strip():
        data["download_dir"] = download_dir.strip()
    if mp3_file.strip():
        data["mp3_file"] = mp3_file.strip()
    if preview_pane_width.strip().isdigit():
        data["preview_pane_width"] = int(preview_pane_width.strip())
    if play_loop is not None:
        data["play_loop"] = bool(play_loop)
    if burn_subtitles is not None:
        data["burn_subtitles"] = bool(burn_subtitles)
    if add_announcer is not None:
        data["add_announcer"] = bool(add_announcer)
    if announcer_file is not None:
        data["announcer_file"] = str(announcer_file).strip()
    if folder_merge is not None:
        data["folder_merge"] = bool(folder_merge)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
