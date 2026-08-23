# -*- coding: utf-8 -*-
"""Genspark AI Chat — 파일 첨부·보정 명령 (Playwright CDP)."""

from __future__ import annotations

import asyncio
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Callable

from srt_edit.paths import GENSPARK_AI_CHAT_URL, default_correct_command

ProgressCb = Callable[[str, float], None]


def _emit_progress(
    on_progress: ProgressCb | None, msg: str, pct: float
) -> None:
    if on_progress is None:
        return
    try:
        on_progress(msg, float(pct))
    except Exception:
        pass

# 모듈 전용 ChromeDebug (다른 Genspark 모듈과 포트·프로필 분리)
_CDP_PORT = 9232
_CDP_PORTS = (9232,)
_CHROME_DEBUG_USER_DATA = Path(r"C:\ChromeDebug_2_4")
_PROFILE_DIRNAME = ".genspark_srt_edit_profile"
# Genspark AI Chat 모델 (브라우저 열기 후 자동 선택)
_TARGET_CHAT_MODEL = "Claude Opus 4.6"
_TARGET_CHAT_MODEL_RE = re.compile(
    r"claude\s*opus\s*4\s*[.\s]?6|opus\s*4\s*[.\s]?6",
    re.IGNORECASE,
)
_CHAT_MODEL_CHIP_RE = re.compile(
    r"claude|opus|sonnet|gpt|gemini|grok|mixture|deepseek|model|모델",
    re.IGNORECASE,
)


def find_chrome_exe() -> Path | None:
    candidates: list[Path] = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    for key in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base = os.environ.get(key, "")
        if base:
            candidates.append(
                Path(base) / "Google" / "Chrome" / "Application" / "chrome.exe"
            )
    seen: set[str] = set()
    for p in candidates:
        key = str(p).lower()
        if key in seen:
            continue
        seen.add(key)
        if p.is_file():
            return p
    return None


def close_chrome_debug(*, user_data_dir: Path | None = None) -> None:
    """이 모듈 ChromeDebug(CDP)만 종료 — 다른 모듈 포트·프로필은 건드리지 않음."""
    reset_session()
    data = str(Path(user_data_dir or _CHROME_DEBUG_USER_DATA).resolve())
    data_esc = data.replace("'", "''")
    if sys.platform == "win32":
        ps = (
            "$ud='"
            + data_esc
            + "';"
            "$ports=@("
            + ",".join(str(p) for p in _CDP_PORTS)
            + ");"
            "Get-CimInstance Win32_Process -Filter \"Name='chrome.exe'\" | "
            "ForEach-Object {"
            "  $cl=$_.CommandLine; if(-not $cl){return};"
            "  $hit=$false;"
            "  if($cl -like ('*'+$ud+'*')){$hit=$true};"
            "  foreach($p in $ports){"
            "    if(($cl -like ('*--remote-debugging-port='+$p+'*')) -and "
            "       ($cl -like ('*'+$ud+'*'))){$hit=$true}"
            "  };"
            "  if($hit){Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue}"
            "}"
        )
        try:
            subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-Command",
                    ps,
                ],
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    time.sleep(0.35)


def clear_chrome_session_restore(user_data_dir: Path | None = None) -> None:
    """이전 창·탭 복원을 막아 탭이 쌓이지 않게 한다."""
    root = Path(user_data_dir or _CHROME_DEBUG_USER_DATA)
    default = root / "Default"
    if not default.is_dir():
        return
    for name in (
        "Current Session",
        "Current Tabs",
        "Last Session",
        "Last Tabs",
        "Session Storage",
    ):
        p = default / name
        try:
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
        except OSError:
            pass
    sessions = default / "Sessions"
    if sessions.is_dir():
        shutil.rmtree(sessions, ignore_errors=True)


def wait_cdp_ready(*, debug_port: int = _CDP_PORT, timeout_sec: float = 45.0) -> bool:
    """ChromeDebug remote debugging 포트가 응답할 때까지 대기."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{int(debug_port)}/json/version"
    deadline = time.time() + max(0.5, float(timeout_sec))
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1.0) as resp:
                if getattr(resp, "status", 200) == 200:
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            pass
        time.sleep(0.25)
    return False


def open_chrome_debug(
    url: str = GENSPARK_AI_CHAT_URL,
    *,
    debug_port: int = _CDP_PORT,
    user_data_dir: Path | None = None,
    restart: bool = True,
) -> dict[str, str]:
    """고정 디버그 Chrome 실행.

    ``restart=True`` 이면 기존 ChromeDebug 을 종료한 뒤 다시 연다.
    ``restart=False`` 이고 CDP 가 이미 응답하면 재실행하지 않는다.
    """
    data_dir = Path(user_data_dir or _CHROME_DEBUG_USER_DATA)
    if not restart and wait_cdp_ready(debug_port=debug_port, timeout_sec=1.2):
        return {
            "mode": "chrome_debug",
            "debug_port": str(debug_port),
            "user_data": str(data_dir.resolve()),
            "reused": "1",
        }
    if restart:
        close_chrome_debug(user_data_dir=user_data_dir)
        clear_chrome_session_restore(user_data_dir)
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\nChrome 설치 후 다시 시도하세요."
        )
    data_dir.mkdir(parents=True, exist_ok=True)
    reset_session()
    args: list[str] = [
        str(chrome),
        f"--remote-debugging-port={int(debug_port)}",
        f"--user-data-dir={data_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--new-window",
        url,
    ]
    kwargs: dict = {"args": args, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(**kwargs)
    if not wait_cdp_ready(debug_port=debug_port, timeout_sec=45.0):
        raise RuntimeError(
            f"ChromeDebug(CDP :{debug_port})에 연결하지 못했습니다.\n"
            "Chrome이 완전히 뜬 뒤 「브라우저 열기」를 다시 눌러 주세요."
        )
    return {
        "mode": "chrome_debug",
        "debug_port": str(debug_port),
        "user_data": str(data_dir.resolve()),
        "reused": "0",
    }


def has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


async def _is_logged_in(page: Any) -> bool:
    """이미 로그인된 세션인지 휴리스틱 판별."""
    try:
        url = (page.url or "").lower()
        if "accounts.google.com" in url:
            return False
        return bool(
            await page.evaluate(
                """() => {
                  const t = ((document.body && document.body.innerText) || '').slice(0, 8000);
                  if (/accounts\\.google\\.com/i.test(location.href)) return false;
                  const needsLogin = /Sign\\s*in|Log\\s*in|로그인|Continue with Google/i.test(t)
                    && !/Sign\\s*out|Log\\s*out|로그아웃/i.test(t);
                  if (needsLogin) return false;
                  const hasAvatar = !!document.querySelector(
                    'img[alt*="avatar" i], img[alt*="profile" i], [data-testid*="avatar" i]'
                  );
                  const hasUserMenu = !!document.querySelector(
                    '[aria-label*="account" i], [aria-label*="Account" i], [aria-label*="프로필" i]'
                  );
                  if (hasAvatar || hasUserMenu) return true;
                  const hasPrompt = !!document.querySelector(
                    "textarea, [contenteditable='true'], [role='textbox']"
                  );
                  return hasPrompt && !needsLogin;
                }"""
            )
        )
    except Exception:
        return False


async def _type_into(page: Any, selectors: tuple[str, ...], text: str) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        try:
            if not await loc.is_visible(timeout=2500):
                continue
            await loc.click(timeout=4000)
            await page.wait_for_timeout(200)
            try:
                await loc.fill("")
            except Exception:
                pass
            await page.keyboard.press("Control+A")
            await page.keyboard.press("Backspace")
            await page.keyboard.type(text, delay=25)
            await page.wait_for_timeout(300)
            return True
        except Exception:
            continue
    return False


async def _click_by_text(page: Any, texts: tuple[str, ...]) -> bool:
    for text in texts:
        for sel in (
            f"button:has-text('{text}')",
            f"[role='button']:has-text('{text}')",
            f"[role='option']:has-text('{text}')",
            f"[role='menuitem']:has-text('{text}')",
            f"li:has-text('{text}')",
            f"a:has-text('{text}')",
            f"label:has-text('{text}')",
            f"span:has-text('{text}')",
            f"div:has-text('{text}')",
        ):
            loc = page.locator(sel).first
            try:
                if not await loc.is_visible(timeout=800):
                    continue
                await loc.click(timeout=4000, force=False)
                await page.wait_for_timeout(600)
                return True
            except Exception:
                continue
    return False


async def _click_login_entry(page: Any) -> bool:
    for text in (
        "Continue with Google",
        "Google로 계속",
        "Sign in with Google",
        "Sign in with google",
        "Sign in",
        "Log in",
        "Login",
        "로그인",
    ):
        if await _click_by_text(page, (text,)):
            return True
    return False


async def _pick_google_account(page: Any, email: str) -> bool:
    email = (email or "").strip()
    if not email:
        return False
    for sel in (
        f'div[data-identifier="{email}"]',
        f'div[data-email="{email}"]',
        f'[data-identifier="{email}"]',
        f'text="{email}"',
        f'div:has-text("{email}")',
        f'li:has-text("{email}")',
        f'div[role="link"]:has-text("{email}")',
    ):
        loc = page.locator(sel).first
        try:
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=4000)
                await page.wait_for_timeout(1000)
                return True
        except Exception:
            continue
    return False


async def _click_next(page: Any) -> None:
    for text in ("Next", "다음", "Continue", "계속"):
        if await _click_by_text(page, (text,)):
            return
    try:
        await page.keyboard.press("Enter")
    except Exception:
        pass


async def _fill_google_credentials(page: Any, email: str, password: str) -> bool:
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        return False
    await _pick_google_account(page, email)
    email_ok = await _type_into(
        page,
        (
            'input[type="email"]',
            "#identifierId",
            'input[name="identifier"]',
            'input[autocomplete="username"]',
        ),
        email,
    )
    if email_ok:
        await _click_next(page)
        await page.wait_for_timeout(1800)
    await _pick_google_account(page, email)
    await page.wait_for_timeout(600)
    pw_ok = False
    for _ in range(20):
        pw_ok = await _type_into(
            page,
            (
                'input[type="password"]',
                'input[name="Passwd"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
            ),
            password,
        )
        if pw_ok:
            break
        if await _type_into(
            page,
            ('input[type="email"]', "#identifierId", 'input[name="identifier"]'),
            email,
        ):
            await _click_next(page)
        await page.wait_for_timeout(800)
    if not pw_ok:
        return False
    await _click_next(page)
    await page.wait_for_timeout(2000)
    for text in (
        "Not now",
        "나중에",
        "Skip",
        "건너뛰기",
        "Continue",
        "계속",
        "Yes",
        "확인",
        "I understand",
        "이해했습니다",
    ):
        try:
            if await _click_by_text(page, (text,)):
                await page.wait_for_timeout(700)
        except Exception:
            pass
    return True


async def _wait_back_to_genspark(page: Any, *, seconds: int = 45) -> bool:
    for _ in range(max(1, seconds * 2)):
        url = (page.url or "").lower()
        if "genspark.ai" in url and "accounts.google.com" not in url:
            await page.wait_for_timeout(1000)
            return True
        await page.wait_for_timeout(500)
    return "genspark.ai" in (page.url or "").lower()


async def _google_login(
    page: Any,
    email: str,
    password: str,
    *,
    context: Any | None = None,
) -> bool:
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        return False
    login_page = page
    for attempt in range(3):
        popup: Any | None = None
        if context is not None:
            try:
                async with context.expect_page(timeout=4000) as pi:
                    await _click_login_entry(page)
                popup = await pi.value
            except Exception:
                await _click_login_entry(page)
        else:
            await _click_login_entry(page)
        if popup is not None:
            try:
                await popup.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            login_page = popup
            break
        for _ in range(20):
            if "accounts.google.com" in (page.url or "").lower():
                login_page = page
                break
            await _click_by_text(
                page,
                (
                    "Continue with Google",
                    "Google로 계속",
                    "Sign in with Google",
                    "Google",
                ),
            )
            await page.wait_for_timeout(400)
        else:
            if attempt < 2:
                continue
        break
    for _ in range(30):
        cur = (login_page.url or "").lower()
        if "accounts.google.com" in cur or await login_page.locator(
            'input[type="email"], input[type="password"], #identifierId'
        ).count():
            break
        await page.wait_for_timeout(400)
        if context is not None:
            for p in context.pages:
                if "accounts.google.com" in (p.url or "").lower():
                    login_page = p
                    break
    filled = await _fill_google_credentials(login_page, email, password)
    if not filled:
        e_ok = await _type_into(
            page,
            (
                'input[type="email"]',
                'input[name="email"]',
                'input[autocomplete="username"]',
            ),
            email,
        )
        p_ok = await _type_into(
            page,
            (
                'input[type="password"]',
                'input[name="password"]',
                'input[autocomplete="current-password"]',
            ),
            password,
        )
        if e_ok and p_ok:
            await _click_next(page)
            filled = True
    if not filled:
        return False
    if login_page is not page:
        try:
            await login_page.wait_for_event("close", timeout=20000)
        except Exception:
            pass
        try:
            if not login_page.is_closed():
                await _wait_back_to_genspark(login_page, seconds=20)
        except Exception:
            pass
    ok = await _wait_back_to_genspark(page, seconds=40)
    if ok:
        return True
    return await _is_logged_in(page)


async def _ensure_login(
    page: Any,
    email: str,
    password: str,
    *,
    context: Any | None = None,
    force: bool = False,
) -> dict[str, bool]:
    if not force and await _is_logged_in(page):
        return {"logged_in": True, "attempted": False, "filled": False}
    if not (email or "").strip() or not password:
        return {"logged_in": False, "attempted": False, "filled": False}
    needs = True
    try:
        t = await page.evaluate(
            "() => ((document.body && document.body.innerText) || '').slice(0, 5000)"
        )
        needs = bool(
            re.search(r"Sign\s*in|Log\s*in|로그인|Continue with Google", t or "", re.I)
        ) or not await _is_logged_in(page)
    except Exception:
        needs = True
    if not needs and not force:
        return {"logged_in": True, "attempted": False, "filled": False}
    ok = await _google_login(page, email, password, context=context)
    return {
        "logged_in": bool(ok or await _is_logged_in(page)),
        "attempted": True,
        "filled": True,
    }


async def _launch_context(playwright: Any, profile_dir: Path) -> Any:
    for _ in range(16):
        for port in _CDP_PORTS:
            try:
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}"
                )
                if browser.contexts:
                    return browser.contexts[0]
            except Exception:
                continue
        await asyncio.sleep(0.25)

    profile_dir.mkdir(parents=True, exist_ok=True)
    kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir.resolve()),
        "channel": "chrome",
        "headless": False,
        "locale": "ko-KR",
        "accept_downloads": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    try:
        return await playwright.chromium.launch_persistent_context(**kwargs)
    except Exception:
        browser = await playwright.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        return await browser.new_context(locale="ko-KR", accept_downloads=True)


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
        for i in range(min(n, 8)):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
                tag = await item.evaluate(
                    "el => ((el.tagName||'')+(el.getAttribute('type')||'')).toLowerCase()"
                )
                if "file" in (tag or ""):
                    continue
                await item.click(timeout=3000)
                try:
                    await item.fill(text, timeout=8000)
                except Exception:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.insert_text(text)
                return True
            except Exception:
                continue
    return False


async def _submit(page: Any) -> None:
    for sel in (
        "button:has-text('Send')",
        "button:has-text('전송')",
        "button:has-text('Submit')",
        "button:has-text('실행')",
        "button:has-text('Ask')",
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


async def _pick_genspark_page(context: Any, url: str) -> Any:
    """CDP 컨텍스트에서 Genspark AI Chat 탭을 고른다."""
    pages = list(getattr(context, "pages", []) or [])
    # agents / ai_chat 우선
    for p in reversed(pages):
        try:
            u = (p.url or "").lower()
        except Exception:
            continue
        if "genspark.ai" in u and ("agents" in u or "ai_chat" in u or "chat" in u):
            try:
                await p.bring_to_front()
            except Exception:
                pass
            return p
    for p in reversed(pages):
        try:
            u = (p.url or "").lower()
        except Exception:
            continue
        if "genspark.ai" in u:
            try:
                await p.bring_to_front()
            except Exception:
                pass
            return p
    page = pages[-1] if pages else await context.new_page()
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(500)
    return page


async def _wait_chat_ready(page: Any, *, timeout_ms: int = 90_000) -> None:
    """로그인·채팅 UI가 뜰 때까지 대기."""
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        url = (page.url or "").lower()
        if any(x in url for x in ("login", "signin", "sign-in", "accounts.google")):
            await page.wait_for_timeout(500)
            continue
        try:
            n = await page.locator(
                "textarea:visible, [contenteditable='true']:visible, "
                "[role='textbox']:visible, input[type='file']"
            ).count()
        except Exception:
            n = 0
        if n > 0 and "genspark.ai" in url:
            await page.wait_for_timeout(250)
            return
        await page.wait_for_timeout(350)
    raise RuntimeError(
        "Genspark 채팅 화면을 찾지 못했습니다.\n"
        "브라우저에서 로그인한 뒤 「브라우저 열기」→「보정」을 다시 시도하세요."
    )


def _label_is_claude_opus_46(text: str) -> bool:
    t = (text or "").replace("\n", " ")
    if re.search(r"sonnet", t, re.I):
        return False
    return bool(_TARGET_CHAT_MODEL_RE.search(t))


async def _toolbar_chat_model_label(page: Any) -> str:
    """하단 툴바의 현재 채팅 모델 칩 텍스트."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  const vh = window.innerHeight || 800;
                  const re = /claude|opus|sonnet|gpt|gemini|grok|mixture|deepseek|model|모델/i;
                  const hits = [];
                  const els = document.querySelectorAll(
                    'button, [role="button"], [role="combobox"], [aria-haspopup], div, span'
                  );
                  for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.bottom < vh * 0.55 || r.top > vh - 6) continue;
                    if (r.width < 24 || r.height < 12 || r.height > 64) continue;
                    const t = (el.innerText || el.textContent || '')
                      .replace(/\\s+/g, ' ').trim();
                    if (!t || t.length > 80) continue;
                    if (!re.test(t)) continue;
                    hits.push({ t, h: r.height, bottom: r.bottom });
                  }
                  if (!hits.length) return '';
                  hits.sort((a, b) => a.h - b.h || b.bottom - a.bottom);
                  return hits[0].t;
                }"""
            )
            or ""
        )
    except Exception:
        return ""


async def _open_chat_model_picker(page: Any) -> str:
    """하단 모델 칩을 눌러 목록을 연다."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  const vh = window.innerHeight || 800;
                  const re = /claude|opus|sonnet|gpt|gemini|grok|mixture|deepseek|model|모델/i;
                  const hits = [];
                  const els = document.querySelectorAll(
                    'button, [role="button"], [role="combobox"], [aria-haspopup], div, span'
                  );
                  for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.bottom < vh * 0.55 || r.top > vh - 6) continue;
                    if (r.width < 24 || r.height < 12 || r.height > 64) continue;
                    const t = (el.innerText || el.textContent || '')
                      .replace(/\\s+/g, ' ').trim();
                    if (!t || t.length > 80) continue;
                    if (!re.test(t)) continue;
                    hits.push({ el, t, h: r.height, bottom: r.bottom });
                  }
                  hits.sort((a, b) => a.h - b.h || b.bottom - a.bottom);
                  if (!hits.length) return '';
                  hits[0].el.click();
                  return hits[0].t;
                }"""
            )
            or ""
        )
    except Exception:
        return ""


async def _click_claude_opus_46_option(page: Any) -> str:
    """팝업에서 Claude Opus 4.6 항목 클릭 (Sonnet 제외)."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  const roots = Array.from(document.querySelectorAll(
                    '[role="listbox"], [role="menu"], [role="dialog"], '
                    + '[data-radix-popper-content-wrapper], [class*="popover" i], '
                    + '[class*="dropdown" i], [class*="Menu" i]'
                  ));
                  const scope = roots.length ? roots : [document.body];
                  const nodes = [];
                  for (const root of scope) {
                    nodes.push(...root.querySelectorAll(
                      '[role="option"], [role="menuitem"], button, li, div, span, a'
                    ));
                  }
                  const hits = [];
                  const want = /claude\\s*opus\\s*4\\s*[.\\s]?6|opus\\s*4\\s*[.\\s]?6/i;
                  for (const el of nodes) {
                    const t = (el.innerText || el.textContent || '')
                      .replace(/\\s+/g, ' ').trim();
                    if (!t || t.length > 72) continue;
                    if (/sonnet/i.test(t)) continue;
                    if (!want.test(t)) continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 10 || r.height > 90) continue;
                    hits.push({ el, t, h: r.height, y: r.top });
                  }
                  hits.sort((a, b) => a.h - b.h || a.y - b.y);
                  if (!hits.length) return '';
                  hits[0].el.click();
                  return hits[0].t;
                }"""
            )
            or ""
        )
    except Exception:
        return ""


async def _select_claude_opus_46(page: Any) -> bool:
    """AI Chat 모델 칩에서 Claude Opus 4.6 을 선택한다."""
    from srt_edit import diag_log

    before = await _toolbar_chat_model_label(page)
    if _label_is_claude_opus_46(before):
        diag_log.log(f"모델 이미 Opus 4.6: {before[:60]}")
        return True
    diag_log.log(f"모델 선택 시작 현재={before[:60] or '(없음)'} → {_TARGET_CHAT_MODEL}")

    opened = await _open_chat_model_picker(page)
    if opened:
        diag_log.log(f"모델 칩 클릭: {opened[:60]}")
        await page.wait_for_timeout(700)
    else:
        for sel in (
            "button:has-text('Model')",
            "button:has-text('모델')",
            "[aria-label*='Model' i]",
            "[aria-label*='모델' i]",
            "[role='combobox']",
        ):
            loc = page.locator(sel).first
            try:
                if not await loc.is_visible(timeout=500):
                    continue
                await loc.click(timeout=3000)
                await page.wait_for_timeout(700)
                opened = "fallback"
                break
            except Exception:
                continue

    picked = await _click_claude_opus_46_option(page)
    if not picked:
        try:
            loc = page.get_by_role(
                "option", name=re.compile(r"Claude\s*Opus\s*4\.?\s*6", re.I)
            ).first
            if await loc.is_visible(timeout=1200):
                label = (await loc.inner_text() or "").strip()
                if not re.search(r"sonnet", label, re.I):
                    await loc.click(timeout=4000)
                    picked = label or _TARGET_CHAT_MODEL
                    await page.wait_for_timeout(500)
        except Exception:
            pass
    if not picked:
        for text in (
            "Claude Opus 4.6",
            "Opus 4.6",
            "claude-opus-4-6",
        ):
            loc = page.locator(
                f"[role='option']:has-text('{text}'), "
                f"[role='menuitem']:has-text('{text}')"
            ).first
            try:
                if not await loc.is_visible(timeout=700):
                    continue
                label = (await loc.inner_text() or "").strip()
                if re.search(r"sonnet", label, re.I):
                    continue
                await loc.click(timeout=4000)
                picked = label or text
                await page.wait_for_timeout(500)
                break
            except Exception:
                continue

    after = await _toolbar_chat_model_label(page)
    ok = _label_is_claude_opus_46(after)
    if not ok and picked and _label_is_claude_opus_46(picked):
        ok = True
    diag_log.log(
        f"모델 선택 결과 ok={ok} 칩={after[:60] or '(없음)'} "
        f"picked={(picked or '')[:40]}"
    )
    return ok


def _iter_targets(page: Any) -> list[Any]:
    """본문 + iframe 대상."""
    out: list[Any] = [page]
    try:
        for fr in page.frames:
            if fr is not page.main_frame:
                out.append(fr)
    except Exception:
        pass
    return out


async def _try_set_files_on_target(target: Any, paths: list[str]) -> bool:
    for sel in ("input[type='file']", "input[type='file'][multiple]"):
        loc = target.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            n = 0
        for i in range(min(n, 12)):
            item = loc.nth(i)
            try:
                await item.wait_for(state="attached", timeout=3000)
                await item.set_input_files(paths, timeout=12_000)
                await asyncio.sleep(0.35)
                return True
            except Exception:
                continue
    return False


async def _try_filechooser_click(target: Any, paths: list[str]) -> bool:
    page = getattr(target, "page", target)
    for text in (
        "Attach",
        "Upload",
        "첨부",
        "파일",
        "Add file",
        "업로드",
        "Add",
        "+",
    ):
        for sel in (
            f"button:has-text('{text}')",
            f"[role='button']:has-text('{text}')",
            f"[aria-label*='{text}' i]",
            f"[title*='{text}' i]",
            f"label:has-text('{text}')",
        ):
            btn = target.locator(sel).first
            try:
                if not await btn.is_visible(timeout=500):
                    continue
                async with page.expect_file_chooser(timeout=10_000) as fc_info:
                    await btn.click(timeout=4000)
                chooser = await fc_info.value
                await chooser.set_files(paths)
                await asyncio.sleep(0.35)
                return True
            except Exception:
                continue
    for sel in (
        "[data-testid*='attach' i]",
        "[data-testid*='upload' i]",
        "[aria-label*='attach' i]",
        "[aria-label*='upload' i]",
        "[aria-label*='file' i]",
        "[aria-label*='클립' i]",
        "button:has(svg)",
    ):
        btns = target.locator(sel)
        try:
            n = await btns.count()
        except Exception:
            n = 0
        for i in range(min(n, 16)):
            btn = btns.nth(i)
            try:
                if not await btn.is_visible(timeout=350):
                    continue
                async with page.expect_file_chooser(timeout=7000) as fc_info:
                    await btn.click(timeout=3000)
                chooser = await fc_info.value
                await chooser.set_files(paths)
                await asyncio.sleep(0.35)
                return True
            except Exception:
                continue
    return False


async def _attach_files(page: Any, files: list[Path]) -> bool:
    """input[type=file] / filechooser — 모든 프레임 포함."""
    paths = [str(Path(p).resolve()) for p in files if Path(p).is_file()]
    if not paths:
        raise RuntimeError("첨부할 파일이 없습니다.")

    await _wait_chat_ready(page)

    for _attempt in range(10):
        for target in _iter_targets(page):
            if await _try_set_files_on_target(target, paths):
                return True
        for target in _iter_targets(page):
            if await _try_filechooser_click(target, paths):
                return True
        # 입력창 포커스 후 클립 버튼이 생기는 UI 대응
        try:
            await page.locator(
                "textarea:visible, [contenteditable='true']:visible"
            ).first.click(timeout=2000)
        except Exception:
            pass
        await page.wait_for_timeout(1000)

    return False


def _read_text_file(path: Path, *, limit: int = 400_000) -> str:
    try:
        raw = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if len(raw) > limit:
        return raw[:limit] + "\n…(이하 생략)"
    return raw


def _response_looks_finished(txt: str, *, original: str = "") -> bool:
    """응답 완료: 페이지에 end 마커 + 원본에 가까운 실보정본."""
    from srt_edit.srt_diff import (
        changed_cue_count,
        cue_count_fit,
        extract_srt_payload,
        has_end_marker,
        parse_srt_cues,
    )

    if not txt or "-->" not in txt:
        return False
    # end 필수 (하단 UI 문구는 has_end_marker 가 건너뜀)
    if not has_end_marker(txt):
        return False
    payload = extract_srt_payload(
        txt, original=original or None, log_detail=False
    )
    n = len(parse_srt_cues(payload)) if payload else 0
    orig_n = len(parse_srt_cues(original)) if original else 0
    if orig_n > 0:
        if not cue_count_fit(n, orig_n):
            return False
        if changed_cue_count(payload, original) <= 0:
            return False
        return True
    return n >= 3


async def _page_chat_text(page: Any) -> str:
    """채팅 DOM에서 보정 응답 텍스트 수집 (가장 적합한 한 덩어리만)."""
    try:
        return await page.evaluate(
            """() => {
              const parts = [];
              const nodes = Array.from(document.querySelectorAll('*'));
              for (const el of nodes) {
                try {
                  if (el.scrollHeight > el.clientHeight + 80) {
                    el.scrollTop = el.scrollHeight;
                  }
                } catch (e) {}
              }
              window.scrollTo(0, document.body.scrollHeight);
              const push = (t) => {
                const s = (t || '').trim();
                if (s.length > 40) parts.push(s);
              };
              push(document.body && document.body.innerText);
              for (const sel of [
                'pre', 'code',
                '[class*="markdown" i]', '[class*="message" i]',
                '[class*="assistant" i]', '[class*="prose" i]',
                '[data-testid*="message" i]', 'article'
              ]) {
                for (const el of document.querySelectorAll(sel)) {
                  push(el.innerText || el.textContent || '');
                }
              }
              const hasStart = (p) =>
                /(?:^|\\n)\\s*(?:==\\s*)?start(?:\\s*==)?(?:\\s*(?:\\n|$)|[ \\t]*\\d)/i.test(p);
              const hasEnd = (p) =>
                /(?:^|\\n)\\s*(?:==\\s*)?end(?:\\s*==)?\\s*(?:\\n|$)/i.test(p)
                || /\\s+(?:==\\s*)?end(?:\\s*==)?\\s*$/im.test(p);
              const hasMarkers = (p) => hasStart(p) && hasEnd(p);
              const arrowCount = (p) => (p.match(/-->/g) || []).length;
              const marked = parts.filter(hasMarkers);
              const pool = marked.length
                ? marked
                : parts.filter(p => /-->/.test(p));
              if (!pool.length) return parts.sort((a, b) => b.length - a.length)[0] || '';
              // 여러 조각을 이어붙이지 않음 — 화살표(큐) 수가 적당한 최장 1개
              pool.sort((a, b) => {
                const ma = hasMarkers(a) ? 1 : 0;
                const mb = hasMarkers(b) ? 1 : 0;
                if (mb !== ma) return mb - ma;
                const ca = arrowCount(a);
                const cb = arrowCount(b);
                if (cb !== ca) return cb - ca;
                return b.length - a.length;
              });
              return pool[0] || '';
            }"""
        )
    except Exception:
        return ""


async def _try_click_copy_near_end(page: Any) -> str:
    """Copy 버튼을 눌러 클립보드에서 SRT 읽기."""
    try:
        clicked = await page.evaluate(
            """() => {
              const all = Array.from(
                document.querySelectorAll('button, [role="button"], a')
              );
              const isCopy = (el) => {
                const t = ((el.innerText || '') + ' '
                  + (el.getAttribute('aria-label') || '') + ' '
                  + (el.getAttribute('title') || '')).toLowerCase();
                return /copy|복사|clipboard/.test(t);
              };
              const html = (document.body && document.body.innerText) || '';
              const hasStart =
                /(?:^|\\n)\\s*(?:==\\s*)?start(?:\\s*==)?(?:\\s*(?:\\n|$)|[ \\t]*\\d)/i.test(html);
              const hasEnd =
                /(?:^|\\n)\\s*(?:==\\s*)?end(?:\\s*==)?\\s*(?:\\n|$)/i.test(html)
                || /\\s+(?:==\\s*)?end(?:\\s*==)?\\s*$/im.test(html);
              if (!hasStart || !hasEnd) return false;
              for (let i = all.length - 1; i >= 0; i--) {
                const el = all[i];
                if (!isCopy(el)) continue;
                try { el.click(); return true; } catch (e) {}
              }
              return false;
            }"""
        )
    except Exception:
        clicked = False
    if not clicked:
        return ""
    await page.wait_for_timeout(500)
    try:
        clip = await page.evaluate(
            """async () => {
              try { return await navigator.clipboard.readText(); }
              catch (e) { return ''; }
            }"""
        )
    except Exception:
        clip = ""
    return (clip or "").strip()


async def _keyboard_copy_page(page: Any) -> str:
    """본문 포커스 후 Ctrl+A / Ctrl+C 로 클립보드 수집 (권한 있을 때)."""
    try:
        await page.evaluate(
            """() => {
              const el = document.body;
              if (!el) return;
              const range = document.createRange();
              range.selectNodeContents(el);
              const sel = window.getSelection();
              sel.removeAllRanges();
              sel.addRange(range);
            }"""
        )
        await page.keyboard.press("Control+C")
        await page.wait_for_timeout(400)
        clip = await page.evaluate(
            """async () => {
              try { return await navigator.clipboard.readText(); }
              catch (e) { return ''; }
            }"""
        )
        return (clip or "").strip()
    except Exception:
        return ""


async def _scrape_corrected_srt(
    page: Any,
    *,
    wait_ms: int | None = None,
    original: str = "",
    on_progress: ProgressCb | None = None,
) -> str:
    """응답 SRT 자동 추출 — end/마지막 큐 + 원본 근접 큐 수면 완료.

    Genspark 가 ``start`` 줄을 생략하고 ``… end`` 만 붙이는 경우도 허용한다.
    """
    from srt_edit import diag_log
    from srt_edit.srt_diff import (
        cue_count_fit,
        extract_srt_payload,
        has_end_marker,
        has_start_end_markers,
        has_start_marker,
        parse_srt_cues,
        reaches_last_original_cue,
    )

    orig_n = len(parse_srt_cues(original)) if original else 0
    if wait_ms is None:
        # 402큐 한 줄 응답은 10분 이상 걸릴 수 있음
        wait_ms = int(min(1_200_000, max(420_000, 240_000 + orig_n * 1200)))
    min_cues = max(3, int(orig_n * 0.80)) if orig_n else 3
    target_cues = max(min_cues, int(orig_n * 0.90)) if orig_n else min_cues
    max_cues = (orig_n + max(8, int(orig_n * 0.15))) if orig_n else 10_000
    deadline = time.time() + wait_ms / 1000.0
    started = time.time()
    best = ""
    best_n = 0
    best_diff = -1
    stable_hits = 0
    copy_tried = False
    kb_tried = False
    tick = 0
    last_raw = ""

    diag_log.log(
        f"스크래프시작 wait_ms={wait_ms} 원본큐={orig_n} "
        f"min_cues={min_cues} target={target_cues} max_cues={max_cues}"
    )
    _emit_progress(on_progress, "AI 응답 대기…", 50.0)

    def _scrape_pct() -> float:
        wait_sec = max(1.0, wait_ms / 1000.0)
        elapsed = min(1.0, (time.time() - started) / wait_sec)
        cue_r = (best_n / orig_n) if orig_n else 0.0
        return 50.0 + min(45.0, max(elapsed * 40.0, cue_r * 45.0))

    def _from_text(txt: str, *, src: str) -> tuple[str, int, int]:
        if not txt or "-->" not in txt:
            return "", 0, 0
        payload = extract_srt_payload(
            txt, original=original or None, log_detail=False
        )
        n = len(parse_srt_cues(payload)) if payload and "-->" in payload else 0
        if orig_n > 0 and n > max_cues:
            diag_log.log(f"스크래프[{src}] 큐과다 {n}>{max_cues} → 무시")
            return "", 0, 0
        if n > 0 and n < min_cues:
            return "", 0, 0
        diff = 0
        if original and n > 0:
            from srt_edit.srt_diff import changed_cue_count

            diff = changed_cue_count(payload, original)
            # 원본과 완전 동일하면 실패로 보고 계속 대기
            if diff == 0 and cue_count_fit(n, orig_n):
                diag_log.log(f"스크래프[{src}] 원본과 동일 → 무시 큐={n}")
                return "", 0, 0
        if n:
            diag_log.log(
                f"스크래프[{src}] 추출큐={n} 변경={diff} chars={len(payload)} "
                f"end={has_end_marker(txt)} "
                f"lastCue={reaches_last_original_cue(txt, original)}"
            )
        return (payload, n, diff) if n else ("", 0, 0)

    while time.time() < deadline:
        txt = await _page_chat_text(page)
        last_raw = txt or last_raw
        finished = _response_looks_finished(txt, original=original)
        payload, n, diff = _from_text(txt, src="dom")
        tick += 1
        if tick == 1 or tick % 5 == 0 or (finished and n >= min_cues):
            if tick == 1 or tick % 15 == 0 or (finished and n >= min_cues):
                diag_log.log(
                    f"스크래프 tick={tick} chars={len(txt or '')} "
                    f"start={has_start_marker(txt or '')} "
                    f"end={has_end_marker(txt or '')} "
                    f"lastCue={reaches_last_original_cue(txt or '', original)} "
                    f"finished={finished} "
                    f"n={n} diff={diff} best={best_n} stable={stable_hits} "
                    f"tail={diag_log.preview((txt or '')[-200:], head=160, tail=0)}"
                )
            cue_note = (
                f"큐 {best_n}/{orig_n}" if orig_n else f"큐 {best_n}"
            )
            _emit_progress(
                on_progress,
                f"AI 응답 대기… {cue_note}",
                _scrape_pct(),
            )

        if finished and n < target_cues and not copy_tried:
            copy_tried = True
            diag_log.log("스크래프 Copy버튼 시도")
            clip = await _try_click_copy_near_end(page)
            if clip:
                last_raw = clip
            cp, cn, cd = _from_text(clip, src="copy")
            if cn > n or (cn == n and cd > diff):
                payload, n, diff = cp, cn, cd
        if finished and n < target_cues and not kb_tried:
            kb_tried = True
            diag_log.log("스크래프 Ctrl+C 시도")
            clip = await _keyboard_copy_page(page)
            if clip:
                last_raw = clip
            cp, cn, cd = _from_text(clip, src="kbd")
            if cn > n or (cn == n and cd > diff):
                payload, n, diff = cp, cn, cd

        if payload and n >= min_cues and n <= max_cues:
            better = (
                n > best_n
                or (n == best_n and diff > best_diff)
                or (n == best_n and diff == best_diff and len(payload) > len(best))
            )
            if payload == best:
                stable_hits += 1
            else:
                if better:
                    best = payload
                    best_n = n
                    best_diff = diff
                    diag_log.log(
                        f"스크래프 best갱신 큐={best_n} 변경={best_diff}"
                    )
                stable_hits = 0
            # end+마지막큐+변경: 스트리밍 완료로 보고 즉시 채택 (미완성 위험 낮음)
            if (
                finished
                and best_n >= min_cues
                and best_diff > 0
                and stable_hits >= 1
                and reaches_last_original_cue(txt or last_raw, original)
            ):
                diag_log.log(
                    f"스크래프완료 end+lastCue 큐={best_n} 변경={best_diff}"
                )
                return best
            if (
                finished
                and best_n >= min_cues
                and best_diff > 0
                and stable_hits >= 1
            ):
                # 짧은 재확인만 (구 1.5s → 0.4s)
                await page.wait_for_timeout(400)
                p2, n2, d2 = _from_text(
                    await _page_chat_text(page), src="confirm"
                )
                if n2 >= best_n and d2 >= best_diff:
                    diag_log.log(f"스크래프완료 confirm 큐={n2} 변경={d2}")
                    return p2 or best
                diag_log.log(
                    f"스크래프완료 best 큐={best_n} 변경={best_diff}"
                )
                return best
            if (
                best_n >= target_cues
                and best_diff > 0
                and stable_hits >= 1
                and finished
            ):
                diag_log.log(
                    f"스크래프완료 target+stable 큐={best_n} 변경={best_diff}"
                )
                return best

        await page.wait_for_timeout(1000)

    for name, getter in (
        ("copy_final", _try_click_copy_near_end),
        ("kbd_final", _keyboard_copy_page),
    ):
        if best_n >= min_cues and best_diff > 0 and (
            has_end_marker(last_raw)
            or reaches_last_original_cue(last_raw, original)
        ):
            break
        diag_log.log(f"스크래프 마감재시도 {name}")
        clip = await getter(page)
        if clip:
            last_raw = clip
        cp, cn, cd = _from_text(clip, src=name)
        if cn > best_n or (cn == best_n and cd > best_diff):
            best, best_n, best_diff = cp, cn, cd

    dump_dir = diag_log.log_path().parent if diag_log.log_path() else None
    if dump_dir is not None and last_raw:
        from srt_edit.srt_diff import normalize_start_end_boundaries

        diag_log.write_dump(
            dump_dir / "srt_edit_last_raw.txt",
            normalize_start_end_boundaries(last_raw),
        )
    # 최종 페이지 한 번 더
    try:
        final_txt = await _page_chat_text(page)
        if final_txt:
            last_raw = final_txt
            cp, cn, cd = _from_text(final_txt, src="final")
            if cn > best_n or (cn == best_n and cd > best_diff):
                best, best_n, best_diff = cp, cn, cd
    except Exception:
        pass

    complete = has_end_marker(last_raw) or reaches_last_original_cue(
        last_raw, original
    )
    diag_log.log(
        f"스크래프종료 best_큐={best_n} 변경={best_diff} "
        f"complete={complete} end={has_end_marker(last_raw)} "
        f"(min={min_cues}) 결과chars={len(best)}"
    )
    if best and best_diff > 0 and best_n >= min_cues and complete:
        return best
    if best and best_diff > 0 and best_n >= target_cues:
        diag_log.log("스크래프결과 end미확인이나 큐·변경 충분 → 채택")
        return best
    diag_log.log("스크래프결과 부족 → 자동저장 보류")
    return ""


def _build_inline_payload(
    *,
    srt: Path,
    tts: Path,
    md: Path,
    command: str,
) -> str:
    """첨부 UI 실패 시 — 세 파일 본문을 입력창에 넣어 보정 요청."""
    parts = [
        command.strip()
        or default_correct_command(
            srt_name=srt.name, tts_name=tts.name, md_name=md.name
        ),
        "",
        f"===== MD 지침: {md.name} =====",
        _read_text_file(md, limit=80_000),
        "",
        f"===== TTS 대본: {tts.name} =====",
        _read_text_file(tts, limit=200_000),
        "",
        f"===== STT SRT: {srt.name} =====",
        _read_text_file(srt, limit=200_000),
        "",
        "위 MD 지침과 TTS 대본을 기준으로 SRT만 교정해, 수정된 전체 SRT만 출력해 주세요.",
    ]
    return "\n".join(parts)


class GensparkChatSession:
    def __init__(self, profile_dir: Path) -> None:
        self._profile_dir = profile_dir
        self._cmd_q: queue.Queue[tuple[str, Any, queue.Queue]] = queue.Queue()
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

    def _call(self, op: str, arg: Any = None, *, timeout: float = 300.0) -> Any:
        self._ensure_thread()
        resp_q: queue.Queue[tuple[bool, Any, Exception | None]] = queue.Queue()
        self._cmd_q.put((op, arg, resp_q))
        try:
            ok, result, err = resp_q.get(timeout=timeout)
        except queue.Empty as e:
            raise TimeoutError("Genspark 작업 시간이 초과되었습니다.") from e
        if not ok and err:
            raise err
        return result

    def open_chat(
        self,
        *,
        url: str = GENSPARK_AI_CHAT_URL,
        email: str = "",
        password: str = "",
    ) -> dict[str, bool]:
        return self._call(
            "open",
            {"url": url, "email": email, "password": password},
            timeout=180.0,
        )

    def attach_and_correct(
        self,
        *,
        srt_path: Path,
        tts_path: Path,
        md_path: Path,
        command: str = "",
        url: str = GENSPARK_AI_CHAT_URL,
        email: str = "",
        password: str = "",
        on_progress: ProgressCb | None = None,
    ) -> dict[str, Any]:
        return self._call(
            "correct",
            {
                "url": url,
                "srt": str(srt_path),
                "tts": str(tts_path),
                "md": str(md_path),
                "command": command,
                "email": email,
                "password": password,
                "on_progress": on_progress,
            },
            timeout=960.0,
        )

    def stop(self) -> None:
        try:
            self._call("stop", timeout=10.0)
        except Exception:
            pass

    async def _async_worker(self) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await _launch_context(pw, self._profile_dir)
            try:
                await context.grant_permissions(
                    ["clipboard-read", "clipboard-write"],
                    origin="https://www.genspark.ai",
                )
            except Exception:
                pass
            page = await _pick_genspark_page(context, GENSPARK_AI_CHAT_URL)

            while True:
                try:
                    op, arg, resp_q = self._cmd_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    continue
                try:
                    if op == "open":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_CHAT_URL
                        email = str(data.get("email") or "")
                        password = str(data.get("password") or "")
                        page = await _pick_genspark_page(context, url)
                        cur = (page.url or "").lower()
                        need_nav = (
                            "genspark.ai" not in cur
                            or "agents" not in cur
                            or "ai_chat" not in cur
                        )
                        if need_nav:
                            await page.goto(
                                url or GENSPARK_AI_CHAT_URL,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            await page.wait_for_timeout(600)
                        login_info = await _ensure_login(
                            page, email, password, context=context
                        )
                        if login_info.get("logged_in"):
                            try:
                                await _wait_chat_ready(page, timeout_ms=45_000)
                                await _select_claude_opus_46(page)
                            except Exception as ex:
                                from srt_edit import diag_log

                                diag_log.log(f"open 모델 선택 경고: {ex}")
                        resp_q.put(
                            (
                                True,
                                {
                                    "ok": True,
                                    "logged_in": bool(login_info.get("logged_in")),
                                    "login_attempted": bool(
                                        login_info.get("attempted")
                                    ),
                                },
                                None,
                            )
                        )
                    elif op == "correct":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_CHAT_URL
                        email = str(data.get("email") or "")
                        password = str(data.get("password") or "")
                        on_prog: ProgressCb | None = data.get("on_progress")
                        srt = Path(data.get("srt") or "")
                        tts = Path(data.get("tts") or "")
                        md = Path(data.get("md") or "")
                        for p, label in ((srt, "SRT"), (tts, "TTS"), (md, "MD")):
                            if not p.is_file():
                                raise RuntimeError(f"{label} 파일이 없습니다: {p}")
                        _emit_progress(on_prog, "Genspark 페이지 연결…", 12.0)
                        page = await _pick_genspark_page(context, url)
                        cur = (page.url or "").lower()
                        need_nav = (
                            "genspark.ai" not in cur
                            or "agents" not in cur
                            or "ai_chat" not in cur
                        )
                        if need_nav:
                            await page.goto(
                                url or GENSPARK_AI_CHAT_URL,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            await page.wait_for_timeout(600)
                        _emit_progress(on_prog, "로그인 확인…", 20.0)
                        login_info = await _ensure_login(
                            page, email, password, context=context
                        )
                        if email and password and not login_info.get("logged_in"):
                            # 한 번 더 시도
                            login_info = await _ensure_login(
                                page,
                                email,
                                password,
                                context=context,
                                force=True,
                            )
                        _emit_progress(on_prog, "채팅 준비…", 28.0)
                        await _wait_chat_ready(page, timeout_ms=60_000)
                        try:
                            _emit_progress(on_prog, "모델 선택…", 32.0)
                            await _select_claude_opus_46(page)
                        except Exception as ex:
                            from srt_edit import diag_log

                            diag_log.log(f"모델 선택 경고: {ex}")
                        cmd = (data.get("command") or "").strip() or default_correct_command(
                            srt_name=srt.name,
                            tts_name=tts.name,
                            md_name=md.name,
                        )
                        _emit_progress(on_prog, "파일 첨부…", 40.0)
                        ok_attach = await _attach_files(page, [srt, tts, md])
                        mode = "attach"
                        if ok_attach:
                            await page.wait_for_timeout(400)
                            _emit_progress(on_prog, "보정 명령 입력…", 45.0)
                            if not await _fill_first_editable(page, cmd):
                                raise RuntimeError("명령 입력창을 찾지 못했습니다.")
                        else:
                            # 첨부 UI 없으면 텍스트 본문 주입 (SRT/TTS/MD는 텍스트 파일)
                            mode = "inline"
                            _emit_progress(on_prog, "본문 주입…", 45.0)
                            payload = _build_inline_payload(
                                srt=srt, tts=tts, md=md, command=cmd
                            )
                            if not await _fill_first_editable(page, payload):
                                raise RuntimeError(
                                    "파일 첨부 UI와 입력창을 모두 찾지 못했습니다.\n"
                                    "Genspark AI Chat에 로그인한 뒤 다시 시도하세요."
                                )
                        _emit_progress(on_prog, "보정 요청 전송…", 48.0)
                        await _submit(page)
                        from srt_edit import diag_log

                        diag_log.log(
                            f"보정제출 mode={mode} attach={ok_attach} "
                            f"srt={srt.name} tts={tts.name} md={md.name}"
                        )
                        orig_srt = _read_text_file(srt, limit=400_000)
                        diag_log.log(
                            f"원본SRT 읽기 chars={len(orig_srt)} "
                            f"path={srt}"
                        )
                        scraped = await _scrape_corrected_srt(
                            page, original=orig_srt, on_progress=on_prog
                        )
                        diag_log.log(
                            f"스크래프결과 chars={len(scraped or '')} "
                            f"head={diag_log.preview(scraped or '')}"
                        )
                        _emit_progress(on_prog, "결과 정리…", 96.0)
                        resp_q.put(
                            (
                                True,
                                {
                                    "ok": True,
                                    "attached": ok_attach,
                                    "mode": mode,
                                    "command": cmd,
                                    "corrected_srt": scraped or "",
                                    "logged_in": bool(login_info.get("logged_in")),
                                    "login_attempted": bool(
                                        login_info.get("attempted")
                                    ),
                                },
                                None,
                            )
                        )
                    elif op == "stop":
                        resp_q.put((True, None, None))
                        break
                    else:
                        resp_q.put(
                            (False, None, RuntimeError(f"알 수 없는 명령: {op}"))
                        )
                except Exception as ex:
                    resp_q.put((False, None, ex))


_session: GensparkChatSession | None = None
_session_lock = threading.Lock()


def reset_session() -> None:
    global _session
    with _session_lock:
        if _session is not None:
            try:
                _session.stop()
            except Exception:
                pass
            _session = None


def get_chat_session(profile_dir: Path) -> GensparkChatSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = GensparkChatSession(profile_dir)
        return _session


def run_correct_flow(
    *,
    srt_path: Path,
    tts_path: Path,
    md_path: Path,
    profile_dir: Path,
    command: str = "",
    open_browser: bool = True,
    url: str = GENSPARK_AI_CHAT_URL,
    email: str = "",
    password: str = "",
    on_progress: ProgressCb | None = None,
) -> dict[str, Any]:
    """브라우저 오픈(옵션) → 자동 로그인 → 첨부 → 보정 명령 전송 → 결과 스크랩."""
    if not has_playwright():
        raise RuntimeError("Playwright가 필요합니다.\npip install playwright")
    if open_browser:
        _emit_progress(on_progress, "Chrome 연결…", 3.0)
        # CDP가 이미 살아 있으면 Chrome 재시작 생략 (변환 시작까지 크게 단축)
        already = wait_cdp_ready(timeout_sec=1.0)
        info = open_chrome_debug(url, restart=not already)
        from srt_edit import diag_log

        diag_log.log(
            f"ChromeDebug reused={info.get('reused')} "
            f"port={info.get('debug_port')} restart={not already}"
        )
        if not already:
            _emit_progress(on_progress, "Chrome 시작…", 8.0)
            time.sleep(0.25)
        else:
            _emit_progress(on_progress, "Chrome 재사용…", 8.0)
    sess = get_chat_session(profile_dir)
    # open_chat 생략 — attach_and_correct 가 로그인·채팅대기·첨부를 한 번에 수행
    return sess.attach_and_correct(
        srt_path=srt_path,
        tts_path=tts_path,
        md_path=md_path,
        command=command,
        url=url,
        email=email,
        password=password,
        on_progress=on_progress,
    )
