# -*- coding: utf-8 -*-
"""기본 경로."""

from __future__ import annotations

import sys
from pathlib import Path

from wisdom_workspace import get_workspace_dir, workspace_module_output

MODULE = "7_3_mp4Search"

# 우측 하단 원형 아나운서 PiP — ``…/무협극장/anouncer/*.mp4``
_LEGACY_ANNOUNCER_DIR = Path(r"C:\무협극장\anouncer")
_LEGACY_ANNOUNCER_MP4 = Path(r"C:\무협극장\middleageAnouncer.mp4")


def announcer_search_dirs() -> list[Path]:
    """아나운서 mp4 후보 폴더 (앞쪽 우선)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path | None) -> None:
        if p is None:
            return
        try:
            key = str(p.expanduser().resolve())
        except OSError:
            key = str(p)
        if key in seen:
            return
        seen.add(key)
        out.append(Path(key))

    ws = get_workspace_dir()
    if ws is not None:
        add(ws / "anouncer")
        # 작업폴더가 장/부 하위여도 상위의 anouncer 탐색
        for parent in (ws, *ws.parents):
            add(parent / "anouncer")
            if parent.name == "무협극장" or parent.parent == parent:
                break
            # 너무 위로 올라가지 않음
            if len(parent.parts) <= 2:
                break

    try:
        from wisdom_root import resolve_wisdom_root

        root = resolve_wisdom_root()
        add(root / "무협극장" / "anouncer")
        add(root / "anouncer")
    except ImportError:
        pass

    add(_LEGACY_ANNOUNCER_DIR)
    return out


def announcer_dir() -> Path | None:
    """mp4가 있는 첫 anouncer 폴더."""
    for d in announcer_search_dirs():
        if d.is_dir() and any(d.glob("*.mp4")):
            return d
    for d in announcer_search_dirs():
        if d.is_dir():
            return d
    return None


# 하위 호환: 예전 상수명 (실제 경로는 announcer_dir() 사용)
ANNOUNCER_DIR = _LEGACY_ANNOUNCER_DIR
DEFAULT_ANNOUNCER_MP4 = _LEGACY_ANNOUNCER_MP4


def list_announcer_mp4s() -> list[Path]:
    """anouncer 폴더의 *.mp4 (이름순). 없으면 레거시 단일 파일."""
    for d in announcer_search_dirs():
        if not d.is_dir():
            continue
        files = sorted(
            (p for p in d.glob("*.mp4") if p.is_file()),
            key=lambda p: p.name.lower(),
        )
        if files:
            return files
    if _LEGACY_ANNOUNCER_MP4.is_file():
        return [_LEGACY_ANNOUNCER_MP4]
    # wisdom 쪽 middleage 폴백
    try:
        from wisdom_root import resolve_wisdom_root

        for name in ("middleageAnouncer.mp4", "jwhShirt.mp4"):
            p = resolve_wisdom_root() / "무협극장" / "anouncer" / name
            if p.is_file():
                return [p]
    except ImportError:
        pass
    return []


def resolve_announcer_mp4(name_or_path: str = "") -> Path | None:
    """선택 이름/경로 → 실제 파일. 비어 있으면 목록 첫 항목."""
    raw = (name_or_path or "").strip()
    files = list_announcer_mp4s()
    if raw:
        p = Path(raw)
        if p.is_file():
            return p
        # 파일명만 저장된 경우 — 후보 폴더·목록에서 검색
        name = Path(raw).name
        for d in announcer_search_dirs():
            cand = d / name
            if cand.is_file():
                return cand
        for f in files:
            if f.name.lower() == name.lower():
                return f
    return files[0] if files else None


def default_output_dir() -> Path:
    return workspace_module_output(MODULE) / "mp4"


def _config_bases() -> list[Path]:
    bases: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        s = str(p)
        if s not in seen:
            seen.add(s)
            bases.append(p)

    if getattr(sys, "frozen", False):
        add(Path(sys.executable).resolve().parent)
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            add(Path(meipass))
    try:
        from wisdom_root import module_dir

        mod = module_dir(MODULE)
        if mod.is_dir():
            add(mod)
    except ImportError:
        pass
    add(Path(__file__).resolve().parents[1])
    return bases


def stock_api_config_write_path() -> Path:
    """API 키 저장 권장 경로 (exe 옆 ``config/stock_api.json``)."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "config" / "stock_api.json"
    for base in _config_bases():
        if (base / "config").is_dir() or base.name == MODULE:
            return base / "config" / "stock_api.json"
    return Path(__file__).resolve().parents[1] / "config" / "stock_api.json"


def stock_api_config_candidates() -> list[Path]:
    """``stock_api.json`` → ``stock_api.example.json`` 순으로 탐색."""
    out: list[Path] = []
    seen: set[str] = set()
    for base in _config_bases():
        for name in ("stock_api.json", "stock_api.example.json"):
            p = base / "config" / name
            s = str(p)
            if s not in seen:
                seen.add(s)
                out.append(p)
    return out


def media_dirs_for_srt(srt: Path) -> tuple[Path, Path]:
    """SRT 기준 콘텐츠 루트의 ``mp4``·``mp3`` 폴더 (없으면 경로만 구성).

    ``…/kor/mp3/all.srt`` → ``…/kor/mp4``, ``…/kor/mp3``
    ``…/kor/all.srt`` → ``…/kor/mp4``, ``…/kor/mp3``
    """
    from wisdom_content_paths import find_child_dir

    srt = Path(srt)
    start = srt.parent if srt.suffix or srt.is_file() else srt
    root = start
    if start.name.casefold() in ("mp3", "mp4", "png", "jpg", "srt"):
        root = start.parent
    else:
        for cand in (start, *start.parents):
            mp4_c = find_child_dir(cand, "mp4")
            mp3_c = find_child_dir(cand, "mp3")
            if mp4_c.is_dir() or mp3_c.is_dir():
                root = cand
                break
            if cand.name.casefold() in ("mp3", "mp4", "png", "jpg", "srt"):
                root = cand.parent
                break
    return find_child_dir(root, "mp4"), find_child_dir(root, "mp3")


def mp3_candidates_for_srt(srt: Path) -> list[Path]:
    """SRT·작업 폴더 기준 MP3 후보 (``all.mp3``, ``part01.mp3``, SRT와 같은 이름 등)."""
    out: list[Path] = []
    seen: set[str] = set()

    def add(p: Path) -> None:
        s = str(p)
        if s not in seen:
            seen.add(s)
            out.append(p)

    srt = Path(srt)
    _, mp3_dir = media_dirs_for_srt(srt) if (srt.is_file() or srt.suffix) else (Path(), Path())
    if mp3_dir:
        if srt.is_file() or srt.suffix:
            add(mp3_dir / srt.with_suffix(".mp3").name)
        for name in ("all.mp3", "part01.mp3"):
            add(mp3_dir / name)
    if srt.is_file() or srt.suffix:
        add(srt.with_suffix(".mp3"))
        for name in ("all.mp3", "part01.mp3"):
            add(srt.parent / name)
    try:
        from wisdom_content_paths import default_mp3_dir

        cfg_mp3 = default_mp3_dir()
        if cfg_mp3 and cfg_mp3.is_dir():
            if srt.is_file() or srt.suffix:
                add(cfg_mp3 / srt.with_suffix(".mp3").name)
            for name in ("all.mp3", "part01.mp3"):
                add(cfg_mp3 / name)
    except ImportError:
        pass
    try:
        from wisdom_workspace import workspace_module_output

        tts_out = workspace_module_output("2_1_ttsToVoice")
        for name in ("all.mp3", "part01.mp3"):
            add(tts_out / name)
    except ImportError:
        pass
    return out


def resolve_mp3_for_srt(srt: Path) -> Path | None:
    for cand in mp3_candidates_for_srt(srt):
        if cand.is_file():
            return cand
    return None


def pick_default_srt_mp3() -> tuple[Path | None, Path | None]:
    """4_1_video 와 동일 — ``all.srt`` / ``all.mp3`` 우선."""
    roots: list[Path] = []
    seen: set[str] = set()

    def add_root(p: Path | None) -> None:
        if p is None:
            return
        p = Path(p)
        if p.is_dir():
            s = str(p)
            if s not in seen:
                seen.add(s)
                roots.append(p)

    try:
        from wisdom_content_paths import default_mp3_dir

        add_root(default_mp3_dir())
    except ImportError:
        pass
    try:
        from wisdom_workspace import workspace_module_output

        add_root(workspace_module_output("2_1_ttsToVoice"))
    except ImportError:
        pass

    for root in roots:
        all_mp3 = root / "all.mp3"
        all_srt = root / "all.srt"
        if all_srt.is_file():
            mp3 = all_mp3 if all_mp3.is_file() else resolve_mp3_for_srt(all_srt)
            return all_srt, mp3
        p1 = root / "part01.mp3"
        s1 = root / "part01.srt"
        if s1.is_file():
            mp3 = p1 if p1.is_file() else resolve_mp3_for_srt(s1)
            return s1, mp3
        srts = sorted(root.glob("*.srt"))
        if srts:
            srt = srts[0]
            mp3 = resolve_mp3_for_srt(srt)
            return srt, mp3
    return None, None
