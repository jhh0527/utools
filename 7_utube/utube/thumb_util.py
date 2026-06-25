"""YouTube 썸네일 로드 (GUI 미리보기용)."""

from __future__ import annotations

import io
import urllib.request


def youtube_thumbnail_url(video_id: str, *, quality: str = "mqdefault") -> str:
    return f"https://i.ytimg.com/vi/{video_id}/{quality}.jpg"


def load_thumbnail_bytes(video_id: str) -> bytes | None:
    url = youtube_thumbnail_url(video_id)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            return resp.read()
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
        return None


def load_thumbnail_photo(video_id: str, *, max_size: tuple[int, int] = (168, 94)):
    """PIL ImageTk.PhotoImage 또는 None."""
    raw = load_thumbnail_bytes(video_id)
    if not raw:
        return None
    try:
        from PIL import Image, ImageTk
    except ImportError:
        return None
    try:
        img = Image.open(io.BytesIO(raw))
        img.thumbnail(max_size)
        return ImageTk.PhotoImage(img)
    except OSError:
        return None
