# -*- coding: utf-8 -*-
"""wisdom 전역 작업 폴더 — 한 프로그램에서 지정하면 다른 GUI도 같은 기준을 사용."""

from __future__ import annotations

import json
from pathlib import Path

from wisdom_root import (
    canonical_module_name,
    module_name_candidates,
    module_output,
    resolve_wisdom_root,
)

CONFIG_REL = Path("config") / "wisdom_workspace.json"
_KEY = "workspace_dir"


def _config_path() -> Path:
    p = resolve_wisdom_root() / CONFIG_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def load_workspace() -> dict[str, str]:
    p = _config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    v = data.get(_KEY)
    if isinstance(v, str) and v.strip():
        out[_KEY] = v.strip()
    return out


def get_workspace_dir() -> Path | None:
    raw = load_workspace().get(_KEY, "")
    if raw:
        p = Path(raw).expanduser()
        try:
            r = p.resolve()
        except OSError:
            r = None
        else:
            if r.is_dir():
                return r
    discovered = _discover_from_module_configs()
    if discovered is not None:
        try:
            set_workspace_dir(discovered)
        except OSError:
            return discovered
        return discovered
    return None


def _discover_from_module_configs() -> Path | None:
    """다른 모듈 GUI 설정에 저장된 wisdom 밖 폴더를 작업 폴더로 추론."""
    wisdom = resolve_wisdom_root()
    candidates: list[Path] = [
        wisdom / "3_2_pngToJpg" / "dist" / "png2jpg_gui_config.json",
        wisdom / "2_1_ttsToVoice" / "dist" / "elsub_gui_config.json",
        wisdom / "3_1_pngFileName" / "dist" / "png_rename_gui_config.json",
        wisdom / "3_2_pngToJpg" / "dist" / "png2jpg_gui_config.json",
        wisdom / "2_1_ttsToVoice" / "dist" / "elsub_gui_config.json",
        wisdom / "3_1_pngFileName" / "dist" / "png_rename_gui_config.json",
    ]
    import sys

    if getattr(sys, "frozen", False):
        exe_dir = Path(sys.executable).resolve().parent
        for name in (
            "png2jpg_gui_config.json",
            "elsub_gui_config.json",
            "png_rename_gui_config.json",
        ):
            candidates.append(exe_dir / name)
    for cfg in candidates:
        if not cfg.is_file():
            continue
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        for key in ("input_dir", "output_dir", "png_dir"):
            v = data.get(key)
            if not isinstance(v, str) or not v.strip():
                continue
            p = Path(v.strip()).expanduser()
            if p.is_file():
                p = p.parent
            try:
                r = p.resolve()
            except OSError:
                continue
            if not r.is_dir():
                continue
            try:
                r.relative_to(wisdom)
            except ValueError:
                return r
    return None


def set_workspace_dir(path: Path) -> Path:
    p = path.expanduser().resolve()
    if not p.is_dir():
        raise NotADirectoryError(p)
    cfg = _config_path()
    cfg.write_text(
        json.dumps({_KEY: str(p)}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return p


def touch_workspace_from_path(path: str | Path) -> Path | None:
    """사용자가 고른 경로가 wisdom 저장소 밖이면 콘텐츠 루트를 작업 폴더로 저장."""
    p = Path(path).expanduser()
    try:
        p = p.resolve()
    except OSError:
        return None
    check = p.parent if p.is_file() else p
    if not check.is_dir():
        return None
    wisdom = resolve_wisdom_root()
    try:
        check.relative_to(wisdom)
        return get_workspace_dir()
    except ValueError:
        pass
    from wisdom_content_paths import touch_content_root_from_path

    return touch_content_root_from_path(path)


def workspace_module_dir(module: str) -> Path | None:
    ws = get_workspace_dir()
    if ws is None:
        return None
    for n in module_name_candidates(module):
        p = ws / n
        if p.is_dir():
            return p
    return ws / canonical_module_name(module)


def workspace_module_output(module: str) -> Path | None:
    d = workspace_module_dir(module)
    return d / "output" if d is not None else None


def resolve_module_output(module: str) -> Path:
    """작업 폴더가 있으면 ``{workspace}/{module}/output``, 없으면 wisdom 기본."""
    ws_out = workspace_module_output(module)
    if ws_out is not None:
        return ws_out
    return module_output(module)


def folder_dialog_initial(preferred: Path | None = None) -> str:
    """폴더 선택 대화상자 ``initialdir`` — 작업 폴더 우선."""
    if preferred is not None:
        try:
            p = preferred.expanduser().resolve()
            if p.is_file():
                p = p.parent
            if p.is_dir():
                return str(p)
        except OSError:
            pass
    ws = get_workspace_dir()
    if ws is not None:
        return str(ws)
    if preferred is not None:
        try:
            p = preferred.expanduser().resolve()
            if p.is_file():
                p = p.parent
            if p.parent.is_dir():
                return str(p.parent)
        except OSError:
            pass
    return str(resolve_wisdom_root())
