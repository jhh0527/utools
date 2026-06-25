# -*- coding: utf-8 -*-
"""Genspark AI 채팅 — Chrome 열기·검색어 전송 (Playwright)."""

from __future__ import annotations

import asyncio
import os
import queue
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

GENSPARK_CHAT_URL = "https://www.genspark.ai/agents?type=ai_chat"
_PROFILE_DIRNAME = ".genspark_chat_profile"
_CDP_PORTS = (9222, 9223)

StatusCb = Callable[[str], None] | None


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


def chat_profile_dir(base_dir: Path) -> Path:
    return base_dir / _PROFILE_DIRNAME


def open_genspark_chat_in_chrome() -> None:
    """기본 Chrome 계정으로 Genspark 채팅 URL을 엽니다."""
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\n"
            "Chrome 설치 후 다시 시도하세요."
        )
    kwargs: dict = {
        "args": [str(chrome), GENSPARK_CHAT_URL],
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(**kwargs)


def has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def ensure_playwright() -> None:
    if not has_playwright():
        raise RuntimeError(
            "자동 검색어 전송에 Playwright 가 필요합니다.\n"
            "지금은 검색어가 클립보드에 복사되고 Chrome만 열립니다."
        )


def _emit(on_status: StatusCb, msg: str) -> None:
    if on_status:
        on_status(msg)


async def _fill_first_editable(page: Any, text: str) -> bool:
    for sel in (
        "textarea:visible",
        "[contenteditable='true']:visible",
        "[role='textbox']:visible",
    ):
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(min(n, 6)):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
                await item.click(timeout=3000)
                await item.fill(text, timeout=8000)
                return True
            except Exception:
                try:
                    await item.click(timeout=3000)
                    await page.keyboard.press("Control+A")
                    await page.keyboard.insert_text(text)
                    return True
                except Exception:
                    continue
    return False


async def _submit_chat(page: Any) -> None:
    for sel in (
        "button:has-text('Send')",
        "button:has-text('전송')",
        "button:has-text('Submit')",
        "button[type='submit']:visible",
        "[aria-label*='Send' i]",
        "[aria-label*='전송' i]",
    ):
        btn = page.locator(sel).first
        try:
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=5000)
                return
        except Exception:
            continue
    await page.keyboard.press("Enter")


async def _launch_context(playwright: Any, profile_dir: Path) -> Any:
    for port in _CDP_PORTS:
        try:
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}"
            )
            if browser.contexts:
                return browser.contexts[0]
        except Exception:
            continue

    profile_dir.mkdir(parents=True, exist_ok=True)
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir.resolve()),
        channel="chrome",
        headless=False,
        locale="ko-KR",
        args=["--disable-blink-features=AutomationControlled"],
    )


class GensparkChatSession:
    """Playwright Chrome 세션을 백그라운드에서 유지해 같은 창에 검색어를 보냅니다."""

    def __init__(self, profile_dir: Path) -> None:
        self._profile_dir = profile_dir
        self._cmd_q: queue.Queue[tuple[str, str | None, queue.Queue]] = queue.Queue()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _ensure_thread(self) -> None:
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._worker_main, daemon=True)
            self._thread.start()

    def _worker_main(self) -> None:
        asyncio.run(self._async_worker())

    def _call(self, op: str, arg: str | None, *, timeout: float = 180.0) -> None:
        self._ensure_thread()
        resp_q: queue.Queue[tuple[bool, Exception | None]] = queue.Queue()
        self._cmd_q.put((op, arg, resp_q))
        try:
            ok, err = resp_q.get(timeout=timeout)
        except queue.Empty as e:
            raise TimeoutError("Genspark 작업 시간이 초과되었습니다.") from e
        if not ok and err:
            raise err

    def open_browser(self) -> None:
        self._call("open", None)

    def submit_search(self, query: str) -> None:
        q = (query or "").strip()
        if not q:
            raise ValueError("검색어가 비어 있습니다.")
        self._call("search", q)

    async def _async_worker(self) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await _launch_context(pw, self._profile_dir)
            page = context.pages[0] if context.pages else await context.new_page()

            while True:
                try:
                    op, arg, resp_q = self._cmd_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    continue

                try:
                    if op == "open":
                        await page.goto(
                            GENSPARK_CHAT_URL,
                            wait_until="domcontentloaded",
                            timeout=90_000,
                        )
                        await page.wait_for_timeout(1200)
                        resp_q.put((True, None))
                    elif op == "search":
                        url = page.url or ""
                        if "genspark.ai" not in url:
                            await page.goto(
                                GENSPARK_CHAT_URL,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            await page.wait_for_timeout(1200)
                        if not await _fill_first_editable(page, arg or ""):
                            raise RuntimeError(
                                "채팅 입력란을 찾지 못했습니다. "
                                "로그인·페이지 로드 후 다시 시도하세요."
                            )
                        await _submit_chat(page)
                        await page.wait_for_timeout(800)
                        resp_q.put((True, None))
                    elif op == "stop":
                        resp_q.put((True, None))
                        break
                    else:
                        resp_q.put((False, RuntimeError(f"알 수 없는 명령: {op}")))
                except Exception as ex:
                    resp_q.put((False, ex))


_session: GensparkChatSession | None = None
_session_lock = threading.Lock()


def get_chat_session(profile_dir: Path) -> GensparkChatSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = GensparkChatSession(profile_dir)
        return _session


def run_open_chat_sync(
    profile_dir: Path | None = None,
    *,
    on_status: StatusCb = None,
) -> None:
    """기본 Chrome 계정으로 Genspark 채팅을 엽니다."""
    _emit(on_status, "Chrome으로 Genspark 채팅 열기…")
    open_genspark_chat_in_chrome()
    _emit(on_status, "Genspark 채팅이 열렸습니다.")


def run_submit_search_sync(
    profile_dir: Path,
    query: str,
    *,
    on_status: StatusCb = None,
    copy_for_manual: Callable[[str], None] | None = None,
) -> str:
    """
    채팅에 검색어 전송.
    Playwright 없으면 ``copy_for_manual`` 로 클립보드 복사 후 Chrome만 엽니다.
    반환: ``"auto"`` | ``"manual"``
    """
    q = (query or "").strip()
    if not q:
        raise ValueError("검색어가 비어 있습니다.")

    if not has_playwright():
        if copy_for_manual is None:
            raise RuntimeError(
                "자동 전송을 사용할 수 없습니다.\n"
                "검색어를 복사한 뒤 Genspark 채팅에 붙여넣으세요."
            )
        copy_for_manual(q)
        open_genspark_chat_in_chrome()
        _emit(on_status, "검색어 복사 · Chrome 열림 — 입력란에 Ctrl+V")
        return "manual"

    _emit(on_status, "Genspark 채팅에 검색어 전송 중…")
    get_chat_session(profile_dir).submit_search(q)
    _emit(on_status, "검색어를 채팅에 전송했습니다.")
    return "auto"
