# -*- coding: utf-8 -*-
"""wisdom 워크스페이스(IDE·탐색기에서 연 폴더) 루트 — 모듈 간 경로의 공통 기준."""

from __future__ import annotations

import os
import sys
from pathlib import Path

# wisdom 루트 판별용 (번호 체계 개편 후 폴더명)
MARKER_DIRS = (
    "2_1_ttsToVoice",
    "4_1_video",
    "2_2_srtToImage",
    "1_1_textTo700Text",
)

# canonical → 예전 폴더명 (작업 폴더·저장 경로 호환)
MODULE_LEGACY_ALIASES: dict[str, tuple[str, ...]] = {
    "1_1_textTo700Text": ("1_textTo700Text",),
    "1_2_textToTts": ("2_textToTts",),
    "2_1_ttsToVoice": ("3_ttsToVoice",),
    "2_2_srtToImage": ("4_srtToImage",),
    "3_1_pngFileName": ("4_2pngFileName",),
    "3_2_pngToJpg": ("4_1pngToJpg",),
    "4_1_video": ("5_video",),
    "4_2_ShortVideo": ("5_2_ShortVideo",),
}

_LEGACY_TO_CANONICAL: dict[str, str] = {
    legacy: canonical
    for canonical, legacies in MODULE_LEGACY_ALIASES.items()
    for legacy in legacies
}

_installed = False


def canonical_module_name(name: str) -> str:
    """모듈 폴더의 현재(정식) 이름."""
    return _LEGACY_TO_CANONICAL.get(name, name)


def module_name_candidates(name: str) -> tuple[str, ...]:
    """존재하는 폴더를 찾을 때 시도할 이름 (정식 → 구 이름)."""
    canonical = canonical_module_name(name)
    seen: set[str] = set()
    out: list[str] = []
    for n in (canonical, name):
        if n not in seen:
            seen.add(n)
            out.append(n)
    for legacy in MODULE_LEGACY_ALIASES.get(canonical, ()):
        if legacy not in seen:
            seen.add(legacy)
            out.append(legacy)
    return tuple(out)


def _first_existing_child(parent: Path, names: tuple[str, ...]) -> Path | None:
    for n in names:
        p = parent / n
        if p.is_dir():
            return p
    return None


def looks_like_wisdom_root(p: Path) -> bool:
    try:
        r = p.resolve()
    except OSError:
        return False
    hits = sum(1 for name in MARKER_DIRS if (r / name).is_dir())
    if hits >= 2:
        return True
    # 구 마커만 있는 저장소도 인식
    legacy_markers = (
        "3_ttsToVoice",
        "5_video",
        "4_srtToImage",
        "1_textTo700Text",
    )
    legacy_hits = sum(1 for name in legacy_markers if (r / name).is_dir())
    return legacy_hits >= 2


def _walk_up(start: Path, *, max_depth: int = 12) -> Path | None:
    p = start.resolve()
    for _ in range(max_depth):
        if looks_like_wisdom_root(p):
            return p
        parent = p.parent
        if parent == p:
            break
        p = parent
    return None


def _candidate_starts() -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        try:
            key = str(p.resolve())
        except OSError:
            return
        if key not in seen:
            seen.add(key)
            out.append(Path(key))

    add(Path.cwd())
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        add(exe.parent)
        if exe.parent.name == "dist":
            add(exe.parent.parent)
            add(exe.parent.parent.parent)
    here = Path(__file__).resolve().parent
    add(here)
    for parent in here.parents:
        add(parent)
    return out


def resolve_wisdom_root() -> Path:
    """wisdom 워크스페이스 루트.

    1. ``WISDOM_ROOT`` 환경 변수
    2. 현재 작업 폴더(열린 폴더) — wisdom 구조면 우선
    3. exe·``wisdom_root.py`` 위치에서 상위 탐색
    4. 작업 폴더 그대로(열린 폴더를 루트로 간주)
    """
    env = os.environ.get("WISDOM_ROOT", "").strip()
    if env:
        return Path(env).expanduser().resolve()

    cwd = Path.cwd().resolve()
    if looks_like_wisdom_root(cwd):
        return cwd
    found_cwd = _walk_up(cwd)
    if found_cwd is not None:
        return found_cwd

    for start in _candidate_starts():
        if start == cwd:
            continue
        found = _walk_up(start)
        if found is not None:
            return found

    return cwd


def _ensure_importable() -> None:
    root = Path(__file__).resolve().parent
    s = str(root)
    if s not in sys.path:
        sys.path.insert(0, s)


def install(*, chdir: bool = True) -> Path:
    """GUI·run 스크립트 시작 시 1회: import 경로·작업 폴더를 wisdom 루트로."""
    global _installed
    _ensure_importable()
    root = resolve_wisdom_root()
    if chdir:
        try:
            os.chdir(root)
        except OSError:
            pass
    _installed = True
    return root


def bootstrap() -> Path:
    """``install()`` 별칭 — run_*_gui 진입점에서 호출."""
    return install()


def module_dir(name: str) -> Path:
    root = resolve_wisdom_root()
    found = _first_existing_child(root, module_name_candidates(name))
    if found is not None:
        return found
    return root / canonical_module_name(name)


def module_output(name: str) -> Path:
    return module_dir(name) / "output"


def find_module_dir(name: str) -> Path | None:
    """``name`` 모듈 폴더가 있으면 반환, 없으면 None."""
    p = module_dir(name)
    return p if p.is_dir() else None
