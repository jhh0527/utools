from __future__ import annotations

import re
from datetime import datetime


def format_count(n: int | None) -> str:
    if n is None:
        return "-"
    if n < 0:
        return "-"
    if n >= 100_000_000:
        return f"{n / 100_000_000:.1f}억"
    if n >= 10_000:
        return f"{n / 10_000:.1f}만"
    return f"{n:,}"


# YouTube Shorts 최대 길이(초). API에 isShort 없어 길이로 판별.
SHORTS_MAX_SECONDS = 180


def parse_iso8601_duration_seconds(iso: str) -> int:
    """``PT1H2M3S`` → 초."""
    if not iso or not iso.startswith("PT"):
        return 0
    h = m = s = 0
    for part in re.finditer(r"(\d+)([HMS])", iso):
        v, u = int(part.group(1)), part.group(2)
        if u == "H":
            h = v
        elif u == "M":
            m = v
        else:
            s = v
    return h * 3600 + m * 60 + s


def is_youtube_shorts(duration_seconds: int) -> bool:
    """길이 기준 쇼츠 여부 (YouTube Shorts ≤ 3분)."""
    return 0 < duration_seconds <= SHORTS_MAX_SECONDS


def shorts_label(duration_seconds: int) -> str:
    if duration_seconds <= 0:
        return "-"
    return "쇼츠" if is_youtube_shorts(duration_seconds) else "일반"


def parse_iso8601_duration(iso: str) -> str:
    """``PT1H2M3S`` → ``1:02:03`` 또는 ``2:03``."""
    if not iso or not iso.startswith("PT"):
        return iso or ""
    h = m = s = 0
    for part in re.finditer(r"(\d+)([HMS])", iso):
        v, u = int(part.group(1)), part.group(2)
        if u == "H":
            h = v
        elif u == "M":
            m = v
        else:
            s = v
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def duration_display_to_seconds(text: str) -> int:
    """``1:02:03`` / ``2:03`` → 초 (정렬용)."""
    text = (text or "").strip()
    if not text:
        return 0
    parts = [int(p) for p in text.split(":") if p.isdigit() or (p and p.lstrip("-").isdigit())]
    if not parts:
        return 0
    if len(parts) == 3:
        h, m, s = parts
        return h * 3600 + m * 60 + s
    if len(parts) == 2:
        m, s = parts
        return m * 60 + s
    return parts[0]


def format_published(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return iso[:10] if len(iso) >= 10 else iso
