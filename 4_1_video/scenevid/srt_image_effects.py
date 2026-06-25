# -*- coding: utf-8 -*-
"""2_2_srtToImage ``SRT_image_effect.md`` 형식 JSON → 4_1_video 큐별 Ken Burns 모션 토큰."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from scenevid.motion import normalize_effect

# ``scene_analysis.type`` → compose 모션 (pan_left, zoom_in, …)
_SCENE_TYPE_MOTION: dict[str, str] = {
    "fixed": "none",
    "curiosity": "zoom_in",
    "achievement": "zoom_in",
    "warning": "zoom_out",
    "awe": "zoom_in",
    "caution": "pan_left",
    "confrontation": "pan_right",
}

# ``auto_effects[].effect`` 가 단독으로 있을 때 보조 매핑
_AUTO_EFFECT_MOTION: dict[str, str] = {
    "dramatic_lighting": "zoom_in",
    "split_lighting": "pan_right",
    "dual_tone": "pan_right",
    "scale_emphasis": "zoom_in",
    "color_shift": "zoom_out",
    "color_desaturation": "zoom_out",
}

_EFFECTS_JSON_NAMES: tuple[str, ...] = (
    "SRT_image_effects.json",
    "srt_image_effects.json",
    "image_effects.json",
    "srt_effects.json",
)


def find_srt_image_effects_json(*search_dirs: Path | str | None) -> Path | None:
    """이미지·산출물 폴더에서 효과 메타데이터 JSON 을 찾습니다."""
    seen: set[Path] = set()
    for raw in search_dirs:
        if raw is None:
            continue
        d = Path(raw).resolve()
        if d in seen:
            continue
        seen.add(d)
        if d.is_file() and _is_effects_json_file(d):
            return d
        if not d.is_dir():
            continue
        for name in _EFFECTS_JSON_NAMES:
            p = d / name
            if p.is_file():
                return p
        for p in sorted(d.glob("*effects*.json")):
            if p.is_file() and _is_effects_json_file(p):
                return p
    return None


def _is_effects_json_file(path: Path) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, json.JSONDecodeError, ValueError):
        return False
    if not isinstance(data, dict):
        return False
    return "images" in data or "effects_version" in data


def load_cue_effects_from_srt_image_json(path: Path) -> dict[int, str]:
    """JSON ``images[]`` → ``{ SRT 표시 번호: 모션 토큰 }``."""
    data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError(f"효과 JSON 루트가 객체가 아닙니다: {path}")
    images = data.get("images")
    if not isinstance(images, list):
        raise ValueError(f"효과 JSON에 images 배열이 없습니다: {path}")

    out: dict[int, str] = {}
    for item in images:
        if not isinstance(item, dict):
            continue
        sn = item.get("srt_number")
        if sn is None:
            continue
        try:
            n = int(str(sn).strip())
        except ValueError:
            continue
        if n < 1:
            continue
        out[n] = normalize_effect(motion_token_for_image_entry(item))
    return out


def motion_token_for_image_entry(entry: dict[str, Any]) -> str:
    """단일 ``images[]`` 항목 → 4_1_video 모션 토큰."""
    sa = entry.get("scene_analysis")
    if not isinstance(sa, dict):
        sa = {}
    stype = str(sa.get("type") or "fixed").strip().lower()
    auto = entry.get("auto_effects")
    if not isinstance(auto, list):
        auto = []

    if stype == "fixed" or not auto:
        return _SCENE_TYPE_MOTION.get(stype, "none")

    for raw in auto:
        if not isinstance(raw, dict):
            continue
        name = str(raw.get("effect") or "").strip().lower()
        if name in _AUTO_EFFECT_MOTION:
            return _AUTO_EFFECT_MOTION[name]

    intensity = str(sa.get("intensity") or "none").strip().lower()
    base = _SCENE_TYPE_MOTION.get(stype, "zoom_in")
    if intensity == "high":
        return "zoom_in" if base in ("none", "pan_left", "pan_right") else base
    if intensity == "low" and base in ("zoom_in", "zoom_out"):
        return "pan_right"
    return base


def extract_json_from_markdown(md_text: str) -> dict[str, Any] | None:
    """마크다운 본문에 포함된 ```json … ``` 블록(효과 메타데이터)을 파싱합니다."""
    for m in re.finditer(r"```json\s*\n(.*?)```", md_text, flags=re.DOTALL | re.IGNORECASE):
        block = m.group(1).strip()
        if not block:
            continue
        try:
            data = json.loads(block)
        except json.JSONDecodeError:
            continue
        if isinstance(data, dict) and ("images" in data or "effects_version" in data):
            return data
    return None


def save_srt_image_effects_json(path: Path, data: dict[str, Any]) -> None:
    """효과 메타데이터 JSON 저장 (2_2_srtToImage 등에서 사용 가능)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
