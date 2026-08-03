# -*- coding: utf-8 -*-
"""씬 스크립트 파싱 — ``SRT_XXX: prompt``."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

_SCENE_RE = re.compile(
    r"^\s*SRT[_\s-]?(\d{1,6})\s*:\s*(.+?)\s*$",
    re.IGNORECASE | re.DOTALL,
)
_SCENE_START_RE = re.compile(r"^\s*SRT[_\s-]?(\d{1,6})\s*:\s*", re.IGNORECASE)


@dataclass(frozen=True)
class SceneLine:
    sec: int
    prompt: str

    @property
    def label(self) -> str:
        return f"SRT_{self.sec:03d}"

    @property
    def png_name(self) -> str:
        return f"SRT_{self.sec:03d}.png"

    def list_label(self) -> str:
        tip = self.prompt[:72] + ("…" if len(self.prompt) > 72 else "")
        return f"{self.label}  |  {tip}"


def srt_png_name(sec: int) -> str:
    return f"SRT_{max(0, int(sec)):03d}.png"


def scene_png_path(png_dir: Path, sec: int) -> Path:
    return Path(png_dir) / srt_png_name(sec)


def png_already_exists(png_dir: Path, sec: int, *, min_bytes: int = 512) -> bool:
    """PNG 폴더에 유효한 SRT_XXX.png가 있으면 재생성하지 않음."""
    p = scene_png_path(png_dir, sec)
    try:
        return p.is_file() and p.stat().st_size >= int(min_bytes)
    except OSError:
        return False


def parse_scene_script(text: str) -> list[SceneLine]:
    """textarea 본문에서 ``SRT_XXX: …`` 씬을 추출.

    한 줄에 프롬프트가 길거나, 빈 줄로 구분된 블록도 허용.
    """
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    if not raw.strip():
        return []

    scenes: list[SceneLine] = []
    cur_sec: int | None = None
    cur_parts: list[str] = []

    def flush() -> None:
        nonlocal cur_sec, cur_parts
        if cur_sec is None:
            return
        prompt = " ".join(p.strip() for p in cur_parts if p.strip()).strip()
        prompt = re.sub(r"\s+", " ", prompt)
        if prompt:
            scenes.append(SceneLine(sec=int(cur_sec), prompt=prompt))
        cur_sec = None
        cur_parts = []

    for line in raw.split("\n"):
        m = _SCENE_START_RE.match(line)
        if m:
            flush()
            cur_sec = int(m.group(1))
            rest = line[m.end() :].strip()
            cur_parts = [rest] if rest else []
            continue
        if cur_sec is not None:
            if line.strip():
                cur_parts.append(line.strip())
            else:
                # 빈 줄 — 다음 SRT_ 전까지 이어붙이거나 종료
                continue
    flush()

    # 한 줄 정규식 보조 (위에서 못 잡은 경우 거의 없음)
    if not scenes:
        for m in re.finditer(
            r"SRT[_\s-]?(\d{1,6})\s*:\s*(.+?)(?=(?:\n\s*SRT[_\s-]?\d)|\Z)",
            raw,
            re.IGNORECASE | re.DOTALL,
        ):
            prompt = re.sub(r"\s+", " ", m.group(2).strip())
            if prompt:
                scenes.append(SceneLine(sec=int(m.group(1)), prompt=prompt))
    return scenes
