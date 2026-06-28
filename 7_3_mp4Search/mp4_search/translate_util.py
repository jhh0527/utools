# -*- coding: utf-8 -*-
"""검색어 → 영어 번역 (Google Translate, API 키 불필요)."""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request

_CACHE: dict[str, str] = {}
_ASCII_WORD = re.compile(r"[A-Za-z0-9]{2,}")
_QUERY_STOP = frozenset(
    """
    a an the and or of on in at to for with from is are was were be been being
    this that these those it its as by into through over under about up down out
    off not no nor so if but than then also very just only even still already
    there their they them we you your our can could would should will shall may
    might must do does did done have has had having am i me my he she his her
    what when where which who whom how why all each every both few more most some
    such other another one two three first last new old same than too
    """.split()
)


def compact_search_query(text: str, *, max_words: int = 4) -> str:
    """긴 문장 → 스톡 영상 검색용 핵심 키워드(영어)."""
    words = re.findall(r"[A-Za-z0-9]+", text or "")
    lower = [w.lower() for w in words if w]
    strong = [w for w in lower if len(w) >= 4 and w not in _QUERY_STOP]
    weak = [w for w in lower if 3 <= len(w) < 4 and w not in _QUERY_STOP]
    picked: list[str] = []
    for bucket in (strong, weak):
        for w in bucket:
            if w not in picked:
                picked.append(w)
            if len(picked) >= max_words:
                break
        if len(picked) >= max_words:
            break
    if picked:
        return " ".join(picked[:max_words])
    return " ".join(lower[:max_words])


def search_query_from_cue(text: str, *, max_len: int = 80) -> str:
    """자막 텍스트에서 스톡 영상 검색용 영어 쿼리 생성."""
    src = " ".join((text or "").split())
    if not src:
        return ""
    if src in _CACHE:
        return _CACHE[src]
    if _ASCII_WORD.search(src) and len(_ASCII_WORD.findall(src)) >= 2:
        out = compact_search_query(src, max_words=4) or src[:max_len].strip()
    else:
        translated = translate_to_english(src)
        out = compact_search_query(translated, max_words=4) or translated[:max_len].strip()
    out = out[:max_len].strip()
    _CACHE[src] = out
    return out


def translate_to_english(text: str) -> str:
    src = (text or "").strip()
    if not src:
        return ""
    try:
        params = {
            "client": "gtx",
            "sl": "auto",
            "tl": "en",
            "dt": "t",
            "q": src,
        }
        url = f"https://translate.googleapis.com/translate_a/single?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        parts = data[0] if isinstance(data, list) and data else []
        out = "".join(str(chunk[0]) for chunk in parts if isinstance(chunk, list) and chunk)
        return out.strip() or src
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, IndexError, TypeError):
        return src
