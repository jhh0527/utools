# -*- coding: utf-8 -*-
"""기본 Chrome 프로필에서 Genspark·Google 로그인 쿠키 읽기 (Playwright 주입용)."""

from __future__ import annotations

from typing import Any

_COOKIE_DOMAINS = (
    "genspark.ai",
    "google.com",
    "accounts.google.com",
)


def load_genspark_cookies() -> list[dict[str, Any]]:
    """
    기본 Chrome(로그인된 창)에서 Genspark·Google 쿠키를 읽습니다.
    browser_cookie3 미설치·읽기 실패 시 빈 목록.
    """
    try:
        import browser_cookie3
    except ImportError:
        return []

    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for domain in _COOKIE_DOMAINS:
        try:
            jar = browser_cookie3.chrome(domain_name=domain)
        except Exception:
            continue
        for c in jar:
            key = (c.domain, c.name, c.path or "/")
            if key in seen:
                continue
            seen.add(key)
            item: dict[str, Any] = {
                "name": c.name,
                "value": c.value,
                "domain": c.domain,
                "path": c.path or "/",
            }
            if c.expires:
                item["expires"] = float(c.expires)
            if c.secure:
                item["secure"] = True
            out.append(item)
    return out
