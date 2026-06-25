# -*- coding: utf-8 -*-
"""GUI 마지막 사용 경로 저장."""

from __future__ import annotations

import json
import sys
from pathlib import Path

CONFIG_NAME = "png_rename_gui_config.json"


def _is_legacy_png_dir(path: str) -> bool:
    """예전 기본값 ``2_2_srtToImage/output``."""
    try:
        parts = {p.lower() for p in Path(path).resolve().parts}
    except OSError:
        return False
    return (
        ("4_srttoimage" in parts or "2_2_srttoimage" in parts) and "output" in parts
    )


def config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / CONFIG_NAME
    return Path(__file__).resolve().parents[1] / "dist" / CONFIG_NAME


def ensure_default_settings() -> None:
    """설정 파일이 없을 때 SRT·기본 PNG 폴더를 미리 기록."""
    p = config_path()
    if p.is_file():
        return
    from png_rename.paths import default_png_dir, default_srt_file

    try:
        save_gui_settings(
            srt_file=str(default_srt_file()),
            png_dir=str(default_png_dir()),
        )
    except OSError:
        pass


def load_gui_settings() -> dict[str, str]:
    ensure_default_settings()
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("srt_file", "png_dir", "download_dir"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    pw = data.get("preview_pane_width")
    if isinstance(pw, int) and pw >= 200:
        out["preview_pane_width"] = str(pw)
    elif isinstance(pw, str) and pw.isdigit() and int(pw) >= 200:
        out["preview_pane_width"] = pw
    ts = data.get("preview_thumb_size")
    if isinstance(ts, int) and 80 <= ts <= 1200:
        out["preview_thumb_size"] = str(ts)
    elif isinstance(ts, str) and ts.isdigit() and 80 <= int(ts) <= 1200:
        out["preview_thumb_size"] = ts

    from png_rename.paths import default_png_dir, default_srt_file

    migrated = False
    if "png_dir" in out:
        if _is_legacy_png_dir(out["png_dir"]):
            out["png_dir"] = str(default_png_dir())
            migrated = True

    if migrated:
        try:
            pw = out.get("preview_pane_width")
            preview_pane_width = int(pw) if pw and str(pw).isdigit() else None
            ts = out.get("preview_thumb_size")
            preview_thumb_size = int(ts) if ts and str(ts).isdigit() else None
            save_gui_settings(
                srt_file=out.get("srt_file", str(default_srt_file())),
                png_dir=out.get("png_dir", str(default_png_dir())),
                download_dir=out.get("download_dir"),
                preview_pane_width=preview_pane_width,
                preview_thumb_size=preview_thumb_size,
            )
        except OSError:
            pass

    return out


def load_manual_overrides() -> dict[str, dict]:
    """사용자가 GUI에서 직접 수정한 행 데이터(수동 지정 값)."""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    ov = data.get("manual_overrides")
    if not isinstance(ov, dict):
        return {}
    out: dict[str, dict] = {}
    for k, v in ov.items():
        if not isinstance(k, str) or not k.strip():
            continue
        if isinstance(v, dict):
            out[k] = v
    return out


def save_manual_overrides(overrides: dict[str, dict]) -> None:
    """수동 지정 값을 설정 파일에 저장(기존 설정 유지)."""
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError, ValueError):
            base = {}
    base["manual_overrides"] = overrides
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_download_image_inputs() -> dict[str, str]:
    """자막별 다운로드 이미지 파일명 입력(대본번호 키)."""
    p = config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    raw = data.get("download_image_inputs")
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for k, v in raw.items():
        if isinstance(k, str) and k.strip() and isinstance(v, str) and v.strip():
            out[k.strip()] = v.strip()
    return out


def save_download_image_inputs(inputs: dict[str, str]) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    base: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                base = cur
        except (OSError, json.JSONDecodeError, ValueError):
            base = {}
    base["download_image_inputs"] = inputs
    p.write_text(json.dumps(base, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def save_gui_settings(
    *,
    srt_file: str,
    png_dir: str,
    download_dir: str | None = None,
    preview_pane_width: int | None = None,
    preview_thumb_size: int | None = None,
) -> None:
    p = config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    # 기존 설정(수동 지정 값 등)을 보존
    data: dict = {}
    if p.is_file():
        try:
            cur = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(cur, dict):
                data = cur
        except (OSError, json.JSONDecodeError, ValueError):
            data = {}

    data["srt_file"] = srt_file
    data["png_dir"] = png_dir
    data.pop("mp3_file", None)
    if download_dir is not None and download_dir.strip():
        data["download_dir"] = download_dir.strip()
    try:
        from wisdom_workspace import touch_workspace_from_path

        touch_workspace_from_path(png_dir)
    except ImportError:
        pass
    if preview_pane_width is not None and preview_pane_width >= 200:
        data["preview_pane_width"] = preview_pane_width
    if preview_thumb_size is not None and 80 <= preview_thumb_size <= 1200:
        data["preview_thumb_size"] = preview_thumb_size
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
