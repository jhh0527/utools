# -*- coding: utf-8 -*-
"""Genspark AI Image — Nano banana pro 선택·프롬프트 전송·이미지 수집 (Playwright)."""

from __future__ import annotations

import asyncio
import base64
import os
import queue
import re
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from scene_image.paths import GENSPARK_AI_IMAGE_URL
from scene_image.scene_parse import png_already_exists, srt_png_name
from scene_image.url_filter import (
    is_collectable_image_url,
    is_genspark_file_url,
    is_tracking_url,
)

_NANO_BANANA_PRO_TEXTS = (
    "Nano Banana Pro",
    "Nano banana pro",
    "nano banana pro",
    "NanoBanana Pro",
    "NanoBananaPro",
    "Banana Pro",
)
_PROFILE_DIRNAME = ".genspark_scene_image_profile"
_STORAGE_STATE_NAME = "storage_state.json"
# 브라우저 열기: chrome --remote-debugging-port=9222 --user-data-dir=C:\ChromeDebug
_CDP_PORT = 9222
_CDP_PORTS = (9222, 9232, 9233)
_CHROME_DEBUG_USER_DATA = Path(r"C:\ChromeDebug")
_GENSPARK_FILE_RE = re.compile(
    r"https?://(?:www\.)?genspark\.ai/api/files/[^\s\"'<>]+",
    re.IGNORECASE,
)
_SRT_LABEL_RE = re.compile(r"SRT[_\s-]?(\d{1,6})", re.IGNORECASE)


def storage_state_path(base_dir: Path) -> Path:
    """Playwright storageState 경로 (세션·쿠키 유지)."""
    return Path(base_dir) / _STORAGE_STATE_NAME


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


def image_profile_dir(base_dir: Path) -> Path:
    """레거시 전용 프로필 (계정 Chrome 프로필을 쓸 때는 사용하지 않음)."""
    return base_dir / _PROFILE_DIRNAME


def open_chrome_debug(
    url: str = GENSPARK_AI_IMAGE_URL,
    *,
    debug_port: int = _CDP_PORT,
    user_data_dir: Path | None = None,
) -> dict[str, str]:
    """고정 디버그 Chrome 실행.

    ``chrome.exe --remote-debugging-port=9222 --user-data-dir=C:\\ChromeDebug``
    """
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\nChrome 설치 후 다시 시도하세요."
        )
    data_dir = Path(user_data_dir or _CHROME_DEBUG_USER_DATA)
    data_dir.mkdir(parents=True, exist_ok=True)
    reset_image_session()
    args: list[str] = [
        str(chrome),
        f"--remote-debugging-port={int(debug_port)}",
        f"--user-data-dir={data_dir.resolve()}",
        "--new-window",
        url,
    ]
    kwargs: dict = {"args": args, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(**kwargs)
    return {
        "mode": "chrome_debug",
        "debug_port": str(debug_port),
        "user_data": str(data_dir.resolve()),
    }


def open_genspark_in_chrome(
    url: str = GENSPARK_AI_IMAGE_URL,
    *,
    profile_dir: Path | None = None,
    chrome_user_data: Path | None = None,
    chrome_profile_directory: str | None = None,
    debug_port: int = _CDP_PORT,
) -> None:
    """레거시 호환 — 기본은 ChromeDebug(9222)."""
    if chrome_user_data is None and profile_dir is None:
        open_chrome_debug(url, debug_port=debug_port)
        return
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\nChrome 설치 후 다시 시도하세요."
        )
    args: list[str] = [str(chrome)]
    if chrome_user_data is not None and chrome_profile_directory:
        args.append(f"--user-data-dir={chrome_user_data.resolve()}")
        args.append(f"--profile-directory={chrome_profile_directory}")
        args.append(f"--remote-debugging-port={debug_port}")
    elif profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={profile_dir.resolve()}")
        args.append(f"--remote-debugging-port={debug_port}")
    else:
        args.append(f"--remote-debugging-port={debug_port}")
        args.append(f"--user-data-dir={_CHROME_DEBUG_USER_DATA.resolve()}")
    args.append("--new-window")
    args.append(url)
    kwargs: dict = {"args": args, "close_fds": True}
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(**kwargs)


def open_browser_for_account(
    url: str,
    *,
    email: str = "",
    fallback_profile_dir: Path | None = None,
    debug_port: int = _CDP_PORT,
    restart_chrome: bool = False,
) -> dict[str, str]:
    """브라우저 열기 — C:\\ChromeDebug + port 9222."""
    del email, fallback_profile_dir, restart_chrome  # 호환용 인자
    return open_chrome_debug(url, debug_port=debug_port)


def open_browser_for_manual_login(url: str, profile_dir: Path | None = None) -> None:
    del profile_dir
    open_chrome_debug(url)


def build_prompt_with_filename(prompt: str, srt_sec: int) -> str:
    """생성 요청에 파일명(SRT_XXX.png)을 포함."""
    name = srt_png_name(srt_sec)
    body = (prompt or "").strip()
    # 이미 파일명이 있으면 중복 삽입 안 함
    if re.search(rf"SRT[_\s-]?{int(srt_sec):03d}\.png", body, re.I):
        return body
    return (
        f"filename: {name}\n"
        f"Save / name this image as {name}.\n\n"
        f"{body}"
    )


def has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def preferred_genspark_url(user_url: str = "") -> str:
    u = (user_url or "").strip()
    return u or GENSPARK_AI_IMAGE_URL


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
    """입력란 클릭 후 키보드로 입력 (fill보다 Google 폼에 안정적)."""
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


async def _click_login_entry(page: Any) -> bool:
    # 단독 "Google" 은 업로드/기타 UI까지 잡혀 파일창이 뜰 수 있어 제외
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
    """계정 선택 화면에서 해당 이메일 클릭."""
    email = (email or "").strip()
    if not email:
        return False
    # data-identifier / 이메일 텍스트
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
    """accounts.google.com (또는 팝업)에서 이메일·비밀번호 자동 입력."""
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        return False

    # 계정 선택 목록이 있으면 클릭
    await _pick_google_account(page, email)

    # 이메일 단계
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

    # 다시 계정 선택일 수 있음
    await _pick_google_account(page, email)
    await page.wait_for_timeout(600)

    # 비밀번호 단계 (최대 ~20초 대기)
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
        # "Use another account" 후 이메일 재입력
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

    # 추가 확인 화면
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
    """Google 계정으로 Genspark 로그인 — 이메일/비밀번호 자동 입력."""
    email = (email or "").strip()
    password = password or ""
    if not email or not password:
        return False

    login_page = page

    # Google 로그인 팝업 또는 리다이렉트 대기
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

        # 같은 탭에서 Google로 이동했는지
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

    # 로그인 페이지에서 자격 증명 입력
    for _ in range(30):
        cur = (login_page.url or "").lower()
        if "accounts.google.com" in cur or await login_page.locator(
            'input[type="email"], input[type="password"], #identifierId'
        ).count():
            break
        await page.wait_for_timeout(400)
        # context의 다른 페이지에 Google 로그인일 수 있음
        if context is not None:
            for p in context.pages:
                if "accounts.google.com" in (p.url or "").lower():
                    login_page = p
                    break

    filled = await _fill_google_credentials(login_page, email, password)
    if not filled:
        # Genspark 자체 이메일/비밀번호 폼
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

    # 팝업이 닫히면 원래 페이지로
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
    """로그인 필요 시 Google/폼에 계정·비밀번호 자동 입력."""
    if not force and await _is_logged_in(page):
        return {"logged_in": True, "attempted": False, "filled": False}
    if not (email or "").strip() or not password:
        return {"logged_in": False, "attempted": False, "filled": False}

    # Sign in이 보이면 무조건 자동 입력 시도
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


async def _page_has_nano_banana(page: Any) -> bool:
    url = (page.url or "").lower()
    if "ai_image" in url or "ai-image" in url:
        try:
            found = await page.evaluate(
                """() => {
                  const t = (document.body && document.body.innerText) || '';
                  return /Nano\\s*Banana\\s*Pro/i.test(t.slice(0, 6000));
                }"""
            )
            if found:
                return True
        except Exception:
            pass
    try:
        found = await page.evaluate(
            """() => {
              const t = (document.body && document.body.innerText) || '';
              return /Nano\\s*Banana\\s*Pro/i.test(t.slice(0, 6000));
            }"""
        )
        return bool(found)
    except Exception:
        return False


async def _is_file_upload_target(loc: Any) -> bool:
    """파일 선택(Windows 파일 찾기)을 여는 요소인지."""
    try:
        return bool(
            await loc.evaluate(
                """el => {
                  if (!el) return true;
                  const t = (el.tagName || '').toLowerCase();
                  const typ = ((el.getAttribute && el.getAttribute('type')) || '').toLowerCase();
                  if (t === 'input' && typ === 'file') return true;
                  if (el.closest && el.closest('input[type="file"]')) return true;
                  if (el.querySelector && el.querySelector('input[type="file"]')) return true;
                  const al = (
                    (el.getAttribute('aria-label') || '') + ' ' +
                    (el.getAttribute('title') || '') + ' ' +
                    (el.textContent || '')
                  ).toLowerCase();
                  if (/upload image|upload file|choose file|browse file|첨부|파일 선택|파일 업로드|이미지 업로드/.test(al))
                    return true;
                  return false;
                }"""
            )
        )
    except Exception:
        return True


async def _click_by_text(page: Any, texts: tuple[str, ...]) -> bool:
    for text in texts:
        # 넓은 div/span 보다 버튼·옵션을 우선 — 파일 input 오클릭 방지
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
                if await _is_file_upload_target(loc):
                    continue
                await loc.click(timeout=4000, force=False)
                await page.wait_for_timeout(600)
                return True
            except Exception:
                continue
    return False


def _attach_filechooser_guard(page: Any) -> None:
    """실수로 뜬 파일 선택 창은 즉시 빈 선택으로 닫는다."""

    async def _on_chooser(chooser: Any) -> None:
        try:
            await chooser.set_files([])
        except Exception:
            pass

    try:
        page.on("filechooser", lambda c: asyncio.create_task(_on_chooser(c)))
    except Exception:
        pass


async def _select_nano_banana_pro(
    page: Any,
    *,
    custom_selector: str = "",
    model_texts: tuple[str, ...] | None = None,
) -> bool:
    texts = model_texts or _NANO_BANANA_PRO_TEXTS
    if await _page_has_nano_banana(page):
        clicked = await _click_by_text(page, texts)
        if clicked or await _page_has_nano_banana(page):
            return True
    if custom_selector.strip():
        loc = page.locator(custom_selector.strip()).first
        try:
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=4000)
                await page.wait_for_timeout(400)
                if await _click_by_text(page, texts):
                    return True
        except Exception:
            pass
    for sel in (
        "button:has-text('Model')",
        "button:has-text('모델')",
        "[aria-label*='Model' i]",
        "[aria-label*='모델' i]",
        "[data-testid*='model' i]",
        "select",
        "[role='combobox']",
        "[role='listbox']",
    ):
        loc = page.locator(sel).first
        try:
            if not await loc.is_visible(timeout=600):
                continue
            await loc.click(timeout=3000)
            await page.wait_for_timeout(400)
            if await _click_by_text(page, texts):
                return True
        except Exception:
            continue
    if await _click_by_text(page, texts):
        return True
    return await _page_has_nano_banana(page)


async def _count_large_images(page: Any) -> int:
    try:
        return int(
            await page.evaluate(
                """() => {
                  let n = 0;
                  for (const img of document.querySelectorAll('img')) {
                    const src = (img.currentSrc || img.src || '').toLowerCase();
                    if (src.includes('www.genspark.ai/api/files')) { n++; continue; }
                    const w = img.naturalWidth || img.width || 0;
                    const h = img.naturalHeight || img.height || 0;
                    if (w >= 256 && h >= 256) n++;
                  }
                  return n;
                }"""
            )
        )
    except Exception:
        return 0


async def _result_ready(page: Any) -> bool:
    """생성 결과 UI(api/files img · 다운로드 버튼 · 큰 미리보기)가 보이는지."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  // Genspark 결과: <img src="https://www.genspark.ai/api/files/s/...">
                  for (const img of document.querySelectorAll('img')) {
                    const src = (img.currentSrc || img.src || '').toLowerCase();
                    if (src.includes('www.genspark.ai/api/files')) return true;
                  }
                  // 다운로드 버튼/아이콘
                  const dl = document.querySelector(
                    'a[download], button[aria-label*="download" i], button[aria-label*="다운로드" i],'
                    + ' a[aria-label*="download" i], [data-testid*="download" i]'
                  );
                  if (dl) return true;
                  // SVG 화살표 다운로드 아이콘 근처 큰 이미지
                  const imgs = Array.from(document.querySelectorAll('img')).filter(img => {
                    const w = img.naturalWidth || img.width || 0;
                    const h = img.naturalHeight || img.height || 0;
                    return w >= 400 && h >= 300;
                  });
                  if (imgs.length === 0) return false;
                  // "이미지 생성" 결과 카드가 있고 큰 이미지가 있으면 완료로 간주
                  const t = (document.body && document.body.innerText) || '';
                  if (/이미지\\s*생성/.test(t) && imgs.length >= 1) return true;
                  // 우측 프리뷰 패널에 큰 이미지만 있어도 완료
                  return imgs.some(img => (img.naturalWidth || 0) >= 512);
                }"""
            )
        )
    except Exception:
        return False


async def _is_generating(page: Any) -> bool:
    """실제 생성 진행 중인지 — 결과 UI가 있으면 false (오탐 방지)."""
    try:
        if await _result_ready(page):
            return False
        return bool(
            await page.evaluate(
                """() => {
                  const t = ((document.body && document.body.innerText) || '')
                    .toLowerCase().slice(0, 12000);
                  // 진행 문구만 (카드 제목 '이미지 생성'은 제외)
                  if (/generating\\.?\\.|generation in progress|생성\\s*중|생성중|이미지를 생성|생성하고 있/.test(t))
                    return true;
                  const prog = document.querySelector(
                    '[role="progressbar"], [aria-busy="true"]'
                  );
                  return !!prog;
                }"""
            )
        )
    except Exception:
        return False


async def _largest_image_src(page: Any) -> str:
    try:
        return str(
            await page.evaluate(
                """() => {
                  // www.genspark.ai/api/files 우선 (마지막 결과)
                  let fileUrl = '';
                  for (const img of document.querySelectorAll('img')) {
                    const src = img.currentSrc || img.src || '';
                    if (src.toLowerCase().includes('www.genspark.ai/api/files'))
                      fileUrl = src;
                  }
                  if (fileUrl) return fileUrl;
                  let best = '', area = 0;
                  for (const img of document.querySelectorAll('img')) {
                    const w = img.naturalWidth || img.width || 0;
                    const h = img.naturalHeight || img.height || 0;
                    if (w * h > area && w >= 256) {
                      area = w * h;
                      best = img.currentSrc || img.src || '';
                    }
                  }
                  return best;
                }"""
            )
            or ""
        )
    except Exception:
        return ""


_REGEN_PREFIX = (
    "이미지 다시 생성. Regenerate the image. Please try again.\n\n"
)


async def _page_shows_failure(page: Any) -> bool:
    """Genspark 결과에 Failure / 생성 실패 문구가 보이는지."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const t = ((document.body && document.body.innerText) || '')
                    .slice(0, 24000);
                  if (/\\bFailure\\b/i.test(t)) return true;
                  if (/생성\\s*실패|generation\\s*failed|failed\\s*to\\s*generate/i.test(t))
                    return true;
                  if (/error\\s*occurred|오류가\\s*발생/i.test(t)
                      && /image|이미지|generate|생성/i.test(t))
                    return true;
                  return false;
                }"""
            )
        )
    except Exception:
        return False


async def _wait_generation_done(
    page: Any,
    *,
    baseline_count: int,
    prev_src: str = "",
    timeout_sec: int = 180,
) -> bool:
    """새 이미지(src 변경·개수 증가) 또는 결과 다운로드 UI가 안정되면 완료."""
    deadline = asyncio.get_event_loop().time() + max(30, int(timeout_sec))
    stable = 0
    saw_change = False
    # 제출 직후 잠깐은 이전 결과 UI를 무시
    await page.wait_for_timeout(1500)
    while asyncio.get_event_loop().time() < deadline:
        if await _page_shows_failure(page):
            return False
        count = await _count_large_images(page)
        src = await _largest_image_src(page)
        busy = await _is_generating(page)
        changed = (count > baseline_count) or (
            bool(src) and bool(prev_src) and src != prev_src
        ) or (bool(src) and not prev_src and count >= 1)
        if changed:
            saw_change = True
        ready = await _result_ready(page)
        # 새 결과가 반영되고 진행 중이 아니면 완료
        if saw_change and ready and not busy:
            if await _page_shows_failure(page):
                return False
            stable += 1
            if stable >= 2:
                await page.wait_for_timeout(400)
                return True
        elif saw_change and not busy and count > 0:
            if await _page_shows_failure(page):
                return False
            stable += 1
            if stable >= 3:
                return True
        else:
            stable = 0
        await page.wait_for_timeout(1000)
    src = await _largest_image_src(page)
    if await _result_ready(page) and (
        (await _count_large_images(page)) > baseline_count
        or (src and src != prev_src)
    ):
        return True
    return (await _count_large_images(page)) > baseline_count


async def _genspark_file_src(page: Any) -> str:
    """마지막 ``www.genspark.ai/api/files…`` img src만."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  let last = '';
                  for (const img of document.querySelectorAll('img')) {
                    const src = img.currentSrc || img.src
                      || img.getAttribute('data-src') || '';
                    if (src.toLowerCase().includes('www.genspark.ai/api/files'))
                      last = src;
                  }
                  return last;
                }"""
            )
            or ""
        )
    except Exception:
        return ""


async def _save_latest_image_to(
    page: Any,
    dest: Path,
    *,
    prefer_button: bool = False,
) -> Path:
    """``www.genspark.ai/api/files`` img만 다운로드 → dest(SRT_XXX.png)."""
    del prefer_button  # 버튼/기타 이미지 폴백 금지
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    from scene_image.download import download_url

    file_src = (await _genspark_file_src(page) or "").strip()
    if not file_src or not is_genspark_file_url(file_src):
        raise RuntimeError(
            "www.genspark.ai/api/files 이미지가 없습니다. "
            "생성이 끝난 뒤 다시 시도하세요."
        )

    try:
        download_url(file_src, dest)
        if dest.is_file() and dest.stat().st_size >= 512:
            return dest
    except Exception:
        pass

    # 세션 쿠키 필요 시 페이지 fetch (같은 URL만)
    b64 = await page.evaluate(
        """async (u) => {
          const r = await fetch(u, { credentials: 'include' });
          if (!r.ok) return '';
          const buf = await r.arrayBuffer();
          const bytes = new Uint8Array(buf);
          let s = '';
          for (let i = 0; i < bytes.length; i++)
            s += String.fromCharCode(bytes[i]);
          return btoa(s);
        }""",
        file_src,
    )
    if not b64:
        raise RuntimeError(f"api/files 다운로드 실패: {file_src[:120]}")
    dest.write_bytes(base64.b64decode(b64))
    if not dest.is_file() or dest.stat().st_size < 512:
        raise RuntimeError(f"다운로드 검증 실패: {dest.name}")
    return dest


async def _save_storage_state(context: Any, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(path.resolve()))
    except Exception:
        pass


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
                if await _is_file_upload_target(item):
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
        "button:has-text('Generate')",
        "button:has-text('생성')",
        "button:has-text('Send')",
        "button:has-text('전송')",
        "button:has-text('Submit')",
        "button:has-text('실행')",
        "button[type='submit']:visible",
        "[aria-label*='Send' i]",
        "[aria-label*='Generate' i]",
        "[aria-label*='전송' i]",
        "[aria-label*='생성' i]",
    ):
        btn = page.locator(sel).first
        try:
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=5000)
                return
        except Exception:
            continue
    await page.keyboard.press("Enter")


async def _collect_images(page: Any) -> list[tuple[int | None, str]]:
    try:
        await page.evaluate(
            """() => {
              window.scrollTo(0, 0);
              const h = document.body && document.body.scrollHeight || 0;
              window.scrollTo(0, Math.max(0, h - 400));
            }"""
        )
        await page.wait_for_timeout(800)
    except Exception:
        pass
    raw = await page.evaluate(
        """() => {
          const out = [];
          const seen = new Set();
          const skipParts = [
            'bat.bing.com', 'bing.com/action', 'google-analytics.com',
            'googletagmanager.com', 'doubleclick.net', 'clarity.ms', 'hotjar.com'
          ];
          const goodHostParts = [
            'genspark', 'cloudinary', 'amazonaws.com', 'googleusercontent.com',
            'openai.com', 'oaidalle', 'blob.core.windows.net'
          ];
          const isSkip = (url) => {
            if (!url) return true;
            const u = url.toLowerCase();
            if (u.startsWith('data:')) return true;
            if (u.includes('/action/0?') && u.includes('bing')) return true;
            return skipParts.some(p => u.includes(p));
          };
          const looksImage = (url) => {
            if (!url) return false;
            if (url.startsWith('blob:')) return true;
            if (url.toLowerCase().includes('www.genspark.ai/api/files')) return true;
            if (/\\.(png|jpe?g|webp|gif|avif)(\\?|$|#)/i.test(url)) return true;
            try {
              const host = new URL(url).hostname.toLowerCase();
              return goodHostParts.some(p => host.includes(p));
            } catch (e) { return false; }
          };
          const push = (url, label, w, h) => {
            if (!url || seen.has(url) || isSkip(url)) return;
            const isFile = url.toLowerCase().includes('www.genspark.ai/api/files');
            if (!isFile && !looksImage(url) && (w < 256 || h < 256)) return;
            if (!isFile && !url.startsWith('blob:') && (!w || !h) && !looksImage(url)) return;
            seen.add(url);
            out.push({url, label: label || '', w, h});
          };
          for (const img of document.querySelectorAll('img')) {
            const w = img.naturalWidth || img.width || 0;
            const h = img.naturalHeight || img.height || 0;
            const src = img.currentSrc || img.src || '';
            let label = '';
            const near = (img.closest('figure,article,div,li,section') || img.parentElement);
            if (near) label = (near.innerText || '').slice(0, 800);
            push(src, (label + ' ' + (img.alt || '')).trim(), w, h);
            const ds = img.getAttribute('data-src') || img.getAttribute('data-original') || '';
            if (ds) push(ds, label, w, h);
          }
          for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href || '';
            if (!looksImage(href) && !/download/i.test(href)) continue;
            push(href, ((a.innerText || '') + ' ' + (a.getAttribute('download') || '')).trim(), 0, 0);
          }
          return out;
        }"""
    )
    items: list[tuple[int | None, str]] = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        label = str(row.get("label") or "")
        w = int(row.get("w") or 0)
        h = int(row.get("h") or 0)
        if not url or is_tracking_url(url):
            continue
        if not url.startswith("blob:") and not is_collectable_image_url(
            url, width=w, height=h
        ):
            continue
        sec = None
        m = _SRT_LABEL_RE.search(label) or _SRT_LABEL_RE.search(url)
        if m:
            sec = int(m.group(1))
        items.append((sec, url))
    return items


async def _launch_context(playwright: Any, profile_dir: Path) -> Any:
    # 1) 이미 열린 Chrome(CDP)에 연결
    for _ in range(24):
        for port in _CDP_PORTS:
            try:
                browser = await playwright.chromium.connect_over_cdp(
                    f"http://127.0.0.1:{port}"
                )
                if browser.contexts:
                    return browser.contexts[0]
            except Exception:
                continue
        await asyncio.sleep(0.5)

    # 2) 전용 프로필 + storageState (세션 유지)
    profile_dir.mkdir(parents=True, exist_ok=True)
    state = storage_state_path(profile_dir)
    kwargs: dict[str, Any] = {
        "user_data_dir": str(profile_dir.resolve()),
        "channel": "chrome",
        "headless": False,
        "locale": "ko-KR",
        "accept_downloads": True,
        "args": ["--disable-blink-features=AutomationControlled"],
    }
    # persistent context는 storage_state 인자를 지원하지 않는 버전도 있어
    # 별도 브라우저 launch + new_context 폴백
    try:
        return await playwright.chromium.launch_persistent_context(**kwargs)
    except Exception:
        browser = await playwright.chromium.launch(
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        if state.is_file():
            return await browser.new_context(
                storage_state=str(state.resolve()),
                locale="ko-KR",
                accept_downloads=True,
            )
        return await browser.new_context(locale="ko-KR", accept_downloads=True)


class GensparkSceneSession:
    """Playwright 세션 — Nano banana pro · 씬 프롬프트 전송·이미지 수집."""

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

    def open_and_select_model(
        self,
        *,
        url: str,
        model_selector: str = "",
        email: str = "",
        password: str = "",
        model_texts: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, bool]:
        return self._call(
            "open_model",
            {
                "url": url,
                "model_selector": model_selector,
                "email": email,
                "password": password,
                "model_texts": list(model_texts or []),
            },
            timeout=240.0,
        )

    def submit_prompt(
        self,
        *,
        url: str,
        prompt: str,
        model_selector: str = "",
        try_model_select: bool = True,
        model_texts: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, bool]:
        return self._call(
            "submit",
            {
                "url": url,
                "prompt": prompt,
                "model_selector": model_selector,
                "try_model": try_model_select,
                "model_texts": list(model_texts or []),
            },
            timeout=240.0,
        )

    def collect_images(self, *, wait_ms: int = 3000) -> list[tuple[int | None, str]]:
        return self._call("collect", wait_ms, timeout=120.0)

    def download_via_page(
        self,
        items: list[tuple[int | None, str]],
        png_dir: Path,
        *,
        fallback_secs: list[int] | None = None,
        default_start_sec: int | None = None,
    ) -> list[str]:
        return self._call(
            "download",
            {
                "items": items,
                "png_dir": str(png_dir),
                "fallback_secs": list(fallback_secs or []),
                "default_start_sec": default_start_sec,
            },
            timeout=300.0,
        )

    def run_scene_with_retry(
        self,
        *,
        url: str,
        prompt: str,
        png_dir: Path,
        srt_sec: int,
        model_selector: str = "",
        model_texts: tuple[str, ...] | list[str] | None = None,
        try_model_select: bool = False,
        retry_count: int = 3,
        retry_wait_sec: int = 30,
        generate_timeout_sec: int = 180,
    ) -> dict[str, Any]:
        """프롬프트 전송 → 생성 완료 대기 → 다운로드. 실패 시 재시도."""
        return self._call(
            "run_scene",
            {
                "url": url,
                "prompt": prompt,
                "png_dir": str(png_dir),
                "srt_sec": int(srt_sec),
                "model_selector": model_selector,
                "model_texts": list(model_texts or []),
                "try_model": try_model_select,
                "retry_count": int(retry_count),
                "retry_wait_sec": int(retry_wait_sec),
                "generate_timeout_sec": int(generate_timeout_sec),
            },
            timeout=float(
                max(300, (retry_count + 1) * (generate_timeout_sec + retry_wait_sec + 60))
            ),
        )

    async def _async_worker(self) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await _launch_context(pw, self._profile_dir)
            page = context.pages[0] if context.pages else await context.new_page()
            _attach_filechooser_guard(page)
            for p in list(context.pages or []):
                _attach_filechooser_guard(p)
            try:
                context.on(
                    "page",
                    lambda p: _attach_filechooser_guard(p),
                )
            except Exception:
                pass
            model_ready = False

            while True:
                try:
                    op, arg, resp_q = self._cmd_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    continue
                try:
                    if op == "open_model":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        email = str(data.get("email") or "")
                        password = str(data.get("password") or "")
                        mtexts = tuple(data.get("model_texts") or []) or None
                        await page.goto(
                            url, wait_until="domcontentloaded", timeout=90_000
                        )
                        await page.wait_for_timeout(1800)
                        # storageState/쿠키로 로그인 유지 — 만료 시에만 재로그인
                        login_info = await _ensure_login(
                            page,
                            email,
                            password,
                            context=context,
                            force=False,
                        )
                        if "genspark.ai" not in (page.url or "").lower() or (
                            "ai_image" not in (page.url or "").lower()
                            and "ai-image" not in (page.url or "").lower()
                        ):
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            await page.wait_for_timeout(1500)
                        if email and password and not await _is_logged_in(page):
                            login_info = await _ensure_login(
                                page,
                                email,
                                password,
                                context=context,
                                force=True,
                            )
                            if login_info.get("logged_in"):
                                await _save_storage_state(
                                    context,
                                    storage_state_path(self._profile_dir),
                                )
                            if "ai_image" not in (page.url or "").lower() and (
                                "ai-image" not in (page.url or "").lower()
                            ):
                                await page.goto(
                                    url,
                                    wait_until="domcontentloaded",
                                    timeout=90_000,
                                )
                                await page.wait_for_timeout(1200)
                        elif login_info.get("logged_in"):
                            await _save_storage_state(
                                context,
                                storage_state_path(self._profile_dir),
                            )
                        model_auto = await _select_nano_banana_pro(
                            page,
                            custom_selector=str(data.get("model_selector") or ""),
                            model_texts=mtexts,
                        )
                        model_ready = model_auto
                        resp_q.put(
                            (
                                True,
                                {
                                    "model_auto": bool(model_auto),
                                    "logged_in": bool(
                                        login_info.get("logged_in")
                                    ),
                                    "login_attempted": bool(
                                        login_info.get("attempted")
                                    ),
                                    "login_filled": bool(
                                        login_info.get("filled")
                                    ),
                                },
                                None,
                            )
                        )
                    elif op == "submit":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        mtexts = tuple(data.get("model_texts") or []) or None
                        cur = (page.url or "").lower()
                        need_nav = (
                            "genspark.ai" not in cur
                            or ("ai_image" not in cur and "ai-image" not in cur)
                        )
                        if need_nav or url.rstrip("/") not in (page.url or ""):
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            await page.wait_for_timeout(1500)
                            model_ready = False
                        model_auto = model_ready
                        if data.get("try_model") and not model_ready:
                            model_auto = await _select_nano_banana_pro(
                                page,
                                custom_selector=str(
                                    data.get("model_selector") or ""
                                ),
                                model_texts=mtexts,
                            )
                            model_ready = model_auto
                        prompt = (data.get("prompt") or "").strip()
                        if not prompt:
                            raise RuntimeError("프롬프트가 비어 있습니다.")
                        if not await _fill_first_editable(page, prompt):
                            raise RuntimeError(
                                "명령어 입력란을 찾지 못했습니다. "
                                "로그인·페이지 로드 후 다시 시도하세요."
                            )
                        await _submit(page)
                        await page.wait_for_timeout(1200)
                        resp_q.put((True, {"model_auto": bool(model_auto)}, None))
                    elif op == "run_scene":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        prompt_raw = (data.get("prompt") or "").strip()
                        png_dir = Path(data.get("png_dir") or ".")
                        srt_sec = int(data.get("srt_sec") or 0)
                        prompt = build_prompt_with_filename(prompt_raw, srt_sec)
                        mtexts = tuple(data.get("model_texts") or []) or None
                        retry_count = max(1, int(data.get("retry_count") or 3))
                        retry_wait = max(5, int(data.get("retry_wait_sec") or 30))
                        gen_timeout = max(30, int(data.get("generate_timeout_sec") or 180))
                        if not prompt_raw:
                            raise RuntimeError("프롬프트가 비어 있습니다.")
                        png_dir.mkdir(parents=True, exist_ok=True)
                        # PNG 폴더에 이미 있으면 재생성하지 않음
                        if png_already_exists(png_dir, srt_sec):
                            existing = png_dir / srt_png_name(srt_sec)
                            resp_q.put(
                                (
                                    True,
                                    {
                                        "ok": True,
                                        "skipped": True,
                                        "attempt": 0,
                                        "saved": [str(existing.resolve())],
                                    },
                                    None,
                                )
                            )
                            continue
                        last_err = ""
                        saved_paths: list[str] = []
                        use_regen_msg = False
                        for attempt in range(1, retry_count + 1):
                            try:
                                cur = (page.url or "").lower()
                                if (
                                    "genspark.ai" not in cur
                                    or (
                                        "ai_image" not in cur
                                        and "ai-image" not in cur
                                    )
                                ):
                                    await page.goto(
                                        url,
                                        wait_until="domcontentloaded",
                                        timeout=90_000,
                                    )
                                    await page.wait_for_timeout(1000)
                                if data.get("try_model") and not model_ready:
                                    model_ready = await _select_nano_banana_pro(
                                        page,
                                        custom_selector=str(
                                            data.get("model_selector") or ""
                                        ),
                                        model_texts=mtexts,
                                    )
                                # Failure 보이면 / 재시도 시 「이미지 다시 생성」메시지 + 원 프롬프트
                                if use_regen_msg or await _page_shows_failure(page):
                                    use_regen_msg = True
                                    send_prompt = _REGEN_PREFIX + prompt
                                else:
                                    send_prompt = prompt
                                baseline = await _count_large_images(page)
                                prev_src = await _largest_image_src(page)
                                if not await _fill_first_editable(page, send_prompt):
                                    raise RuntimeError("명령어 입력란을 찾지 못했습니다.")
                                await _submit(page)
                                ok = await _wait_generation_done(
                                    page,
                                    baseline_count=baseline,
                                    prev_src=prev_src,
                                    timeout_sec=gen_timeout,
                                )
                                if await _page_shows_failure(page):
                                    use_regen_msg = True
                                    raise RuntimeError(
                                        "Failure 메시지 감지 — 다시 생성 메시지로 재시도"
                                    )
                                if not ok:
                                    if not await _result_ready(page):
                                        use_regen_msg = True
                                        raise RuntimeError(
                                            f"생성 완료 대기 시간 초과 ({gen_timeout}s)"
                                        )
                                dest = png_dir / srt_png_name(srt_sec)
                                saved = await _save_latest_image_to(
                                    page, dest, prefer_button=False
                                )
                                saved_paths = [str(saved)]
                                resp_q.put(
                                    (
                                        True,
                                        {
                                            "ok": True,
                                            "attempt": attempt,
                                            "regenerated": use_regen_msg,
                                            "saved": saved_paths,
                                        },
                                        None,
                                    )
                                )
                                break
                            except Exception as ex:
                                last_err = str(ex)
                                use_regen_msg = True
                                if attempt >= retry_count:
                                    resp_q.put(
                                        (
                                            False,
                                            None,
                                            RuntimeError(
                                                f"{retry_count}회 실패: {last_err}"
                                            ),
                                        )
                                    )
                                    break
                                await page.wait_for_timeout(retry_wait * 1000)
                        else:
                            if not saved_paths:
                                resp_q.put(
                                    (
                                        False,
                                        None,
                                        RuntimeError(last_err or "씬 생성 실패"),
                                    )
                                )
                    elif op == "collect":
                        wait_ms = int(arg or 2000)
                        await page.wait_for_timeout(max(0, wait_ms))
                        items = await _collect_images(page)
                        resp_q.put((True, items, None))
                    elif op == "download":
                        data = arg or {}
                        png_dir = Path(data.get("png_dir") or ".")
                        png_dir.mkdir(parents=True, exist_ok=True)
                        from scene_image.download import assign_srt_secs, download_url

                        resolved = assign_srt_secs(
                            list(data.get("items") or []),
                            fallback_secs=data.get("fallback_secs"),
                            default_start_sec=data.get("default_start_sec"),
                        )
                        saved: list[str] = []
                        for n, url in resolved:
                            dest = png_dir / srt_png_name(n)
                            if url.startswith("blob:"):
                                b64 = await page.evaluate(
                                    """async (u) => {
                                      const r = await fetch(u);
                                      const buf = await r.arrayBuffer();
                                      const bytes = new Uint8Array(buf);
                                      let s = '';
                                      for (let i = 0; i < bytes.length; i++)
                                        s += String.fromCharCode(bytes[i]);
                                      return btoa(s);
                                    }""",
                                    url,
                                )
                                dest.write_bytes(base64.b64decode(b64))
                            else:
                                download_url(url, dest)
                            saved.append(str(dest))
                        resp_q.put((True, saved, None))
                    elif op == "stop":
                        resp_q.put((True, None, None))
                        break
                    else:
                        resp_q.put(
                            (False, None, RuntimeError(f"알 수 없는 명령: {op}"))
                        )
                except Exception as ex:
                    resp_q.put((False, None, ex))


_session: GensparkSceneSession | None = None
_session_lock = threading.Lock()


def reset_image_session() -> None:
    global _session
    with _session_lock:
        if _session is not None:
            try:
                _session._call("stop", timeout=10.0)
            except Exception:
                pass
            _session = None


def get_image_session(profile_dir: Path) -> GensparkSceneSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = GensparkSceneSession(profile_dir)
        return _session
