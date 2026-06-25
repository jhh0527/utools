# -*- coding: utf-8 -*-
"""2_1_ttsToVoice 설정(elsub_config.json) 로드/저장 (실행 파일과 같은 폴더)."""

from __future__ import annotations

import json
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_DIRNAME = "2_1_ttsToVoice"


def _ensure_wisdom_on_path(from_file: str | Path) -> None:
    # PyInstaller(onefile)에서는 wisdom_root가 파일 경로가 아닌 번들 모듈일 수 있다.
    if importlib.util.find_spec("wisdom_root") is not None:
        return

    candidates: list[Path] = [Path.cwd(), *Path(from_file).resolve().parents]
    meipass = getattr(sys, "_MEIPASS", "")
    if meipass:
        candidates.append(Path(meipass))
    if getattr(sys, "frozen", False):
        candidates.append(Path(sys.executable).resolve().parent)

    seen: set[str] = set()
    for base in candidates:
        try:
            root = base.resolve()
        except OSError:
            continue
        key = str(root)
        if key in seen:
            continue
        seen.add(key)
        if (root / "wisdom_root.py").is_file():
            if key not in sys.path:
                sys.path.insert(0, key)
            return


_ensure_wisdom_on_path(__file__)
from wisdom_root import module_dir, module_output
from wisdom_workspace import (
    folder_dialog_initial,
    get_workspace_dir,
    resolve_module_output,
    touch_workspace_from_path,
    workspace_module_output,
)

CONFIG_FILENAME = "elsub_config.json"
EXAMPLE_FILENAME = "elsub_config.example.json"
GUI_CONFIG_NAME = "elsub_gui_config.json"
PRESET_CONFIG_FILENAMES: tuple[str, ...] = (
    "elsub_config.json",
    "elsub_config2.json",
    "elsub_config3.json",
    "elsub_config4.json",
    "elsub_config5.json",
)
OUTPUT_DIRNAME = "output"
INPUT_DIRNAME = "input"

_config_path_override: Path | None = None


def configure_module(
    *,
    project_dirname: str | None = None,
    config_filename: str | None = None,
    example_filename: str | None = None,
    gui_config_name: str | None = None,
) -> None:
    """Wonder 등 파생 모듈에서 경로·설정 파일명을 바꿀 때 호출."""
    global PROJECT_DIRNAME, CONFIG_FILENAME, EXAMPLE_FILENAME, GUI_CONFIG_NAME
    if project_dirname is not None:
        PROJECT_DIRNAME = project_dirname
    if config_filename is not None:
        CONFIG_FILENAME = config_filename
    if example_filename is not None:
        EXAMPLE_FILENAME = example_filename
    if gui_config_name is not None:
        GUI_CONFIG_NAME = gui_config_name


def set_config_path_override(path: Path | str | None) -> None:
    global _config_path_override
    if path is None or (isinstance(path, str) and not path.strip()):
        _config_path_override = None
        return
    _config_path_override = Path(path).expanduser().resolve()


def _frozen_exe_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _running_as_wisdom_hub() -> bool:
    return getattr(sys, "frozen", False) and _frozen_exe_dir().stem.lower() == "wisdom_hub_gui"


def _module_dist_dir() -> Path:
    return module_dir(PROJECT_DIRNAME) / "dist"


def _config_search_paths() -> list[Path]:
    """설정 파일 탐색 순서 (허브 exe → 모듈 dist 우선)."""
    out: list[Path] = []
    if getattr(sys, "frozen", False):
        if _running_as_wisdom_hub():
            out.append(_module_dist_dir() / CONFIG_FILENAME)
        out.append(_frozen_exe_dir() / CONFIG_FILENAME)
        return out
    return [module_dir(PROJECT_DIRNAME) / CONFIG_FILENAME]


def config_dist_dir() -> Path:
    """Voice ID JSON이 있는 ``dist`` 폴더 (exe·허브·소스 실행 공통)."""
    if getattr(sys, "frozen", False):
        if _running_as_wisdom_hub():
            return _module_dist_dir()
        return _frozen_exe_dir()
    return module_dir(PROJECT_DIRNAME) / "dist"


def preset_config_paths() -> list[Path]:
    return [config_dist_dir() / name for name in PRESET_CONFIG_FILENAMES]


def resolve_preset_config(saved: str | None = None) -> Path:
    """저장값·존재 파일 기준으로 사용할 Voice ID 설정 경로."""
    presets = preset_config_paths()
    by_name = {p.name: p for p in presets}
    if saved and saved.strip():
        raw = Path(saved.strip()).expanduser()
        if raw.is_file():
            return raw.resolve()
        if raw.name in by_name:
            return by_name[raw.name]
        try:
            resolved = raw.resolve()
            for p in presets:
                if p.resolve() == resolved:
                    return p
        except OSError:
            pass
    for p in presets:
        if p.is_file():
            return p
    return presets[0]


def config_file_path() -> Path:
    if _config_path_override is not None:
        return _config_path_override
    for p in _config_search_paths():
        if p.is_file():
            return p
    for p in preset_config_paths():
        if p.is_file():
            return p
    paths = _config_search_paths()
    if paths:
        return paths[0]
    return config_dist_dir() / CONFIG_FILENAME


def resolve_output_dir() -> Path:
    """``{작업폴더}/2_1_ttsToVoice/output`` 또는 wisdom 기본."""
    return resolve_module_output(PROJECT_DIRNAME)


def default_input_dir() -> Path:
    """기본 입력: 작업 폴더 ``mp3`` (없으면 ``1_2_textToTts/output``)."""
    try:
        from wisdom_content_paths import default_mp3_dir

        mp3 = default_mp3_dir()
        if mp3 is not None:
            return mp3
    except ImportError:
        pass
    ws = get_workspace_dir()
    if ws is not None:
        tts_out = ws / "1_2_textToTts" / OUTPUT_DIRNAME
        if tts_out.is_dir():
            return tts_out
        return ws
    tts_out = module_dir("1_2_textToTts") / OUTPUT_DIRNAME
    if tts_out.is_dir():
        return tts_out
    local = module_dir(PROJECT_DIRNAME) / INPUT_DIRNAME
    local.mkdir(parents=True, exist_ok=True)
    return local


def gui_config_path() -> Path:
    if getattr(sys, "frozen", False):
        if _running_as_wisdom_hub():
            p = _module_dist_dir() / GUI_CONFIG_NAME
            if p.is_file():
                return p
        hub_side = _frozen_exe_dir() / GUI_CONFIG_NAME
        mod_side = _module_dist_dir() / GUI_CONFIG_NAME
        if hub_side.is_file():
            return hub_side
        if mod_side.is_file():
            return mod_side
        return mod_side if _running_as_wisdom_hub() else hub_side
    return module_dir(PROJECT_DIRNAME) / "dist" / GUI_CONFIG_NAME


def load_gui_settings() -> dict[str, str]:
    p = gui_config_path()
    if not p.is_file():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, str] = {}
    for key in ("input_dir", "output_dir", "config_file"):
        v = data.get(key)
        if isinstance(v, str) and v.strip():
            out[key] = v.strip()
    return out


def save_gui_settings(*, input_dir: str, output_dir: str, config_file: str = "") -> None:
    touch_workspace_from_path(input_dir)
    p = gui_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "input_dir": input_dir.strip(),
        "output_dir": output_dir.strip(),
    }
    if config_file.strip():
        data["config_file"] = config_file.strip()
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def copy_bundled_example_if_needed() -> None:
    """PyInstaller onefile: _MEIPASS에 있는 예시를 설정 폴더로 한 번 복사."""
    if not getattr(sys, "frozen", False):
        return
    meipass = getattr(sys, "_MEIPASS", None)
    if not meipass:
        return
    dest_dir = config_file_path().parent
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_example = dest_dir / EXAMPLE_FILENAME
    if dest_example.is_file():
        return
    src = Path(meipass) / EXAMPLE_FILENAME
    if src.is_file():
        try:
            dest_example.write_bytes(src.read_bytes())
        except OSError:
            pass


@dataclass
class AppSettings:
    elevenlabs_api_key: str = ""
    voice_id: str = ""
    model_id: str = "eleven_multilingual_v2"
    default_output_mp3: str = ""


def load_settings() -> AppSettings:
    path = config_file_path()
    if not path.is_file():
        return AppSettings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return AppSettings()
    if not isinstance(raw, dict):
        return AppSettings()
    return AppSettings(
        elevenlabs_api_key=str(raw.get("elevenlabs_api_key", "") or "").strip(),
        voice_id=str(raw.get("voice_id", "") or "").strip(),
        model_id=str(raw.get("model_id", "") or "eleven_multilingual_v2").strip(),
        default_output_mp3=str(raw.get("default_output_mp3", "") or "").strip(),
    )


def save_settings(s: AppSettings) -> None:
    path = config_file_path()
    data = {
        "elevenlabs_api_key": s.elevenlabs_api_key,
        "voice_id": s.voice_id,
        "model_id": s.model_id or "eleven_multilingual_v2",
        "default_output_mp3": s.default_output_mp3,
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def settings_from_vars(
    api_key: str,
    voice_id: str,
    model_id: str,
    default_output_mp3: str,
) -> AppSettings:
    return AppSettings(
        elevenlabs_api_key=api_key.strip(),
        voice_id=voice_id.strip(),
        model_id=model_id.strip() or "eleven_multilingual_v2",
        default_output_mp3=default_output_mp3.strip(),
    )
