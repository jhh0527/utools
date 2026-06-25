# -*- coding: utf-8 -*-
"""Chrome으로 Genspark AI 이미지 페이지 열기."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GENSPARK_URL = "https://www.genspark.ai/ai_image"
CDP_PORT = 9222
CDP_PORTS = (9222, 9223)
_PROFILE_DIRNAME = ".wisdom_genspark_chrome"


def find_chrome_exe() -> Path | None:
    candidates: list[Path] = []
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(key, "")
        if base:
            candidates.append(Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe")
    for p in candidates:
        if p.is_file():
            return p
    return None


def genspark_chrome_profile(png_dir: Path) -> Path:
    """자동 생성·다운로드 전용 Chrome 프로필."""
    legacy = png_dir.parent / ".genspark_playwright_profile"
    profile = png_dir.parent / _PROFILE_DIRNAME
    if legacy.is_dir() and not profile.exists():
        try:
            legacy.rename(profile)
        except OSError:
            pass
    return profile


def is_cdp_available(port: int = CDP_PORT) -> bool:
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version",
            timeout=2.0,
        ) as resp:
            return resp.status == 200
    except (urllib.error.URLError, TimeoutError, OSError):
        return False


def any_cdp_available() -> int | None:
    for port in CDP_PORTS:
        if is_cdp_available(port):
            return port
    return None


def list_cdp_page_urls() -> list[str]:
    """CDP 로 열린 Chrome 탭 URL 목록."""
    urls: list[str] = []
    for port in CDP_PORTS:
        if not is_cdp_available(port):
            continue
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{port}/json/list",
                timeout=2.0,
            ) as resp:
                pages = json.loads(resp.read().decode("utf-8", errors="replace"))
        except Exception:
            continue
        for page in pages:
            if not isinstance(page, dict):
                continue
            url = page.get("url") or ""
            if url and page.get("type") == "page":
                urls.append(url)
    return urls


def has_genspark_ai_image_tab() -> bool:
    for url in list_cdp_page_urls():
        u = url.lower()
        if "genspark.ai" in u and "ai_image" in u:
            return True
    return False


def _popen_chrome(args: list[str]) -> None:
    kwargs: dict = {
        "args": args,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(**kwargs)


def _wait_cdp_ready(ports: tuple[int, ...] = CDP_PORTS, *, timeout_sec: float = 25.0) -> int | None:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        found = any_cdp_available()
        if found is not None:
            return found
        time.sleep(0.35)
    return None


def open_genspark_in_existing_chrome() -> None:
    """기본 Chrome(이미 로그인된 창)에 Genspark ai_image 탭을 엽니다."""
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\n"
            "Chrome 설치 후 다시 시도하세요."
        )
    _popen_chrome([str(chrome), GENSPARK_URL])


def start_chrome_with_cdp(*, profile_dir: Path, url: str | None = None) -> int:
    """자동화 전용 Chrome(CDP)을 띄웁니다."""
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\n"
            "Chrome 설치 후 다시 시도하세요."
        )
    profile_dir.mkdir(parents=True, exist_ok=True)
    last_err = ""
    for port in CDP_PORTS:
        args = [
            str(chrome),
            f"--remote-debugging-port={port}",
            "--remote-debugging-address=127.0.0.1",
            "--remote-allow-origins=*",
            f"--user-data-dir={profile_dir.resolve()}",
            "--no-first-run",
            "--no-default-browser-check",
        ]
        if url:
            args.append(url)
        _popen_chrome(args)
        ready = _wait_cdp_ready((port,), timeout_sec=12.0)
        if ready is not None:
            return ready
        last_err = f"포트 {port}"
    raise RuntimeError(
        "자동화 Chrome CDP 포트를 열지 못했습니다.\n"
        f"시도: {last_err}\n\n"
        "다른 프로그램이 9222·9223 포트를 쓰는지 확인한 뒤 다시 시도하세요."
    )


def open_chrome_tab(url: str, *, profile_dir: Path) -> None:
    """자동화 Chrome 에 새 탭으로 URL 을 엽니다."""
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError("Google Chrome을 찾을 수 없습니다.")
    _popen_chrome(
        [
            str(chrome),
            f"--user-data-dir={profile_dir.resolve()}",
            url,
        ]
    )


def ensure_chrome_cdp(
    *,
    png_dir: Path,
    url: str | None = GENSPARK_URL,
) -> int:
    """자동 생성·다운로드용 CDP Chrome 을 준비합니다."""
    profile = genspark_chrome_profile(png_dir)
    found = any_cdp_available()
    if found is not None:
        if url and not has_genspark_ai_image_tab():
            open_chrome_tab(url, profile_dir=profile)
        return found
    return start_chrome_with_cdp(profile_dir=profile, url=url)


def open_genspark_in_chrome(png_dir: Path | None = None) -> None:
    """기본 Chrome 에 Genspark ai_image 탭을 엽니다 (수동 작업·로그인 유지)."""
    if png_dir is not None:
        png_dir.mkdir(parents=True, exist_ok=True)
    open_genspark_in_existing_chrome()
