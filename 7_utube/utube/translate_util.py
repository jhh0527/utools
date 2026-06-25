# -*- coding: utf-8 -*-
"""YouTube 제목 → 한국어 번역 (Google Translate, API 키 불필요)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

_CACHE: dict[str, str] = {}
_HANGUL_RE = re.compile(r"[\uac00-\ud7a3]")


def is_mostly_korean(text: str) -> bool:
    """한글이 주된 언어이면 True."""
    t = text.strip()
    if not t:
        return True
    hangul = len(_HANGUL_RE.findall(t))
    if hangul < 2:
        return False
    latin = sum(1 for c in t if c.isascii() and c.isalpha())
    return hangul >= latin


def translate_to_korean(text: str) -> str:
    """제목을 한국어로 번역. 이미 한글이면 원문, 실패 시 원문."""
    src = (text or "").strip()
    if not src:
        return ""
    if src in _CACHE:
        return _CACHE[src]
    if is_mostly_korean(src):
        _CACHE[src] = src
        return src
    try:
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "ko",
            "dt": "t",
            "q": src,
        }
        url = f"https://translate.googleapis.com/translate_a/single?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data[0] if isinstance(data, list) and data else []
        out = "".join(str(chunk[0]) for chunk in parts if isinstance(chunk, list) and chunk)
        out = out.strip() or src
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, IndexError, TypeError):
        out = src
    _CACHE[src] = out
    return out
