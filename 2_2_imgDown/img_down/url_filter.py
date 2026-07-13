# -*- coding: utf-8 -*-
"""이미지 URL 판별 — 추적·광고 URL 제외."""

from __future__ import annotations

import re
from urllib.parse import urlparse

_SKIP_HOST_PARTS = (
    "bat.bing.com",
    "bing.com/action",
    "google-analytics.com",
    "googletagmanager.com",
    "doubleclick.net",
    "facebook.com/tr",
    "analytics.",
    "hotjar.com",
    "clarity.ms",
    "segment.io",
)

_IMAGE_EXT_RE = re.compile(r"\.(png|jpe?g|webp|gif|bmp|avif)(\?|$|#)", re.IGNORECASE)

_GOOD_HOST_PARTS = (
    "genspark.ai",
    "genspark",
    "cloudinary",
    "amazonaws.com",
    "googleusercontent.com",
    "oaidalle",
    "openai.com",
    "blob.core.windows.net",
    "cdn.",
    "img.",
    "images.",
    "media.",
    "storage.",
    "files.",
)


def is_tracking_url(url: str) -> bool:
    u = (url or "").strip().lower()
    if not u:
        return True
    if u.startswith("data:"):
        return True
    for part in _SKIP_HOST_PARTS:
        if part in u:
            return True
    if "/action/0?" in u and "bing" in u:
        return True
    return False


def looks_like_image_url(url: str) -> bool:
    u = (url or "").strip()
    if not u:
        return False
    if u.startswith("blob:"):
        return True
    if _IMAGE_EXT_RE.search(u):
        return True
    try:
        host = urlparse(u).netloc.lower()
    except ValueError:
        return False
    return any(part in host for part in _GOOD_HOST_PARTS)


def is_collectable_image_url(url: str, *, width: int = 0, height: int = 0) -> bool:
    """페이지 수집용 — 추적 URL 제외, 생성 이미지 후보만."""
    if is_tracking_url(url):
        return False
    if looks_like_image_url(url):
        return True
    # 확장자·CDN이 없으면 충분히 큰 img만
    if width >= 256 and height >= 256:
        return True
    return False


def is_image_bytes(data: bytes) -> bool:
    if len(data) < 512:
        return False
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return True
    if data[:3] == b"\xff\xd8\xff":
        return True
    if data[:4] == b"RIFF" and len(data) > 12 and data[8:12] == b"WEBP":
        return True
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return True
    return False
