# -*- coding: utf-8 -*-
"""Genspark AI Image — Nano banana pro 선택·프롬프트 전송·이미지 수집 (Playwright)."""

from __future__ import annotations

import asyncio
import base64
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from scene_image.paths import GENSPARK_AI_IMAGE_URL
from scene_image.scene_parse import png_already_exists, srt_png_name
from scene_image.url_filter import (
    is_collectable_image_url,
    is_genspark_file_url,
    is_tracking_url,
    looks_like_image_url,
    normalize_genspark_file_url,
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
# 모듈 전용 ChromeDebug (다른 Genspark 모듈과 포트·프로필 분리)
# chrome --remote-debugging-port=9242 --user-data-dir=C:\ChromeDebug_2_5
_CDP_PORT = 9242
_CDP_PORTS = (9242,)
_CHROME_DEBUG_USER_DATA = Path(r"C:\ChromeDebug_2_5")
_GENSPARK_FILE_RE = re.compile(
    r"https?://(?:www\.)?genspark\.ai/api/files/[^\s\"'<>]+",
    re.IGNORECASE,
)
_SRT_LABEL_RE = re.compile(r"SRT[_\s-]?(\d{1,6})", re.IGNORECASE)
# True 이면 filechooser 가드가 첨부를 가로채지 않음
_FC_ALLOW: dict[str, bool] = {"v": False}
# 탭/창 디버그 → image.log (png 형제 log/)
_TAB_LOG_PNG: dict[str, Path | None] = {"dir": None}


def set_tab_log_png_dir(png_dir: Path | None) -> None:
    """탭·창 이벤트를 image.log 에 남길 png 폴더 지정."""
    _TAB_LOG_PNG["dir"] = Path(png_dir) if png_dir else None


def _tab_log(message: str) -> None:
    d = _TAB_LOG_PNG.get("dir")
    if d is None:
        return
    try:
        from scene_image.image_log import append_image_log

        append_image_log(d, message)
    except Exception:
        pass


def _timing_sec(t0: float) -> float:
    return round(max(0.0, time.perf_counter() - t0), 1)


def _timing_log(label: str, t0: float, *, extra: str = "") -> float:
    """단계 소요(초)를 image.log 에 남기고 새 시각을 반환."""
    sec = _timing_sec(t0)
    msg = f"⏱ {label} {sec}s"
    if extra:
        msg = f"{msg} · {extra}"
    _tab_log(msg)
    return time.perf_counter()


async def _tab_snapshot(context: Any, keep: Any | None = None) -> str:
    """현재 탭 목록 한 줄 요약."""
    lines: list[str] = []
    try:
        pages = list(getattr(context, "pages", []) or [])
    except Exception:
        return "(tabs: ?)"
    for i, p in enumerate(pages):
        try:
            closed = p.is_closed()
            u = "" if closed else (p.url or "")[:120]
            mark = "*" if keep is not None and p is keep else " "
            lines.append(f"{mark}[{i}]{'CLOSED' if closed else u}")
        except Exception as ex:
            lines.append(f" [{i}]err:{ex}")
    return f"tabs={len(pages)} " + " | ".join(lines)


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


def close_chrome_debug(*, user_data_dir: Path | None = None) -> None:
    """이 모듈 ChromeDebug(CDP)만 종료 — 다른 모듈 포트·프로필은 건드리지 않음."""
    reset_image_session()
    data = str(Path(user_data_dir or _CHROME_DEBUG_USER_DATA).resolve())
    data_esc = data.replace("'", "''")
    if sys.platform == "win32":
        # 이 모듈 user-data-dir(또는 전용 포트+프로필) chrome.exe 만 종료
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
    time.sleep(0.8)


def clear_chrome_session_restore(user_data_dir: Path | None = None) -> None:
    """이전 창·탭 복원을 막아 「브라우저 열기」 때 탭 1개만 뜨게 한다."""
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
    for sub in default.glob("Sessions/*"):
        try:
            if sub.is_file():
                sub.unlink()
            elif sub.is_dir():
                shutil.rmtree(sub, ignore_errors=True)
        except OSError:
            pass


def image_profile_dir(base_dir: Path) -> Path:
    """레거시 전용 프로필 (계정 Chrome 프로필을 쓸 때는 사용하지 않음)."""
    return base_dir / _PROFILE_DIRNAME


def wait_cdp_ready(*, debug_port: int = _CDP_PORT, timeout_sec: float = 45.0) -> bool:
    """ChromeDebug remote debugging 포트가 응답할 때까지 대기."""
    import urllib.error
    import urllib.request

    url = f"http://127.0.0.1:{int(debug_port)}/json/version"
    deadline = time.time() + max(5.0, float(timeout_sec))
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as resp:
                if getattr(resp, "status", 200) == 200:
                    time.sleep(0.6)
                    return True
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(0.4)
    return False


def open_chrome_debug(
    url: str = GENSPARK_AI_IMAGE_URL,
    *,
    debug_port: int = _CDP_PORT,
    user_data_dir: Path | None = None,
    restart: bool = False,
) -> dict[str, str]:
    """고정 디버그 Chrome 실행.

    ``chrome.exe --remote-debugging-port=9242 --user-data-dir=C:\\ChromeDebug_2_5``
    ``restart=True`` 이면 기존 ChromeDebug 프로세스를 종료한 뒤 다시 연다.
    Playwright 연결 전에는 about:blank 만 열고, 페이지 이동은 세션이 담당한다.
    """
    if restart:
        close_chrome_debug(user_data_dir=user_data_dir)
        clear_chrome_session_restore(user_data_dir)
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\nChrome 설치 후 다시 시도하세요."
        )
    data_dir = Path(user_data_dir or _CHROME_DEBUG_USER_DATA)
    data_dir.mkdir(parents=True, exist_ok=True)
    reset_image_session()
    # URL은 Playwright가 연 뒤에 이동 — 창만 뜨고 자동화가 안 붙는 착시 방지
    del url  # 호환 인자 (시작 URL은 세션 open_model 에서 처리)
    args: list[str] = [
        str(chrome),
        f"--remote-debugging-port={int(debug_port)}",
        f"--user-data-dir={data_dir.resolve()}",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--new-window",
        "about:blank",
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
    }


def open_genspark_in_chrome(
    url: str = GENSPARK_AI_IMAGE_URL,
    *,
    profile_dir: Path | None = None,
    chrome_user_data: Path | None = None,
    chrome_profile_directory: str | None = None,
    debug_port: int = _CDP_PORT,
) -> None:
    """레거시 호환 — 기본은 ChromeDebug_2_5(9242)."""
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
    """브라우저 열기 — C:\\ChromeDebug_2_5 + port 9242."""
    del email, fallback_profile_dir  # 호환용 인자
    return open_chrome_debug(
        url, debug_port=debug_port, restart=restart_chrome
    )


def open_browser_for_manual_login(url: str, profile_dir: Path | None = None) -> None:
    del profile_dir
    open_chrome_debug(url)


def _is_followup_command(text: str) -> bool:
    """이어쓰기 칸에 넣는 짧은 씬 명령인지 (초기 붙여넣기 대용량과 구분)."""
    t = (text or "").strip()
    if not t:
        return False
    if t.startswith("===== CHARACTER LOOK"):
        return True
    if "CHARACTER LOOK" in t and "Chinese wuxia manhua" in t:
        return True
    return len(t) < 500 and t.upper().startswith("SRT_")


def build_generate_command(
    srt_sec: int,
    *,
    scene_prompt: str | None = None,
    srt_dialogue: str | None = None,
    interval_sec: int = 20,
    character_look: str | None = None,
    png_dir: Path | str | None = None,
    state_tracker: Any | None = None,
) -> str:
    """입력창 명령: 구간 대사(+실장면 프롬프트) + CHARACTER LOOK + 생성 지시.

    Face Identity·State Layer 를 매 장 재삽입해 인물 일관성을 유지한다.
    """
    from scene_image.character_consistency import (
        CharacterStateTracker,
        _STYLE_TAIL,
        build_character_look_for_scene,
    )
    from scene_image.scene_parse import is_real_scene_prompt

    n = max(0, int(srt_sec))
    label = f"SRT_{n:03d}"
    gap = max(1, int(interval_sec))
    dialogue = (srt_dialogue or "").strip()
    real = scene_prompt if is_real_scene_prompt(scene_prompt) else None

    look = (character_look or "").strip()
    tr = state_tracker
    if not look:
        look, tr = build_character_look_for_scene(
            n,
            dialogue=dialogue,
            scene_prompt=real or scene_prompt,
            png_dir=png_dir,
            tracker=tr if isinstance(tr, CharacterStateTracker) else None,
        )
    elif isinstance(tr, CharacterStateTracker) and png_dir:
        tr.save(png_dir)

    parts: list[str] = []
    if look:
        parts.append(f"===== CHARACTER LOOK ({label}) =====\n{look}")
    if real:
        parts.append(f"===== SCENE PROMPT ({label}) =====\n{real}")
    if dialogue:
        parts.append(f"===== SRT [{n}, {n + gap}) =====\n{dialogue}")
    if not real:
        parts.append(f"===== STYLE =====\n{_STYLE_TAIL}")
    tr_obj = tr if isinstance(tr, CharacterStateTracker) else None
    instr = (
        tr_obj.build_scene_instruction(label)
        if tr_obj
        else (
            f"{label} Chinese wuxia manhua illustration — generate now. "
            f"Keep character face and outfit consistent with Character Bible. "
            f"No text or speech bubbles. "
            f"After image appears: 「{label} 이미지가 성공적으로 생성되었습니다.」"
        )
    )
    parts.append(instr)
    return "\n\n".join(parts)


def build_generate_command_from_sources(
    srt_sec: int,
    *,
    scene_prompt: str | None = None,
    srt_path: str | Path | None = None,
    interval_sec: int = 20,
    prompt_path: str | Path | None = None,
    png_dir: Path | str | None = None,
    state_tracker: Any | None = None,
) -> str:
    """SRT 파일·장면 프롬프트에서 매 장 전송 문구를 만든다."""
    del prompt_path  # 향후 NOVEL PACK 파싱용
    from scene_image.scene_parse import is_real_scene_prompt, srt_dialogue_for_window

    dialogue = srt_dialogue_for_window(srt_path, srt_sec, interval_sec)
    real = scene_prompt if is_real_scene_prompt(scene_prompt) else None
    return build_generate_command(
        srt_sec,
        scene_prompt=real,
        srt_dialogue=dialogue or None,
        interval_sec=interval_sec,
        png_dir=png_dir,
        state_tracker=state_tracker,
    )


def build_prompt_with_filename(prompt: str, srt_sec: int) -> str:
    """생성 요청 명령어 — 실장면 프롬프트가 있으면 함께 넣음."""
    return build_generate_command(srt_sec, scene_prompt=prompt)


def has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def preferred_genspark_url(user_url: str = "") -> str:
    u = (user_url or "").strip()
    return u or GENSPARK_AI_IMAGE_URL


def _maybe_set_work_url(current: str, page_url: str) -> str:
    """더 좋은 대화 URL이면 갱신."""
    pu = (page_url or "").strip()
    if not pu:
        return current
    if _score_ai_image_url(pu) >= 35 and _score_ai_image_url(pu) >= _score_ai_image_url(
        current or ""
    ):
        return pu
    return current or pu


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


async def _toolbar_model_label(page: Any) -> str:
    """하단 툴바의 현재 모델 칩 텍스트 (예: Nano Banana 2 Flash)."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  const vh = window.innerHeight || 800;
                  const hits = [];
                  const els = document.querySelectorAll(
                    'button, [role="button"], [role="combobox"], [aria-haspopup], div, span'
                  );
                  for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.bottom < vh * 0.58 || r.top > vh - 6) continue;
                    if (r.width < 24 || r.height < 12 || r.height > 56) continue;
                    const t = (el.innerText || el.textContent || '')
                      .replace(/\\s+/g, ' ').trim();
                    if (!t || t.length > 70) continue;
                    if (!/banana|🍌|flash/i.test(t)) continue;
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


def _label_is_nano_banana_pro(text: str) -> bool:
    t = (text or "").replace("\n", " ")
    if re.search(r"flash", t, re.I):
        return False
    return bool(re.search(r"nano\s*banana\s*(2\s*)?pro|banana\s*pro", t, re.I))


async def _page_has_nano_banana(page: Any) -> bool:
    """툴바에 Nano Banana Pro 가 선택돼 있는지 (Flash 제외)."""
    return _label_is_nano_banana_pro(await _toolbar_model_label(page))


async def _open_model_picker(page: Any) -> str:
    """하단 모델 칩(Flash/Banana)을 눌러 목록을 연다. 클릭한 라벨 반환."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  const vh = window.innerHeight || 800;
                  const hits = [];
                  const els = document.querySelectorAll(
                    'button, [role="button"], [role="combobox"], [aria-haspopup], div, span'
                  );
                  for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.bottom < vh * 0.58 || r.top > vh - 6) continue;
                    if (r.width < 24 || r.height < 12 || r.height > 56) continue;
                    const t = (el.innerText || el.textContent || '')
                      .replace(/\\s+/g, ' ').trim();
                    if (!t || t.length > 70) continue;
                    if (!/nano\\s*banana|🍌|flash/i.test(t)) continue;
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


async def _click_nano_banana_pro_option(page: Any) -> str:
    """팝업 목록에서만 Flash 가 아닌 Pro 항목을 클릭 (본문 텍스트 클릭 금지)."""
    try:
        return str(
            await page.evaluate(
                """() => {
                  const roots = Array.from(document.querySelectorAll(
                    '[role="listbox"], [role="menu"], [role="dialog"], '
                    + '[data-radix-popper-content-wrapper], [class*="popover" i], '
                    + '[class*="dropdown" i], [class*="Menu" i]'
                  ));
                  const scope = roots.length ? roots : [];
                  const nodes = [];
                  for (const root of scope) {
                    nodes.push(...root.querySelectorAll(
                      '[role="option"], [role="menuitem"], button, li, div, span'
                    ));
                  }
                  const hits = [];
                  for (const el of nodes) {
                    const t = (el.innerText || el.textContent || '')
                      .replace(/\\s+/g, ' ').trim();
                    if (!t || t.length > 64) continue;
                    if (/flash/i.test(t)) continue;
                    if (!/nano\\s*banana\\s*(2\\s*)?pro|banana\\s*pro/i.test(t))
                      continue;
                    const r = el.getBoundingClientRect();
                    if (r.width < 20 || r.height < 10 || r.height > 80) continue;
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


async def _select_nano_banana_pro(
    page: Any,
    *,
    custom_selector: str = "",
    model_texts: tuple[str, ...] | None = None,
) -> bool:
    """하단 모델 칩을 열어 Nano Banana Pro 를 선택 (Flash 가 기본이면 교체)."""
    del model_texts  # 칩·옵션 텍스트로 직접 판별
    before = await _toolbar_model_label(page)
    if _label_is_nano_banana_pro(before):
        _tab_log(f"모델 이미 Pro: {before[:60]}")
        return True
    _tab_log(f"모델 선택 시작 현재={before[:60] or '(없음)'}")

    if custom_selector.strip():
        loc = page.locator(custom_selector.strip()).first
        try:
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=4000)
                await page.wait_for_timeout(400)
        except Exception:
            pass

    opened = await _open_model_picker(page)
    if opened:
        _tab_log(f"모델 칩 클릭: {opened[:60]}")
        await page.wait_for_timeout(800)
    else:
        # 폴백: Model/모델 버튼
        for sel in (
            "button:has-text('Model')",
            "button:has-text('모델')",
            "[aria-label*='Model' i]",
            "[aria-label*='모델' i]",
            "[role='combobox']",
        ):
            loc = page.locator(sel).first
            try:
                if not await loc.is_visible(timeout=600):
                    continue
                await loc.click(timeout=3000)
                await page.wait_for_timeout(800)
                opened = "fallback"
                break
            except Exception:
                continue

    picked = await _click_nano_banana_pro_option(page)
    if not picked:
        try:
            loc = page.get_by_role(
                "option", name=re.compile(r"Nano Banana Pro", re.I)
            ).first
            if await loc.is_visible(timeout=1200):
                label = (await loc.inner_text() or "").strip()
                if not re.search(r"flash", label, re.I):
                    await loc.click(timeout=4000)
                    picked = label or "Nano Banana Pro"
                    _tab_log(f"Pro role=option 클릭: {picked[:60]}")
                    await page.wait_for_timeout(700)
        except Exception:
            pass
    if picked:
        _tab_log(f"Pro 옵션 클릭: {picked[:60]}")
        await page.wait_for_timeout(700)
    else:
        for text in ("Nano Banana Pro", "Nano banana pro", "Banana Pro"):
            loc = page.locator(
                f"[role='option']:has-text('{text}'), "
                f"[role='menuitem']:has-text('{text}')"
            ).first
            try:
                if not await loc.is_visible(timeout=800):
                    continue
                label = (await loc.inner_text() or "").strip()
                if re.search(r"flash", label, re.I):
                    continue
                await loc.click(timeout=4000)
                _tab_log(f"Pro 옵션 폴백 클릭: {label[:60]}")
                await page.wait_for_timeout(700)
                picked = label
                break
            except Exception:
                continue

    after = await _toolbar_model_label(page)
    ok = _label_is_nano_banana_pro(after)
    if not ok and picked and not re.search(r"flash", after or "", re.I):
        # 칩을 못 읽어도 목록에서 Pro 를 눌렀으면 성공으로 봄
        ok = True
    _tab_log(f"모델 선택 결과 ok={ok} 칩={after[:60] or '(없음)'} picked={picked[:40]}")
    return ok


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


async def _prompt_editor_candidates(
    page: Any, *, prefer_followup: bool = False
) -> list[Any]:
    """프롬프트 입력 후보.

    ``prefer_followup=True`` 이면 결과 페이지 **이어쓰기** 칸만 우선하고,
    New Image / 검색 칸은 제외한다.
    agents 채팅 입력은 왼쪽 패널(aside)에 있어도 유지한다.
    """
    scored: list[tuple[float, float, float, Any]] = []
    for sel in (
        "textarea:visible",
        "[contenteditable='true']:visible",
        "[role='textbox']:visible",
        "div[contenteditable='true']:visible",
        "input[type='text']:visible",
    ):
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(min(n, 20)):
            item = loc.nth(i)
            try:
                if not await item.is_visible():
                    continue
                if await _is_file_upload_target(item):
                    continue
                box = await item.bounding_box()
                if not box:
                    continue
                if box.get("width", 0) < 100 or box.get("height", 0) < 16:
                    continue
                meta = await item.evaluate(
                    """el => {
                      if (!el) return {kind:'reject', ro:true, ph:''};
                      const ro = !!(el.disabled || el.readOnly
                        || el.getAttribute('aria-readonly') === 'true'
                        || el.getAttribute('contenteditable') === 'false');
                      const ph = (
                        (el.getAttribute('placeholder') || '') + ' ' +
                        (el.getAttribute('aria-label') || '') + ' ' +
                        (el.getAttribute('data-placeholder') || '') + ' ' +
                        (el.getAttribute('title') || '')
                      ).toLowerCase();
                      const inSearch = !!(el.closest && el.closest(
                        '[role="search"]'
                      ));
                      const inNavOnly = !!(el.closest && el.closest(
                        'nav, [role="navigation"], header'
                      )) && !(el.closest('aside') || el.closest('[class*="sidebar" i]')
                        || el.closest('[class*="chat" i]') || el.closest('[class*="composer" i]')
                        || el.closest('[class*="prompt" i]') || el.closest('main'));
                      let kind = 'ok';
                      if (ro) kind = 'reject';
                      else if (/^\\s*(search|검색|filter|온라인에서)/.test(ph) || inSearch) kind = 'reject';
                      else if (/new\\s*image|create\\s*(an?\\s*)?image|새\\s*이미지|새\\s*대화|new\\s*chat|start\\s*a\\s*new/.test(ph))
                        kind = 'new';
                      // Genspark agents: "상상하는 장면을 설명해 주세요"
                      else if (/follow|ask|message|reply|계속|이어|메시지|질문|prompt|describe|설명|상상|장면|tell\\s*me|type\\s*(a\\s*)?(message|prompt)|chat|send\\s*a\\s*message|장면을\\s*설명/.test(ph))
                        kind = 'follow';
                      else if (inNavOnly) kind = 'reject';
                      return {kind, ro, ph, inSearch};
                    }"""
                )
                kind = str((meta or {}).get("kind") or "ok")
                if kind == "reject" or (meta or {}).get("ro"):
                    continue
                if prefer_followup and kind == "new":
                    continue
                # follow 가산, new 감점, 하단·넓은 칸 우선
                kind_boost = 50.0 if kind == "follow" else (0.0 if kind == "ok" else -30.0)
                if prefer_followup and kind != "follow":
                    kind_boost -= 20.0
                y = float(box.get("y", 0)) + float(box.get("height", 0))
                area = float(box.get("width", 0)) * float(box.get("height", 0))
                # agents 대화: 왼쪽 하단 채팅 입력 = 이어쓰기
                if prefer_followup and kind in ("ok", "follow"):
                    try:
                        vh = float(
                            await page.evaluate("() => window.innerHeight || 800")
                        )
                    except Exception:
                        vh = 800.0
                    if y >= vh * 0.35 and area >= 4000:
                        kind_boost = max(kind_boost, 55.0)
                    # placeholder 한국어 장면 설명
                    ph = str((meta or {}).get("ph") or "")
                    if re.search(r"상상|장면|설명|message|ask", ph, re.I):
                        kind_boost = max(kind_boost, 60.0)
                scored.append((kind_boost, y, area, item))
            except Exception:
                continue
    scored.sort(key=lambda t: (t[0], t[1], t[2]), reverse=True)
    if prefer_followup:
        follows = [t for t in scored if t[0] >= 45.0]
        if follows:
            scored = follows
        elif scored:
            # follow 미표기여도 최상단 후보 사용 (aside 채팅칸)
            scored = scored[:3]
    out: list[Any] = []
    seen: set[int] = set()
    for _kb, _y, _a, item in scored:
        try:
            key = await item.evaluate(
                "el => el.outerHTML.length + '|' + (el.className||'')"
            )
            hk = hash(key)
        except Exception:
            hk = id(item)
        if hk in seen:
            continue
        seen.add(hk)
        out.append(item)
    if prefer_followup and not out:
        # 최후: placeholder 로 직접 찾기
        for pat in (
            r"상상하는\s*장면",
            r"장면을\s*설명",
            r"Describe",
            r"Ask\s*(me|anything)?",
            r"Message",
            r"메시지를",
        ):
            try:
                loc = page.get_by_placeholder(re.compile(pat, re.I))
                n = await loc.count()
                for i in range(min(n, 4)):
                    item = loc.nth(i)
                    if await item.is_visible():
                        out.append(item)
            except Exception:
                continue
    if not out:
        # 랜딩/에이전트 공통 최후 수단: 보이는 textarea·textbox 전부
        raw = await _raw_visible_editors(page)
        out.extend(raw)
    return out


async def _raw_visible_editors(page: Any) -> list[Any]:
    """필터 없이 보이는 편집 가능 입력란 (진단·최후 폴백)."""
    out: list[Any] = []
    try:
        infos = await page.evaluate(
            """() => {
              const nodes = Array.from(document.querySelectorAll(
                'textarea, [contenteditable="true"], [role="textbox"]'
              ));
              return nodes.map((el) => {
                const r = el.getBoundingClientRect();
                const st = window.getComputedStyle(el);
                const ph = (el.getAttribute('placeholder') || '')
                  + ' ' + (el.getAttribute('aria-label') || '');
                const vis = st.display !== 'none' && st.visibility !== 'hidden'
                  && Number(st.opacity || '1') > 0.1
                  && r.width >= 80 && r.height >= 14
                  && r.bottom > 0 && r.top < window.innerHeight;
                const ro = !!(el.disabled || el.readOnly
                  || el.getAttribute('aria-readonly') === 'true');
                return {
                  vis, ro, tag: (el.tagName || '').toLowerCase(),
                  ph: ph.slice(0, 100),
                  w: Math.round(r.width), h: Math.round(r.height),
                  y: Math.round(r.bottom),
                  area: Math.round(r.width * r.height)
                };
              });
            }"""
        )
    except Exception as ex:
        _tab_log(f"raw editors evaluate 실패: {ex}")
        infos = []
    _tab_log(
        "raw editors: "
        + (
            " | ".join(
                f"{i.get('tag')} vis={i.get('vis')} ro={i.get('ro')} "
                f"{i.get('w')}x{i.get('h')} ph={i.get('ph')!r}"
                for i in (infos or [])[:12]
            )
            or "(none)"
        )
    )
    # Playwright: 큰 textarea / contenteditable 우선
    for sel in ("textarea", "[contenteditable='true']", "[role='textbox']"):
        try:
            loc = page.locator(sel)
            n = await loc.count()
        except Exception:
            continue
        scored: list[tuple[float, Any]] = []
        for i in range(min(n, 16)):
            el = loc.nth(i)
            try:
                if not await el.is_visible(timeout=800):
                    continue
                box = await el.bounding_box()
                if not box or box["width"] < 80 or box["height"] < 14:
                    continue
                ph = (
                    (await el.get_attribute("placeholder") or "")
                    + " "
                    + (await el.get_attribute("aria-label") or "")
                )
                if re.search(r"온라인에서|^\s*search|^\s*검색", ph, re.I):
                    continue
                # disabled?
                try:
                    if await el.is_disabled():
                        continue
                except Exception:
                    pass
                area = float(box["width"]) * float(box["height"])
                scored.append((area, el))
            except Exception:
                continue
        scored.sort(key=lambda t: t[0], reverse=True)
        for area, el in scored[:3]:
            out.append(el)
            _tab_log(f"raw pick {sel} area={area:.0f}")
        if out:
            break
    return out


async def _append_to_first_editable(page: Any, text: str) -> bool:
    """같은 입력창 끝에 텍스트 추가 (기존 SRT·프롬프트 유지)."""
    for item in await _prompt_editor_candidates(page, prefer_followup=False):
        try:
            await item.click(timeout=3000)
            await page.keyboard.press("Control+End")
            await page.keyboard.insert_text("\n\n" + text)
            await page.wait_for_timeout(300)
            return True
        except Exception:
            continue
    return False


async def _fill_first_editable(
    page: Any,
    text: str,
    *,
    prefer_followup: bool | None = None,
    skip_ready_wait: bool = False,
    ready_timeout_sec: float = 12.0,
) -> bool:
    """입력창에 텍스트 넣기.

    짧은 이어쓰기 명령(``SRT_XXX …``)은 결과 페이지 이어쓰기 칸만 사용.
    ``skip_ready_wait=True`` 이면 입력란 대기(중복)를 생략한다.
    """
    if prefer_followup is None:
        prefer_followup = _is_followup_command(text)
    # agents?id= 대화면 이어쓰기 강제
    if _score_ai_image_url(page.url or "") >= 40:
        prefer_followup = True
    if not skip_ready_wait:
        await _wait_editor_ready(page, timeout_sec=ready_timeout_sec)
    try:
        await page.evaluate(
            """() => {
              const h = document.body && document.body.scrollHeight || 0;
              window.scrollTo(0, Math.max(0, h));
            }"""
        )
        await page.wait_for_timeout(120)
    except Exception:
        pass
    candidates = await _prompt_editor_candidates(
        page, prefer_followup=prefer_followup
    )
    if prefer_followup and not candidates:
        # 이어쓰기 칸을 못 찾으면 New Image 칸으로 가지 않음 — 일반 후보만 재시도
        candidates = await _prompt_editor_candidates(page, prefer_followup=False)
    if not candidates:
        _tab_log(
            f"fill 실패: 입력칸 없음 follow={prefer_followup} "
            f"url={(page.url or '')[:100]}"
        )
        return False
    for item in candidates:
        try:
            await item.scroll_into_view_if_needed(timeout=3000)
            await item.click(timeout=3000)
            if len(text) > 400:
                try:
                    await page.evaluate(
                        """async (t) => {
                          await navigator.clipboard.writeText(t);
                        }""",
                        text,
                    )
                    await page.keyboard.press("Control+A")
                    await page.keyboard.press("Control+V")
                    await page.wait_for_timeout(180)
                    _tab_log(
                        f"fill OK(clip) follow={prefer_followup} chars={len(text)}"
                    )
                    return True
                except Exception:
                    pass
            try:
                await item.fill(text, timeout=60_000)
            except Exception:
                await page.keyboard.press("Control+A")
                await page.keyboard.insert_text(text)
            await page.wait_for_timeout(150)
            _tab_log(
                f"fill OK follow={prefer_followup} chars={len(text)} "
                f"url={(page.url or '')[:100]}"
            )
            return True
        except Exception:
            continue
    _tab_log(f"fill 실패: 후보 {len(candidates)}개")
    return False


async def _composer_text_len(page: Any) -> int:
    """이어쓰기 입력창 본문 길이 (전송 여부 확인용)."""
    try:
        return int(
            await page.evaluate(
                """() => {
                  const els = Array.from(document.querySelectorAll(
                    "textarea, [contenteditable='true'], [role='textbox']"
                  ));
                  let best = 0;
                  const vh = window.innerHeight || 800;
                  for (const el of els) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 40 || r.height < 18) continue;
                    if (r.bottom < vh * 0.35) continue;
                    const t = (el.value || el.innerText || el.textContent || '').trim();
                    if (t.length > best) best = t.length;
                  }
                  return best;
                }"""
            )
        )
    except Exception:
        return 0


async def _submit_looks_sent(page: Any, *, before_len: int) -> bool:
    """입력창 본문이 줄어야 전송된 것으로 본다.

    이전 응답의 「백그라운드에서 진행」문구만으로 성공 처리하면
    명령이 입력창에 남은 채 멈춘다.
    """
    after = await _composer_text_len(page)
    if before_len >= 30 and after < max(12, before_len // 3):
        return True
    return False


async def _composer_box(page: Any) -> dict[str, float] | None:
    try:
        box = await page.evaluate(
            """() => {
              const vh = window.innerHeight || 800;
              let best = null, bestBottom = 0;
              for (const el of document.querySelectorAll(
                "textarea, [contenteditable='true'], [role='textbox']"
              )) {
                const r = el.getBoundingClientRect();
                if (r.width < 80 || r.height < 20) continue;
                if (r.bottom < vh * 0.35) continue;
                if (r.bottom > bestBottom) {
                  bestBottom = r.bottom;
                  best = {x: r.x, y: r.y, w: r.width, h: r.height};
                }
              }
              return best;
            }"""
        )
    except Exception:
        box = None
    if not box:
        return None
    return {
        "x": float(box["x"]),
        "y": float(box["y"]),
        "w": float(box["w"]),
        "h": float(box["h"]),
    }


async def _focus_composer(page: Any) -> bool:
    """입력창 중앙을 눌러 포커스. 우하단(마이크·전송)은 누르지 않는다."""
    box = await _composer_box(page)
    if not box:
        return False
    x = box["x"] + min(box["w"] * 0.4, 120)
    y = box["y"] + box["h"] * 0.45
    try:
        await page.mouse.click(x, y)
        await page.wait_for_timeout(120)
        return True
    except Exception:
        return False


async def _click_composer_send_geo(page: Any) -> bool:
    """입력창 같은 줄의 전송 버튼을 눌러 보낸다.

    우하단 좌표 클릭은 마이크·스크롤 FAB 를 눌러 포커스만 빼므로 쓰지 않는다.
    """
    try:
        hit = await page.evaluate(
            """() => {
              const vh = window.innerHeight || 800;
              let editor = null, bestBottom = 0;
              for (const el of document.querySelectorAll(
                "textarea, [contenteditable='true'], [role='textbox']"
              )) {
                const r = el.getBoundingClientRect();
                if (r.width < 80 || r.height < 20) continue;
                if (r.bottom < vh * 0.35) continue;
                if (r.bottom > bestBottom) {
                  bestBottom = r.bottom;
                  editor = el;
                }
              }
              if (!editor) return 'no-editor';
              const er = editor.getBoundingClientRect();
              const lab = (el) => (
                (el.getAttribute('aria-label') || '') + ' '
                + (el.getAttribute('title') || '') + ' '
                + (el.innerText || '')
              ).toLowerCase();
              const skipLab = /generate|새\\s*이미지|new\\s*image|attach|upload|plus|\\+|mic|micro|voice|음성|녹음|file|clip|emoji|스크롤|scroll|add\\s*photo/;
              const isOverlayFab = (el, r) => {
                const st = getComputedStyle(el);
                if (st.position !== 'fixed' && st.position !== 'sticky')
                  return false;
                if (Math.abs(r.bottom - er.bottom) > 48) return true;
                if (r.left > er.left + 48 && r.right < er.right - 48)
                  return true;
                return false;
              };
              const enable = (el) => {
                try {
                  el.removeAttribute('disabled');
                  el.disabled = false;
                  el.setAttribute('aria-disabled', 'false');
                } catch (e) {}
              };
              const clickBtn = (el, why) => {
                enable(el);
                const r = el.getBoundingClientRect();
                return {
                  hit: why,
                  x: r.x + r.width / 2,
                  y: r.y + r.height / 2,
                };
              };
              const nodes = Array.from(document.querySelectorAll(
                'button, [role="button"]'
              ));
              for (const el of nodes) {
                const r = el.getBoundingClientRect();
                if (r.width < 16 || r.width > 96 || r.height < 16 || r.height > 96)
                  continue;
                if (isOverlayFab(el, r)) continue;
                if (Math.abs(r.bottom - er.bottom) > 72) continue;
                const t = lab(el);
                if (!/send|전송|submit|보내기|보내/.test(t)) continue;
                if (skipLab.test(t)) continue;
                return clickBtn(el, 'el-click-label');
              }
              let root = editor.closest(
                'form, [class*="composer" i], [class*="prompt" i], footer'
              ) || editor.parentElement;
              for (let i = 0; i < 6 && root && root.parentElement; i++) {
                const pr = root.getBoundingClientRect();
                if (pr.width > (window.innerWidth || 1200) * 0.96) break;
                if (pr.height > 320) break;
                const nxt = root.parentElement;
                const nr = nxt.getBoundingClientRect();
                if (nr.height > 360) break;
                root = nxt;
              }
              const hits = [];
              const scope = (root || document).querySelectorAll(
                'button, [role="button"]'
              );
              for (const el of scope) {
                const r = el.getBoundingClientRect();
                if (r.width < 16 || r.width > 96 || r.height < 16 || r.height > 96)
                  continue;
                if (Math.abs(r.bottom - er.bottom) > 72) continue;
                if (isOverlayFab(el, r)) continue;
                const t = lab(el);
                if (skipLab.test(t)) continue;
                if (r.left < er.right - 160) continue;
                if (r.left > er.right + 120) continue;
                hits.push({el, x: r.x + r.width / 2, y: r.y + r.height / 2});
              }
              hits.sort((a, b) => b.x - a.x);
              if (hits.length)
                return clickBtn(hits[0].el, 'el-click-right');
              const form = editor.closest('form');
              if (form && typeof form.requestSubmit === 'function') {
                form.requestSubmit();
                return {hit: 'form-submit', x: 0, y: 0};
              }
              return {hit: 'no-btn', x: 0, y: 0};
            }"""
        )
    except Exception:
        hit = ""
    why = ""
    x = y = 0.0
    if isinstance(hit, dict):
        why = str(hit.get("hit") or "")
        x = float(hit.get("x") or 0)
        y = float(hit.get("y") or 0)
    else:
        why = str(hit or "")
    if why in ("el-click-label", "el-click-right", "el-click") and x > 0 and y > 0:
        try:
            await page.mouse.click(x, y)
            await page.wait_for_timeout(280)
            _tab_log(f"submit geo={why} x={int(x)} y={int(y)}")
            return True
        except Exception:
            pass
    if why == "form-submit":
        await page.wait_for_timeout(280)
        _tab_log("submit geo=form-submit")
        return True
    _tab_log(f"submit geo 실패 hit={why or '-'}")
    return False


async def _click_followup_send(page: Any) -> bool:
    """이어쓰기 칸 옆 Send만 클릭 (Generate·새 이미지 제외)."""
    editors = await _prompt_editor_candidates(page, prefer_followup=True)
    if not editors:
        editors = await _prompt_editor_candidates(page, prefer_followup=False)
    box = None
    if editors:
        try:
            await editors[0].click(timeout=2000)
        except Exception:
            pass
        try:
            box = await editors[0].bounding_box()
        except Exception:
            box = None
    y0 = float(box.get("y", 0)) if box else None
    for sel in (
        "button:has-text('Send')",
        "button:has-text('전송')",
        "button:has-text('Submit')",
        "button:has-text('실행')",
        "[aria-label*='Send' i]",
        "[aria-label*='전송' i]",
        "[aria-label*='Send message' i]",
        "button[type='submit']:visible",
        "button[class*='send' i]",
    ):
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(min(n, 8)):
            btn = loc.nth(i)
            try:
                if not await btn.is_visible(timeout=600):
                    continue
                label = (
                    (await btn.inner_text(timeout=400) or "")
                    + " "
                    + (await btn.get_attribute("aria-label") or "")
                ).lower()
                if re.search(r"generate|새\s*이미지|new\s*image|create", label):
                    continue
                bb = await btn.bounding_box()
                if not bb:
                    continue
                if y0 is not None and abs(float(bb.get("y", 0)) - y0) > 140:
                    continue
                try:
                    await btn.evaluate(
                        """el => {
                          el.removeAttribute('disabled');
                          el.disabled = false;
                          el.setAttribute('aria-disabled', 'false');
                        }"""
                    )
                except Exception:
                    pass
                await btn.click(timeout=4000, force=True)
                return True
            except Exception:
                continue
    return await _click_composer_send_geo(page)


async def _ctrl_enter_submit(page: Any) -> None:
    """Genspark 채팅은 Enter=줄바꿈, Ctrl+Enter=전송인 경우가 많음."""
    try:
        await page.keyboard.press("Control+Enter")
    except Exception:
        pass
    try:
        client = await page.context.new_cdp_session(page)
        await client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "modifiers": 2,
                "windowsVirtualKeyCode": 17,
                "code": "ControlLeft",
                "key": "Control",
            },
        )
        await client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyDown",
                "modifiers": 2,
                "windowsVirtualKeyCode": 13,
                "code": "Enter",
                "key": "Enter",
                "text": "\r",
            },
        )
        await client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "modifiers": 2,
                "windowsVirtualKeyCode": 13,
                "code": "Enter",
                "key": "Enter",
            },
        )
        await client.send(
            "Input.dispatchKeyEvent",
            {
                "type": "keyUp",
                "modifiers": 0,
                "windowsVirtualKeyCode": 17,
                "code": "ControlLeft",
                "key": "Control",
            },
        )
    except Exception:
        pass


async def _submit(page: Any) -> bool:
    """이어쓰기 전송 — Send / Ctrl+Enter, 입력창이 비워질 때까지 확인.

    Enter만 누르면 줄바꿈만 되고 명령이 입력창에 남는 경우가 있다.
    전송되지 않으면 False.
    """
    before = await _composer_text_len(page)
    _tab_log(
        f"submit 시작 composer={before} url={(page.url or '')[:120]}"
    )
    if before < 8:
        _tab_log("submit 건너뜀: 입력창 비어 있음")
        return False
    await _focus_composer(page)
    methods = ("geo", "send", "ctrl", "enter", "geo2", "send2", "ctrl2")
    for name in methods:
        if name.startswith("ctrl") or name == "enter":
            await _focus_composer(page)
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass
            await page.wait_for_timeout(80)
        if name.startswith("geo"):
            hit = await _click_composer_send_geo(page)
            _tab_log(f"submit 시도 method={name} geo={hit}")
        elif name.startswith("send"):
            hit = await _click_followup_send(page)
            _tab_log(f"submit 시도 method={name} send={hit}")
        elif name.startswith("ctrl"):
            await _ctrl_enter_submit(page)
            _tab_log(f"submit 시도 method={name}")
        else:
            await page.keyboard.press("Enter")
            _tab_log(f"submit 시도 method={name}")
        await page.wait_for_timeout(550)
        after = await _composer_text_len(page)
        started = await _is_generating(page)
        if await _submit_looks_sent(page, before_len=before):
            _tab_log(
                f"submit 확인 method={name} generating={started} "
                f"composer={after}"
            )
            return True
        _tab_log(
            f"submit 미확인 method={name} generating={started} "
            f"composer={after}"
        )
    _tab_log(f"submit 실패 composer잔존={await _composer_text_len(page)}")
    return False


async def _ensure_submitted(page: Any) -> None:
    """전송될 때까지 최대 3회. 실패 시 120초 대기로 넘어가지 않는다."""
    for i in range(3):
        if await _submit(page):
            return
        _tab_log(f"submit 재시도 {i + 2}/3")
        await _focus_composer(page)
        await page.wait_for_timeout(500)
    n = await _composer_text_len(page)
    raise RuntimeError(
        f"이어쓰기 전송 실패 — 입력창에 명령이 {n}자 남아 있습니다."
    )


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
    """실수로 뜬 파일 선택 창은 즉시 빈 선택으로 닫는다.

    의도적 첨부(``_FC_ALLOW``) 중에는 가로채지 않는다.
    """

    async def _on_chooser(chooser: Any) -> None:
        if _FC_ALLOW["v"]:
            return
        try:
            await chooser.set_files([])
        except Exception:
            pass

    try:
        page.on("filechooser", lambda c: asyncio.create_task(_on_chooser(c)))
    except Exception:
        pass


def _iter_page_targets(page: Any) -> list[Any]:
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
                await asyncio.sleep(0.8)
                return True
            except Exception:
                continue
    return False


async def _click_genspark_add_entry(page: Any, paths: list[str]) -> bool:
    """입력창 왼쪽 ``+`` (add-entry-icon / 파일 및 기타 추가) → 파일 선택.

    클릭이 곧바로 filechooser 를 열거나, 메뉴가 뜬 뒤 파일/이미지 항목을
    한 번 더 눌러야 하는 두 경로를 모두 시도한다.
    """
    # 1) 아이콘·버튼 후보 (사용자가 확인한 Genspark UI)
    entry_sels = (
        "svg.add-entry-icon",
        ".add-entry-icon",
        "button:has(svg.add-entry-icon)",
        "[class*='add-entry' i]",
        "[aria-label*='파일 및 기타' i]",
        "[title*='파일 및 기타' i]",
        "[aria-label*='Add files' i]",
        "[title*='Add files' i]",
    )
    clicked = False
    for sel in entry_sels:
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            n = 0
        for i in range(min(n, 6)):
            item = loc.nth(i)
            try:
                if not await item.is_visible(timeout=400):
                    continue
                # SVG 면 클릭 가능한 부모 버튼으로
                try:
                    btn = item.locator(
                        "xpath=ancestor-or-self::button[1] | ancestor-or-self::*[@role='button'][1]"
                    ).first
                    if await btn.count() > 0 and await btn.is_visible(timeout=200):
                        target_btn = btn
                    else:
                        target_btn = item
                except Exception:
                    target_btn = item
                try:
                    async with page.expect_file_chooser(timeout=2500) as fc_info:
                        await target_btn.click(timeout=3000)
                    chooser = await fc_info.value
                    await chooser.set_files(paths)
                    await asyncio.sleep(0.6)
                    _tab_log("첨부: add-entry → filechooser 직행")
                    return True
                except Exception:
                    await target_btn.click(timeout=3000)
                    clicked = True
                    _tab_log(f"첨부: add-entry 클릭 (메뉴 대기) sel={sel}")
                    break
            except Exception:
                continue
        if clicked:
            break

    if not clicked:
        # 좌표: 입력창 왼쪽 원형 +
        try:
            hit = await page.evaluate(
                """() => {
                  const vh = window.innerHeight || 800;
                  let editor = null, best = 0;
                  for (const el of document.querySelectorAll(
                    "textarea, [contenteditable='true'], [role='textbox']"
                  )) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 80 || r.height < 20) continue;
                    if (r.bottom < vh * 0.35) continue;
                    if (r.bottom > best) { best = r.bottom; editor = el; }
                  }
                  if (!editor) return null;
                  const er = editor.getBoundingClientRect();
                  const nodes = document.querySelectorAll(
                    'button, [role="button"], svg.add-entry-icon, .add-entry-icon'
                  );
                  for (const el of nodes) {
                    const node = el.tagName === 'svg' || (el.classList && el.classList.contains('add-entry-icon'))
                      ? (el.closest('button,[role=button]') || el)
                      : el;
                    const r = node.getBoundingClientRect();
                    if (r.width < 18 || r.width > 56 || r.height < 18 || r.height > 56)
                      continue;
                    if (Math.abs(r.bottom - er.bottom) > 64) continue;
                    if (r.right > er.left + 72) continue;
                    const t = (
                      (node.getAttribute('aria-label') || '') + ' '
                      + (node.getAttribute('title') || '')
                    );
                    const hasIcon = !!(node.querySelector
                      && (node.querySelector('svg.add-entry-icon')
                        || node.querySelector('.add-entry-icon')));
                    if (hasIcon || /파일|Add files|기타 추가/i.test(t))
                      return {x: r.x + r.width / 2, y: r.y + r.height / 2};
                  }
                  return null;
                }"""
            )
            if hit and hit.get("x"):
                try:
                    async with page.expect_file_chooser(timeout=2500) as fc_info:
                        await page.mouse.click(float(hit["x"]), float(hit["y"]))
                    chooser = await fc_info.value
                    await chooser.set_files(paths)
                    await asyncio.sleep(0.6)
                    _tab_log("첨부: add-entry 좌표 → filechooser")
                    return True
                except Exception:
                    await page.mouse.click(float(hit["x"]), float(hit["y"]))
                    clicked = True
                    _tab_log("첨부: add-entry 좌표 클릭 (메뉴 대기)")
        except Exception:
            pass

    if not clicked:
        return False

    await page.wait_for_timeout(450)
    # 2) 메뉴에서 파일/이미지 항목
    for text in (
        "파일",
        "이미지",
        "사진",
        "Upload",
        "File",
        "Image",
        "Photo",
        "컴퓨터에서",
        "내 기기",
        "Browse",
        "Upload file",
        "Add file",
    ):
        for sel in (
            f"[role='menuitem']:has-text('{text}')",
            f"[role='option']:has-text('{text}')",
            f"button:has-text('{text}')",
            f"[role='button']:has-text('{text}')",
            f"div:has-text('{text}')",
            f"li:has-text('{text}')",
        ):
            item = page.locator(sel).first
            try:
                if not await item.is_visible(timeout=400):
                    continue
                async with page.expect_file_chooser(timeout=8000) as fc_info:
                    await item.click(timeout=3000)
                chooser = await fc_info.value
                await chooser.set_files(paths)
                await asyncio.sleep(0.6)
                _tab_log(f"첨부: 메뉴 '{text}' → filechooser")
                return True
            except Exception:
                continue
    # 3) 메뉴 연 뒤 숨은 file input
    if await _try_set_files_on_target(page, paths):
        _tab_log("첨부: 메뉴 후 hidden input")
        return True
    _tab_log("첨부: add-entry 클릭 후 filechooser 없음")
    return False


async def _try_filechooser_click(target: Any, paths: list[str]) -> bool:
    page = getattr(target, "page", target)
    # Genspark 입력창 왼쪽 + (파일 및 기타 추가) 우선
    if await _click_genspark_add_entry(page, paths):
        return True
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
                await asyncio.sleep(0.8)
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
        "[aria-label*='파일 및 기타' i]",
        "svg.add-entry-icon",
        ".add-entry-icon",
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
                await asyncio.sleep(0.8)
                return True
            except Exception:
                continue
    return False


async def _attach_files(page: Any, files: list[Path]) -> bool:
    """input[type=file] / filechooser 로 SRT·프롬프트 파일 첨부."""
    paths = [str(Path(p).resolve()) for p in files if Path(p).is_file()]
    if not paths:
        return False
    _FC_ALLOW["v"] = True
    try:
        for _attempt in range(8):
            for target in _iter_page_targets(page):
                if await _try_set_files_on_target(target, paths):
                    return True
            for target in _iter_page_targets(page):
                if await _try_filechooser_click(target, paths):
                    return True
            try:
                await page.locator(
                    "textarea:visible, [contenteditable='true']:visible"
                ).first.click(timeout=2000)
            except Exception:
                pass
            await page.wait_for_timeout(800)
        return False
    finally:
        _FC_ALLOW["v"] = False


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
    """실제 **현재** 생성 진행 중인지 (과거 메시지 문구는 무시)."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  // 하단·최신 구간만 — 스크롤 위쪽 옛 Thinking/생성중 문구 오탐 방지
                  const full = ((document.body && document.body.innerText) || '');
                  const t = full.slice(Math.max(0, full.length - 3500));
                  // 완료 응답의 「백그라운드에서 진행」은 오탐 — 명령이 입력창에 남은 채 멈춤
                  const doneTalk = /성공적으로\\s*생성되었습니다/.test(t)
                    && /백그라운드에서\\s*진행|다음\\s*SRT|알려\\s*주세요|준비되어/.test(t);
                  if (!doneTalk) {
                    if (/백그라운드에서\\s*진행|background[^.]{0,40}progress|완료되면\\s*자동으로\\s*결과가\\s*전달/.test(t))
                      return true;
                    if (/(?:^|[\\n\\r])\\s*(?:Thinking|생각\\s*중|generating\\.?\\.|generation in progress|생성\\s*중|생성중)\\b/im.test(t))
                      return true;
                    if (/이미지를\\s*생성하고\\s*있|생성하고\\s*있습니다/.test(t))
                      return true;
                  }
                  const prog = document.querySelector(
                    '[role="progressbar"], [aria-busy="true"]'
                  );
                  if (prog) {
                    const r = prog.getBoundingClientRect();
                    if (r.width > 4 && r.height > 4) return true;
                  }
                  const vh = window.innerHeight || 800;
                  for (const b of document.querySelectorAll('button')) {
                    const al = (
                      (b.getAttribute('aria-label') || '') + ' '
                      + (b.getAttribute('title') || '') + ' '
                      + (b.innerText || '')
                    );
                    if (!/stop|중단|중지|cancel/i.test(al)) continue;
                    if (/요청이\\s*중단|stopped/i.test(al)) continue;
                    const r = b.getBoundingClientRect();
                    // 화면 하단 활성 Stop 만
                    if (r.width > 8 && r.height > 8 && r.bottom > vh * 0.55 && r.top < vh - 2)
                      return true;
                  }
                  return false;
                }"""
            )
        )
    except Exception:
        return False


async def _wait_editor_ready(page: Any, *, timeout_sec: float = 45.0) -> bool:
    """이어쓰기 입력란이 나타날 때까지 대기 (백그라운드 생성 해제 후)."""
    deadline = time.time() + max(3.0, float(timeout_sec))
    while time.time() < deadline:
        try:
            if await _is_generating(page):
                await page.wait_for_timeout(500)
                continue
            cands = await _prompt_editor_candidates(page, prefer_followup=True)
            if cands:
                return True
            cands = await _prompt_editor_candidates(page, prefer_followup=False)
            if cands:
                return True
        except Exception:
            pass
        try:
            await page.wait_for_timeout(400)
        except Exception:
            await asyncio.sleep(0.4)
    return False


async def _wait_idle_after_download(
    page: Any, *, timeout_sec: float = 40.0, stable_hits: int = 3
) -> bool:
    """이미지 저장 후: 생성이 끝나고 이어쓰기 칸이 안정될 때까지 대기.

    다운로드 직후 다음 SRT 명령을 넣으면, 이전 생성이 남은 채로
    Enter가 삼켜지거나 생성 없이 타임아웃 나는 경우가 있다.
    """
    deadline = time.time() + max(4.0, float(timeout_sec))
    idle_hits = 0
    while time.time() < deadline:
        try:
            if await _is_generating(page):
                idle_hits = 0
                await page.wait_for_timeout(500)
                continue
            cands = await _prompt_editor_candidates(page, prefer_followup=True)
            if not cands:
                cands = await _prompt_editor_candidates(page, prefer_followup=False)
            if not cands:
                idle_hits = 0
                await page.wait_for_timeout(400)
                continue
            idle_hits += 1
            if idle_hits >= max(1, int(stable_hits)):
                return True
        except Exception:
            idle_hits = 0
        try:
            await page.wait_for_timeout(400)
        except Exception:
            await asyncio.sleep(0.4)
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


_REGEN_PREFIX = ""  # 재시도·재생성 메시지 사용 안 함



async def _failure_count(page: Any) -> int:
    """본문 ``Failure`` 개수. 우리 명령에 적어 둔 예시는 세지 않는다."""
    try:
        return int(
            await page.evaluate(
                """() => {
                  const raw = ((document.body && document.body.innerText) || '');
                  const t = raw.replace(
                    /실패면\\s*Failure[^\\n]{0,50}|Failure\\s*한\\s*줄만/gi, ' '
                  );
                  const m = t.match(/\\bFailure\\b/gi);
                  return m ? m.length : 0;
                }"""
            )
            or 0
        )
    except Exception:
        return 0


async def _page_shows_failure(page: Any, *, baseline_failures: int = 0) -> bool:
    """최신 응답에 Failure 가 새로 생겼는지.

    과거 Failure 는 무시한다 (한 번 Failure 나면 이후 대기가 즉시 끊기던 문제 방지).
    """
    try:
        now = await _failure_count(page)
        if now > max(0, int(baseline_failures)):
            return True
        # 최신(상단) 메시지 구간만
        return bool(
            await page.evaluate(
                """() => {
                  const t = ((document.body && document.body.innerText) || '')
                    .slice(0, 2200);
                  const failIdx = t.search(/\\bFailure\\b/i);
                  if (failIdx < 0) return false;
                  // 성공 문구가 Failure 보다 위에 있으면 과거 Failure
                  const okIdx = t.search(
                    /성공적으로\\s*생성|생성했습니다|api\\/files\\/s\\//i
                  );
                  if (okIdx >= 0 && okIdx < failIdx) return false;
                  return true;
                }"""
            )
        )
    except Exception:
        return False


async def _srt_success_message_seen(page: Any, srt_sec: int) -> bool:
    """``SRT_XXX 이미지가 성공적으로 생성되었습니다`` 성공 문구 감지.

    요청 문구(생성해줘)는 제외. '성공적으로 생성'을 우선한다.
    """
    try:
        return bool(
            await page.evaluate(
                """(sec) => {
                  const n = Number(sec) || 0;
                  const pad = String(n).padStart(3, '0');
                  const label = new RegExp(
                    'SRT[_\\\\s-]?(?:' + pad + '|' + n + ')\\\\b', 'i'
                  );
                  // 사용자 확인 문구: "SRT_xxx 이미지가 성공적으로 생성되었습니다"
                  const okStrict = /이미지가\\s*성공적으로\\s*생성/;
                  const okLoose = /성공적으로\\s*생성(?:되었습니다|됐습니다|됨)?/;
                  const okAlt = /이미지를\\s*생성했습니다/;
                  const tw = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                  );
                  let node;
                  while ((node = tw.nextNode())) {
                    const t = (node.textContent || '').replace(/\\s+/g, ' ').trim();
                    if (!label.test(t)) continue;
                    if (t.length > 180) continue;
                    if (/쓰지\\s*말|화면에\\s*나온\\s*뒤에만|지금\\s*실제로\\s*생성|이전\\s*SRT\\s*무시|말풍선/.test(t))
                      continue;
                    if (/생성해\\s*줘|생성해줘/i.test(t)
                        && !okStrict.test(t) && !okLoose.test(t) && !okAlt.test(t))
                      continue;
                    if (!(okStrict.test(t) || okLoose.test(t) || okAlt.test(t)))
                      continue;
                    const el = node.parentElement;
                    if (!el) continue;
                    if (el.closest(
                      'textarea, input, [contenteditable="true"]'
                    )) continue;
                    return true;
                  }
                  for (const el of document.querySelectorAll(
                    'div, section, article, li, p'
                  )) {
                    const t = ((el.innerText || '') + '').replace(/\\s+/g, ' ').trim();
                    if (t.length > 180) continue;
                    if (!label.test(t)) continue;
                    if (/쓰지\\s*말|화면에\\s*나온\\s*뒤에만|지금\\s*실제로\\s*생성|이전\\s*SRT\\s*무시|말풍선/.test(t))
                      continue;
                    if (!(okStrict.test(t) || okLoose.test(t))) continue;
                    if (el.closest(
                      'textarea, input, [contenteditable="true"]'
                    )) continue;
                    return true;
                  }
                  return false;
                }""",
                int(srt_sec),
            )
        )
    except Exception:
        return False


async def _generation_error_ui(page: Any) -> bool:
    """응답 옆 회색 느낌표·error 배지 (이미지는 없고 성공 문구만 올 때)."""
    try:
        return bool(
            await page.evaluate(
                """() => {
                  const vh = window.innerHeight || 800;
                  const vw = window.innerWidth || 1200;
                  const nodes = document.querySelectorAll(
                    'button, [role="button"], [aria-label], [title], svg, img, span'
                  );
                  for (const el of nodes) {
                    const r = el.getBoundingClientRect();
                    if (r.width < 10 || r.width > 44 || r.height < 10 || r.height > 44)
                      continue;
                    if (r.left < vw * 0.50 || r.top < 48 || r.bottom > vh - 70)
                      continue;
                    const t = (
                      (el.getAttribute('aria-label') || '') + ' '
                      + (el.getAttribute('title') || '') + ' '
                      + (el.getAttribute('data-tooltip') || '') + ' '
                      + (el.className || '')
                    ).toLowerCase();
                    if (/error|fail|실패|warning|경고|exclaim/.test(t))
                      return true;
                  }
                  return false;
                }"""
            )
        )
    except Exception:
        return False


async def _collect_genspark_file_urls(page: Any) -> list[str]:
    """페이지의 genspark api/files img URL 목록."""
    try:
        raw = await page.evaluate(
            """() => {
              const out = [];
              for (const img of document.querySelectorAll('img')) {
                const src = img.currentSrc || img.src
                  || img.getAttribute('data-src') || '';
                if (/genspark\\.ai\\/api\\/files/i.test(src)) out.push(src);
              }
              return out;
            }"""
        )
        if isinstance(raw, list):
            return [str(u) for u in raw if u]
    except Exception:
        pass
    return []


async def _first_unseen_file_url(
    page: Any,
    *,
    forbid_keys: set[str] | None = None,
    last_saved: str = "",
    baseline: str = "",
) -> str:
    for src in await _collect_genspark_file_urls(page):
        if _is_unseen_file_url(
            src,
            forbid_keys=forbid_keys,
            last_saved=last_saved,
            baseline=baseline,
        ):
            return src
    return ""


async def _assistant_skipped_generation(page: Any, srt_sec: int) -> bool:
    """새 그림 없이 이전 SRT 이야지만 하는지 (예: SRT_165 이전 턴)."""
    try:
        return bool(
            await page.evaluate(
                """(sec) => {
                  const t = ((document.body && document.body.innerText) || '')
                    .slice(0, 4500);
                  if (/백그라운드에서\\s*진행|생성하고\\s*있|generating/i.test(t))
                    return false;
                  if (/준비\\s*완료|이미지\\s*생성/.test(t))
                    return false;
                  const skip = /이전\\s*턴|이미\\s*생성되어\\s*완료|Generated image metadata|어떤 SRT 이미지를 생성/;
                  if (!skip.test(t)) return false;
                  const n = Number(sec) || 0;
                  const pad = String(n).padStart(3, '0');
                  const selfOk = new RegExp(
                    'SRT[_\\\\s-]?(?:' + pad + '|' + n
                    + ')\\\\s*이미지가\\\\s*성공적으로\\\\s*생성'
                  );
                  if (selfOk.test(t) && /api\\/files/i.test(t)) return false;
                  return true;
                }""",
                int(srt_sec),
            )
        )
    except Exception:
        return False


async def _wait_generation_done(
    page: Any,
    *,
    baseline_count: int,
    prev_src: str = "",
    timeout_sec: int = 120,
    context: Any | None = None,
    baseline_failures: int = 0,
    srt_sec: int | None = None,
    baseline_near_src: str = "",
    forbid_keys: set[str] | None = None,
    last_saved_src: str = "",
) -> tuple[bool, Any]:
    """성공 메시지 + 그 아래 **아직 받지 않은** ``api/files`` 이미지까지 대기.

    직전 저장 URL·seen URL 은 새 이미지로 보지 않는다.
    ``(완료여부, page)`` 반환.
    """
    del baseline_count  # 호환용
    deadline = asyncio.get_event_loop().time() + max(120, int(timeout_sec))
    started = asyncio.get_event_loop().time()
    t0 = time.perf_counter()
    stable = 0
    forbid = set(forbid_keys or set())
    last_saved = last_saved_src or prev_src
    fail_base = max(0, int(baseline_failures))
    last_progress_log = 0.0
    _tab_log(
        f"⏱ 생성대기 시작 SRT_{(srt_sec or 0):03d} max={max(120, int(timeout_sec))}s"
    )

    async def _recover() -> Any:
        nonlocal page
        if context is None:
            return page
        try:
            if page is not None and not page.is_closed():
                return page
        except Exception:
            pass
        _tab_log("생성대기: 작업탭 닫힘 → 복구")
        page = await _alive_page(context, page)
        _tab_log(f"생성대기: 복구됨 · {await _tab_snapshot(context, page)}")
        return page

    try:
        await page.wait_for_timeout(600)
    except Exception as ex:
        if "closed" in str(ex).lower() and context is not None:
            page = await _recover()
        else:
            raise
    while asyncio.get_event_loop().time() < deadline:
        try:
            page = await _recover()
            if await _page_shows_failure(page, baseline_failures=fail_base):
                _tab_log(
                    f"⏱ 생성대기 Failure {_timing_sec(t0)}s "
                    f"SRT_{(srt_sec or 0):03d}"
                )
                return False, page
            if srt_sec is not None and await _srt_label_shows_failure(
                page, int(srt_sec)
            ):
                if not await _srt_success_message_seen(page, int(srt_sec)):
                    _tab_log(
                        f"⏱ 생성대기 SRT Failure {_timing_sec(t0)}s "
                        f"SRT_{int(srt_sec):03d}"
                    )
                    return False, page

            busy = await _is_generating(page)
            near = ""
            if srt_sec is not None:
                near = (
                    await _file_src_near_srt_label(
                        page, int(srt_sec), forbid_keys=forbid
                    )
                    or ""
                ).strip()
            else:
                near = await _first_unseen_file_url(
                    page,
                    forbid_keys=forbid,
                    last_saved=last_saved,
                    baseline=baseline_near_src,
                )
            url_ok = _is_unseen_file_url(
                near,
                forbid_keys=forbid,
                last_saved=last_saved,
                baseline=baseline_near_src,
            )

            elapsed = _timing_sec(t0)
            if elapsed - last_progress_log >= 15.0:
                last_progress_log = elapsed
                _tab_log(
                    f"⏱ 생성대기 진행 {_timing_sec(t0)}s "
                    f"SRT_{(srt_sec or 0):03d} busy={busy} url_ok={url_ok} "
                    f"src={_short_src(near)}"
                )

            if url_ok and not busy:
                stable += 1
                if stable >= 1:
                    await page.wait_for_timeout(250)
                    _tab_log(
                        f"⏱ 생성대기 완료 {_timing_sec(t0)}s "
                        f"SRT_{(srt_sec or 0):03d} "
                        f"{_short_src(near)}"
                    )
                    return True, page
            elif url_ok:
                stable += 1
                if stable >= 2:
                    _tab_log(
                        f"⏱ 생성대기 완료(busy무시) {_timing_sec(t0)}s "
                        f"SRT_{(srt_sec or 0):03d} "
                        f"{_short_src(near)}"
                    )
                    return True, page
            else:
                if (
                    srt_sec is not None
                    and not busy
                    and await _srt_success_message_seen(page, int(srt_sec))
                    and await _generation_error_ui(page)
                ):
                    _tab_log(
                        f"⏱ 생성대기 성공문구·오류아이콘 "
                        f"{_timing_sec(t0)}s SRT_{int(srt_sec):03d}"
                    )
                    return False, page
                if (
                    srt_sec is not None
                    and (asyncio.get_event_loop().time() - started) >= 18
                    and await _assistant_skipped_generation(page, int(srt_sec))
                ):
                    _tab_log(
                        f"⏱ 생성대기 스킵감지 {_timing_sec(t0)}s "
                        f"SRT_{int(srt_sec):03d}"
                    )
                    return False, page
                stable = 0
            # 생성 중은 0.7s, 이미 보이면 0.4s
            await page.wait_for_timeout(700 if busy and not url_ok else 400)
        except Exception as ex:
            if "closed" in str(ex).lower() and context is not None:
                _tab_log(f"생성대기 예외(closed): {ex}")
                page = await _recover()
                await asyncio.sleep(0.4)
                continue
            raise

    # 생성 지연: 제한 직후 늦게 붙는 이미지는 해당 SRT 성공 문구 아래만 인정
    if srt_sec is not None:
        extra_until = asyncio.get_event_loop().time() + 25.0
        while asyncio.get_event_loop().time() < extra_until:
            near = (
                await _file_src_near_srt_label(
                    page, int(srt_sec), forbid_keys=forbid
                )
                or ""
            ).strip()
            if _is_unseen_file_url(
                near,
                forbid_keys=forbid,
                last_saved=last_saved,
                baseline=baseline_near_src,
            ):
                _tab_log(
                    f"⏱ 생성대기 지연도착 {_timing_sec(t0)}s "
                    f"SRT_{int(srt_sec):03d} "
                    f"{_short_src(near)}"
                )
                return True, page
            await page.wait_for_timeout(800)
    else:
        near = await _first_unseen_file_url(
            page,
            forbid_keys=forbid,
            last_saved=last_saved,
            baseline=baseline_near_src,
        )
        if near:
            _tab_log(
                f"⏱ 생성대기 시간초과·이미지로 완료 {_timing_sec(t0)}s "
                f"SRT_{(srt_sec or 0):03d}"
            )
            return True, page
    if await _page_shows_failure(page, baseline_failures=fail_base):
        return False, page
    _tab_log(
        f"⏱ 생성대기 시간초과 {_timing_sec(t0)}s "
        f"SRT_{(srt_sec or 0):03d} "
        f"(새 api/files 이미지 없음, max={max(120, int(timeout_sec))}s)"
    )
    return False, page


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
                    if (src.toLowerCase().includes('www.genspark.ai/api/files')
                        || src.toLowerCase().includes('genspark.ai/api/files'))
                      last = src;
                  }
                  return last;
                }"""
            )
            or ""
        )
    except Exception:
        return ""


async def _file_src_near_srt_label(
    page: Any,
    srt_sec: int,
    *,
    forbid_keys: set[str] | None = None,
) -> str:
    """해당 SRT 요청(또는 성공 문구) 근처의 미수신 이미지 URL.

    성공 문구가 없어도, 방금 보낸 ``SRT_XXX`` 명령 **아래**
    (「이미지 생성」 카드) 그림을 고른다. 다음 SRT 요청보다 아래는 쓰지 않는다.
    """
    forbid = [k for k in (forbid_keys or set()) if k]
    try:
        return str(
            await page.evaluate(
                """({sec, forbid}) => {
                  const n = Number(sec) || 0;
                  const pad = String(n).padStart(3, '0');
                  const re = new RegExp(
                    'SRT[_\\\\s-]?(?:' + pad + '|' + n + ')\\\\b', 'i'
                  );
                  const otherSrt = /SRT[_\\\\s-]?\\\\d+/i;
                  const instr = /쓰지\\s*말|화면에\\s*나온\\s*뒤에만|지금\\s*실제로\\s*생성|이전\\s*SRT\\s*무시|말풍선/;
                  const keyOf = (src) => {
                    const u = String(src).split('#')[0].split('?')[0]
                      .toLowerCase().replace(/\\/$/, '');
                    const m = u.match(
                      /https?:\\/\\/(?:www\\.)?genspark\\.ai\\/api\\/files\\/(?:s\\/)?[^/\\s]+/
                    );
                    return m ? m[0] : u;
                  };
                  const banned = new Set(
                    (forbid || []).map(u => keyOf(u)).filter(Boolean)
                  );
                  const bubbleOf = (el) => {
                    let block = el;
                    for (let i = 0; i < 8 && block.parentElement; i++) {
                      const p = block.parentElement;
                      const big = p.querySelector
                        && p.querySelector('img');
                      if (big) {
                        const ir = big.getBoundingClientRect();
                        if (ir.width >= 200 && ir.height >= 160) break;
                      }
                      const pb = p.getBoundingClientRect();
                      if (pb.height > 1800) break;
                      if (pb.width > (window.innerWidth || 1200) * 0.9) break;
                      block = p;
                    }
                    return block.getBoundingClientRect();
                  };
                  const markers = [];
                  const otherTops = [];
                  const tw = document.createTreeWalker(
                    document.body, NodeFilter.SHOW_TEXT
                  );
                  let node;
                  while ((node = tw.nextNode())) {
                    const t = node.textContent || '';
                    const el = node.parentElement;
                    if (!el) continue;
                    if (el.closest(
                      'textarea, input, [contenteditable="true"], nav, header'
                    )) continue;
                    const raw = el.getBoundingClientRect();
                    if (raw.width < 2 && raw.height < 2) continue;
                    if (!re.test(t)) {
                      if (otherSrt.test(t)) otherTops.push(raw.top);
                      continue;
                    }
                    const box = bubbleOf(el);
                    const isFail = /\\\\bFailure\\\\b/i.test(t)
                      || (/Failure/i.test(
                        (el.closest('div,section,article,li') || el).innerText || ''
                      ) && raw.top < 400);
                    const isRes = /이미지가\\s*성공적으로\\s*생성/.test(t)
                      && !instr.test(t);
                    markers.push({
                      y: box.bottom,
                      top: box.top,
                      req: !isRes,
                      res: isRes,
                      fail: isFail,
                    });
                  }
                  if (!markers.length) return '';
                  const imgs = [];
                  const visit = (root) => {
                    if (!root || !root.querySelectorAll) return;
                    for (const img of root.querySelectorAll('img')) {
                      const src = img.currentSrc || img.src
                        || img.getAttribute('data-src') || '';
                      if (!src) continue;
                      const r = img.getBoundingClientRect();
                      if (r.width < 48 || r.height < 48) continue;
                      const isFile = /genspark\\.ai\\/api\\/files/i.test(src);
                      const okSrc = /^https?:/i.test(src) || /^blob:/i.test(src);
                      if (!isFile && !(okSrc && r.width >= 200 && r.height >= 160))
                        continue;
                      if (banned.has(keyOf(src))) continue;
                      imgs.push({
                        src, y: r.top, bottom: r.bottom, file: isFile,
                      });
                    }
                    for (const el of root.querySelectorAll('*')) {
                      if (el.shadowRoot) visit(el.shadowRoot);
                    }
                  };
                  visit(document);
                  if (!imgs.length) return '';
                  const stopAfter = (y) => {
                    let s = 1e12;
                    for (const t of otherTops) {
                      if (t > y + 24 && t < s) s = t;
                    }
                    return s === 1e12 ? 0 : s;
                  };
                  const pickNear = (m, mode) => {
                    const nextStop = mode === 'below' ? stopAfter(m.y) : 0;
                    const tryPick = (filesOnly) => {
                      let best = null;
                      let bestD = 1e12;
                      for (const im of imgs) {
                        if (filesOnly && !im.file) continue;
                        let d = 1e12;
                        if (mode === 'above') {
                          if (im.bottom > m.top + 24) continue;
                          d = m.top - im.bottom;
                          if (d > 220) continue;
                        } else {
                          if (im.y + 8 < m.y) continue;
                          if (nextStop && im.y >= nextStop - 4) continue;
                          d = im.y - m.y;
                          if (d > 6000) continue;
                        }
                        if (d < bestD) { bestD = d; best = im; }
                      }
                      return best;
                    };
                    return tryPick(true) || tryPick(false);
                  };
                  const resMs = markers.filter(m => m.res && !(m.fail && !m.res));
                  for (const m of resMs) {
                    const above = pickNear(m, 'above');
                    if (above) return above.src;
                    const below = pickNear(m, 'below');
                    if (below) return below.src;
                  }
                  const reqMs = markers.filter(m => m.req)
                    .sort((a, b) => b.y - a.y);
                  for (const m of reqMs) {
                    const below = pickNear(m, 'below');
                    if (below) return below.src;
                  }
                  return '';
                }""",
                {"sec": int(srt_sec), "forbid": forbid},
            )
            or ""
        )
    except Exception as ex:
        _tab_log(f"SRT 근접 이미지 탐색 실패: {ex}")
        return ""


async def _srt_label_shows_failure(page: Any, srt_sec: int) -> bool:
    """해당 SRT_XXX 근처(본문)에 Failure 가 있는지."""
    try:
        return bool(
            await page.evaluate(
                """(sec) => {
                  const n = Number(sec) || 0;
                  const pad = String(n).padStart(3, '0');
                  const re = new RegExp(
                    'SRT[_\\\\s-]?(?:' + pad + '|' + n + ')\\\\b', 'i'
                  );
                  const blocks = document.querySelectorAll(
                    'div, section, article, li, p'
                  );
                  for (const el of blocks) {
                    const t = (el.innerText || '').slice(0, 1200);
                    if (!re.test(t)) continue;
                    if (/쓰지\\s*말|화면에\\s*나온\\s*뒤에만|지금\\s*실제로\\s*생성|말풍선/.test(t))
                      continue;
                    if (/\\\\bFailure\\\\b/i.test(t)) return true;
                  }
                  return false;
                }""",
                int(srt_sec),
            )
        )
    except Exception:
        return False


def _image_url_key(src: str) -> str:
    """중복 판별 키. api/files 우선, 없으면 blob·일반 이미지 URL."""
    key = normalize_genspark_file_url(src)
    if key:
        return key
    u = (src or "").strip()
    if not u or is_tracking_url(u):
        return ""
    if u.startswith("blob:"):
        return u
    if looks_like_image_url(u) or u.startswith(("http://", "https://")):
        return u.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()
    return ""


def _short_src(src: str) -> str:
    return (_image_url_key(src) or src or "")[:90]


def _is_unseen_file_url(
    src: str,
    *,
    forbid_keys: set[str] | None = None,
    last_saved: str = "",
    baseline: str = "",
) -> bool:
    """이미 받은·직전 저장·제출 전 근접 URL 이 아닌 새 이미지인지."""
    key = _image_url_key(src)
    if not key:
        return False
    if forbid_keys and key in forbid_keys:
        return False
    last_k = _image_url_key(last_saved)
    if last_k and key == last_k:
        return False
    base_k = _image_url_key(baseline)
    if base_k and key == base_k:
        return False
    return True


def _file_url_map_path(png_dir: Path) -> Path:
    return Path(png_dir) / ".genspark_file_urls.json"


def _load_seen_file_urls(png_dir: Path) -> dict[str, str]:
    """``{normalized_url: SRT_XXX.png}``."""
    path = _file_url_map_path(png_dir)
    if not path.is_file():
        return {}
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return {str(k): str(v) for k, v in data.items() if k and v}
    except Exception:
        pass
    return {}


def _save_seen_file_urls(png_dir: Path, mapping: dict[str, str]) -> None:
    path = _file_url_map_path(png_dir)
    try:
        import json

        path.write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


async def _salvage_late_images(
    page: Any,
    png_dir: Path,
    pending_secs: list[int],
    seen_file_urls: dict[str, str],
) -> str:
    """타임아웃 후 늦게 뜬 이미지를 원래 SRT 파일명으로 저장."""
    last_src = ""
    keep: list[int] = []
    for sec in pending_secs:
        if png_already_exists(png_dir, sec):
            continue
        dest = png_dir / srt_png_name(sec)
        try:
            saved, file_src = await _save_latest_image_to(
                page,
                dest,
                forbid_keys=set(seen_file_urls.keys()),
                srt_sec=sec,
            )
        except Exception as ex:
            _tab_log(f"늦은이미지 회수 실패 SRT_{sec:03d}: {ex}")
            keep.append(sec)
            continue
        key = _image_url_key(file_src)
        if key:
            seen_file_urls[key] = dest.name
            _save_seen_file_urls(png_dir, seen_file_urls)
        last_src = file_src
        _tab_log(f"늦은이미지 회수 SRT_{sec:03d} → {saved.name}")
    pending_secs[:] = keep[-8:]
    return last_src


async def _save_latest_image_to(
    page: Any,
    dest: Path,
    *,
    prefer_button: bool = False,
    forbid_keys: set[str] | None = None,
    require_new_vs: str = "",
    srt_sec: int | None = None,
) -> tuple[Path, str]:
    """``api/files`` 이미지 다운로드 → dest(SRT_XXX.png).

    ``srt_sec`` 가 있으면 본문 ``SRT_XXX`` 성공 메시지 아래 **미수신** 이미지를 우선한다.
    이미 받은 URL 이면 저장하지 않고 오류.
    반환: ``(경로, 원본 URL)``.
    """
    del prefer_button
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)

    from scene_image.download import download_url

    file_src = ""
    if srt_sec is not None:
        file_src = (
            await _file_src_near_srt_label(
                page, int(srt_sec), forbid_keys=forbid_keys
            )
            or ""
        ).strip()
        if file_src:
            _tab_log(
                f"SRT_{int(srt_sec):03d} 근접 이미지 "
                f"{_short_src(file_src)}"
            )
        else:
            raise RuntimeError(
                f"SRT_{int(srt_sec):03d} 요청 아래 새 이미지가 없습니다."
            )
    if not file_src:
        file_src = (
            await _first_unseen_file_url(
                page,
                forbid_keys=forbid_keys,
                last_saved=require_new_vs,
                baseline=require_new_vs,
            )
            or ""
        ).strip()
        if file_src:
            _tab_log(
                f"폴백: 미수신 api/files "
                f"{_short_src(file_src)}"
            )
    if not file_src:
        raise RuntimeError(
            f"SRT_{int(srt_sec or 0):03d} 새 이미지가 없습니다."
        )
    if is_tracking_url(file_src) or not (
        is_genspark_file_url(file_src)
        or looks_like_image_url(file_src)
        or file_src.startswith(("http://", "https://", "blob:"))
    ):
        raise RuntimeError(
            "새 이미지 URL을 찾지 못했습니다. "
            "생성이 끝난 뒤 다시 시도하세요."
        )

    key = _image_url_key(file_src)
    if not _is_unseen_file_url(
        file_src,
        forbid_keys=forbid_keys,
        last_saved=require_new_vs,
        baseline=require_new_vs,
    ):
        raise RuntimeError(
            f"이미 받은 api/files 이미지입니다 (중복 저장 방지).\n{key[:120]}"
        )
    _tab_log(f"다운로드 files URL={key[:120] or file_src[:120]} → {dest.name}")
    t_dl = time.perf_counter()

    try:
        if file_src.startswith("blob:"):
            raise RuntimeError("blob URL")
        download_url(file_src, dest)
        if dest.is_file() and dest.stat().st_size >= 512:
            _tab_log(
                f"⏱ 다운로드 직접 {_timing_sec(t_dl)}s "
                f"size={dest.stat().st_size} {dest.name}"
            )
            return dest, file_src
    except Exception as ex:
        _tab_log(
            f"⏱ 다운로드 직접실패 {_timing_sec(t_dl)}s · 페이지 fetch 재시도: {ex}"
        )

    t_fetch = time.perf_counter()
    b64 = await page.evaluate(
        """async (u) => {
          const r = await fetch(u, { credentials: 'include' });
          if (!r.ok) return '';
          const buf = await r.arrayBuffer();
          const bytes = new Uint8Array(buf);
          let binary = '';
          const chunk = 0x8000;
          for (let i = 0; i < bytes.length; i += chunk) {
            binary += String.fromCharCode.apply(
              null, bytes.subarray(i, i + chunk)
            );
          }
          return btoa(binary);
        }""",
        file_src,
    )
    if not b64:
        raise RuntimeError(f"api/files 다운로드 실패: {file_src[:120]}")
    dest.write_bytes(base64.b64decode(b64))
    if not dest.is_file() or dest.stat().st_size < 512:
        raise RuntimeError(f"다운로드 검증 실패: {dest.name}")
    _tab_log(
        f"⏱ 다운로드 fetch {_timing_sec(t_fetch)}s "
        f"size={dest.stat().st_size} {dest.name}"
    )
    return dest, file_src


async def _save_storage_state(context: Any, path: Path) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        await context.storage_state(path=str(path.resolve()))
    except Exception:
        pass


_SAME_TAB_SCRIPT = """
(() => {
  if (window.__wisdomSameTabV3) return;
  window.__wisdomSameTabV3 = true;
  const go = (url) => {
    try {
      if (url && typeof url === 'string' && url.length && url !== 'about:blank') {
        window.location.assign(url);
      }
    } catch (e) {}
  };
  try {
    window.open = function(url) { go(url); return window; };
  } catch (e) {}
  try {
    Object.defineProperty(window, 'open', {
      configurable: true,
      writable: true,
      value: function(url) { go(url); return window; }
    });
  } catch (e) {}
  const retarget = (el) => {
    try {
      if (!el || !el.closest) return null;
      const a = el.closest('a');
      if (a && a.getAttribute('target') === '_blank') a.setAttribute('target', '_self');
      const f = el.closest('form');
      if (f && f.getAttribute('target') === '_blank') f.setAttribute('target', '_self');
      return a;
    } catch (err) { return null; }
  };
  const blockNew = (e) => {
    try {
      const a = retarget(e.target);
      if (!a) return;
      if (e.ctrlKey || e.metaKey || e.shiftKey || e.button === 1
          || (a.getAttribute('target') || '').toLowerCase() === '_blank') {
        const href = a.href || a.getAttribute('href') || '';
        if (href && !href.startsWith('#') && !href.startsWith('javascript:')) {
          e.preventDefault();
          e.stopPropagation();
          go(href);
        }
      }
    } catch (err) {}
  };
  document.addEventListener('click', blockNew, true);
  document.addEventListener('auxclick', blockNew, true);
  document.addEventListener('mousedown', (e) => { retarget(e.target); }, true);
  try {
    const mo = new MutationObserver(() => {
      document.querySelectorAll('a[target="_blank"], form[target="_blank"]').forEach(el => {
        el.setAttribute('target', '_self');
      });
    });
    mo.observe(document.documentElement, { childList: true, subtree: true, attributes: true, attributeFilter: ['target'] });
  } catch (err) {}
})();
"""


async def _ensure_ai_image_page(
    page: Any, url: str, *, prefer_url: str = ""
) -> bool:
    """동일 탭 유지. agents 대화(id=)가 있으면 랜딩 ai_image 로 돌아가지 않는다."""
    cur = (page.url or "").strip()
    prefer = (prefer_url or "").strip()
    cur_sc = _score_ai_image_url(cur)
    prefer_sc = _score_ai_image_url(prefer)
    _tab_log(
        f"ensure_page cur_sc={cur_sc} prefer_sc={prefer_sc} "
        f"cur={(cur or '')[:100]} prefer={(prefer or '')[:100]}"
    )
    # 이미 대화 세션(agents?id= 등)이면 그대로
    if cur_sc >= 40:
        return False
    # 저장된 대화 URL이 더 좋으면 복귀
    if prefer_sc >= 40 and prefer_sc > cur_sc:
        await page.goto(prefer, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(800)
        await _install_same_tab_guards(page)
        return True
    if prefer_sc >= 30 and prefer_sc > cur_sc:
        await page.goto(prefer, wait_until="domcontentloaded", timeout=90_000)
        await page.wait_for_timeout(800)
        await _install_same_tab_guards(page)
        return True
    # 랜딩·약한 agents 페이지면 유지 (첫 붙여넣기용)
    if cur_sc >= 10:
        return False
    await page.goto(url, wait_until="domcontentloaded", timeout=90_000)
    await page.wait_for_timeout(1500)
    await _install_same_tab_guards(page)
    return True


def _score_ai_image_url(url: str) -> int:
    """대화/결과 탭일수록 높은 점수. 랜딩·로그인은 낮음.

    Genspark 이미지 생성은 제출 후 ``/agents?id=…`` 로 이동한다.
    이 URL을 낮게 보면 이어쓰기 때 랜딩으로 돌아가 새 창·새 대화가 열린다.
    """
    u = (url or "").lower()
    if not u or "genspark" not in u:
        return -100
    if "accounts.google" in u:
        return -100
    # 활성 대화 세션 (이어쓰기 대상)
    if "/agents" in u and "id=" in u:
        return 80
    if "/agents" in u and "image_generation" in u:
        if "chat_now" in u or "action=" in u:
            return 55
        return 35
    if "ai_image" not in u and "ai-image" not in u:
        return 0
    bare = u.split("?")[0].rstrip("/")
    if bare.endswith("/ai_image") or bare.endswith("/ai-image"):
        return 10  # 랜딩
    return 40  # ai_image + 쿼리(구형 대화)

async def _install_same_tab_guards(page: Any) -> None:
    """새 창/새 탭 열기 금지 — 항상 현재 탭에서만 이동."""
    try:
        await page.add_init_script(_SAME_TAB_SCRIPT)
    except Exception:
        pass
    try:
        await page.evaluate(_SAME_TAB_SCRIPT)
    except Exception:
        pass


async def _install_context_same_tab_guards(context: Any) -> None:
    try:
        await context.add_init_script(_SAME_TAB_SCRIPT)
    except Exception:
        pass


async def _leave_single_tab(context: Any, url: str, page: Any | None = None) -> Any:
    """탭을 1개만 남기고 url로 연다. 「브라우저 열기」용."""
    pages = [p for p in list(getattr(context, "pages", []) or []) if not p.is_closed()]
    keep = page if page is not None and not page.is_closed() else (pages[0] if pages else None)
    if keep is None:
        keep = await context.new_page()
    for p in list(getattr(context, "pages", []) or []):
        if p is keep:
            continue
        try:
            if not p.is_closed():
                await p.close()
        except Exception:
            pass
    await keep.goto(url, wait_until="domcontentloaded", timeout=90_000)
    await keep.wait_for_timeout(800)
    await _install_same_tab_guards(keep)
    return keep


async def _alive_page(context: Any, page: Any) -> Any:
    """닫힌 page 참조를 복구. 동일 탭(Genspark)을 우선한다."""
    try:
        if page is not None and not page.is_closed():
            return page
    except Exception:
        pass
    pages = list(getattr(context, "pages", []) or [])
    best = None
    best_sc = -999
    for p in pages:
        try:
            if p.is_closed():
                continue
            sc = _score_ai_image_url(p.url or "")
            if sc > best_sc:
                best_sc = sc
                best = p
        except Exception:
            continue
    if best is not None:
        await _install_same_tab_guards(best)
        try:
            await best.bring_to_front()
        except Exception:
            pass
        return best
    raise RuntimeError(
        "브라우저 탭이 닫혔습니다. 「브라우저 열기」를 다시 눌러 주세요."
    )


async def _close_all_extra_tabs(context: Any, keep: Any) -> None:
    """keep 이외 탭만 닫는다. keep가 유일한 탭이면 아무 것도 안 함."""
    try:
        alive = [p for p in list(context.pages or []) if not p.is_closed()]
    except Exception:
        return
    if len(alive) <= 1:
        return
    keep_id = id(keep) if keep is not None else None
    closed_n = 0
    for p in alive:
        if keep is not None and (p is keep or id(p) == keep_id):
            continue
        try:
            if p.is_closed():
                continue
            pu = (p.url or "").lower()
            if "accounts.google" in pu:
                continue
            _tab_log(f"탭닫기(여분) url={(p.url or '')[:100]}")
            await p.close()
            closed_n += 1
        except Exception as ex:
            _tab_log(f"탭닫기 실패: {ex}")
    if closed_n:
        _tab_log(f"여분 탭 닫음 n={closed_n} · {await _tab_snapshot(context, keep)}")


async def _adopt_same_tab(
    context: Any, page: Any, *, navigate: bool = True
) -> Any:
    """여분 탭을 정리. ``navigate=True`` 이면 더 좋은 Genspark URL로 작업 탭 이동.

    생성 대기 중에는 ``navigate=False`` 로 호출해 작업 탭 네비게이션을 막는다.
    """
    page = await _alive_page(context, page)
    await _install_same_tab_guards(page)
    before = await _tab_snapshot(context, page)

    page_score = _score_ai_image_url(page.url or "")
    best_url = ""
    best_score = -999
    best_page = None
    for p in list(getattr(context, "pages", []) or []):
        if p is page:
            continue
        try:
            if p.is_closed():
                continue
            u = (p.url or "").strip()
            if not u or u.startswith("about:") or u.startswith("chrome:"):
                continue
            sc = _score_ai_image_url(u)
            if "genspark" in u.lower() and sc >= 10 and sc >= page_score and sc >= best_score:
                best_score = sc
                best_url = u
                best_page = p
        except Exception:
            continue

    if best_page is not None and best_score > page_score:
        # 새 탭이 더 좋은 대화면 그 탭을 작업 탭으로 승격 (goto 로 기존 탭 깨지 않음)
        _tab_log(
            f"adopt: 작업탭 승격 score {page_score}→{best_score} url={best_url[:100]}"
        )
        page = best_page
        await _install_same_tab_guards(page)
    elif navigate and best_url:
        try:
            await page.bring_to_front()
            if (page.url or "").rstrip("/") != best_url.rstrip("/"):
                _tab_log(f"adopt: goto {best_url[:100]}")
                await page.goto(best_url, wait_until="domcontentloaded", timeout=90_000)
                await page.wait_for_timeout(300)
        except Exception as ex:
            _tab_log(f"adopt: goto 실패 {ex}")
            page = await _alive_page(context, page)

    await _close_all_extra_tabs(context, page)
    page = await _alive_page(context, page)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    await _install_same_tab_guards(page)
    after = await _tab_snapshot(context, page)
    if before != after:
        _tab_log(f"adopt 후 · {after}")
    return page


async def _merge_popup_into_page(
    context: Any, page: Any, popup: Any, *, allow_navigate: bool = True
) -> Any:
    """새 탭 URL만 기존 탭으로 옮기고 팝업을 닫는다. 기존 page를 닫지 않음."""
    # 빈/약:blank 팝업은 그냥 닫기
    try:
        if popup is None or popup.is_closed():
            return await _alive_page(context, page)
    except Exception:
        return await _alive_page(context, page)

    try:
        if page is not None and not page.is_closed() and popup is page:
            return page
    except Exception:
        pass

    dest = ""
    for _ in range(16):
        try:
            if popup.is_closed():
                break
            u = (popup.url or "").strip()
            if u.startswith("about:") or u.startswith("chrome:"):
                await asyncio.sleep(0.2)
                continue
            if u and "genspark" in u.lower():
                dest = u
                break
            if u and "genspark" not in u.lower() and "google" not in u.lower():
                break
        except Exception:
            break
        await asyncio.sleep(0.15)

    popup_score = _score_ai_image_url(dest) if dest else -100
    page_alive = page is not None and not page.is_closed()
    page_score = _score_ai_image_url(page.url or "") if page_alive else -100
    _tab_log(
        f"merge: popup={(dest or (getattr(popup, 'url', '') or ''))[:100]} "
        f"score={popup_score} page_score={page_score} nav={allow_navigate} · "
        f"{await _tab_snapshot(context, page)}"
    )

    # 팝업이 더 좋은 대화면 작업 탭을 팝업으로 바꾸고 예전 탭만 닫기
    if dest and popup_score > page_score and not popup.is_closed():
        old = page
        page = popup
        _tab_log(f"merge: 작업탭=새탭 승격 (구탭 닫기)")
        try:
            if old is not None and old is not page and not old.is_closed():
                await old.close()
        except Exception:
            pass
        await _install_same_tab_guards(page)
        await _close_all_extra_tabs(context, page)
        return await _alive_page(context, page)

    # 팝업만 닫기 (page 유지)
    try:
        if not popup.is_closed() and popup is not page:
            await popup.close()
            _tab_log("merge: 팝업 닫음")
    except Exception as ex:
        _tab_log(f"merge: 팝업 닫기 실패 {ex}")

    page = await _alive_page(context, page)
    if allow_navigate and dest and "genspark" in dest.lower():
        try:
            await page.bring_to_front()
            if (page.url or "").rstrip("/") != dest.rstrip("/"):
                _tab_log(f"merge: page.goto {dest[:100]}")
                await page.goto(dest, wait_until="domcontentloaded", timeout=90_000)
                await page.wait_for_timeout(250)
        except Exception as ex:
            _tab_log(f"merge: goto 실패 {ex}")
            page = await _alive_page(context, page)
    await _close_all_extra_tabs(context, page)
    page = await _alive_page(context, page)
    await _install_same_tab_guards(page)
    try:
        await page.bring_to_front()
    except Exception:
        pass
    return page


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
    # 1) 이미 열린 Chrome(CDP)에 연결 — 재시작 직후 여유 있게 대기
    for _ in range(60):
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

    raise RuntimeError(
        "ChromeDebug(CDP)에 연결하지 못했습니다.\n"
        "「브라우저 열기」로 ChromeDebug를 먼저 띄운 뒤 다시 시도하세요."
    )


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

    def paste_text(
        self,
        *,
        url: str,
        text: str,
        model_selector: str = "",
        try_model_select: bool = True,
        model_texts: tuple[str, ...] | list[str] | None = None,
        append: bool = False,
    ) -> dict[str, bool]:
        """입력창에만 붙여넣기 (전송하지 않음). ``append=True`` 면 기존 내용 뒤에 추가."""
        return self._call(
            "paste",
            {
                "url": url,
                "text": text,
                "model_selector": model_selector,
                "try_model": try_model_select,
                "model_texts": list(model_texts or []),
                "append": bool(append),
            },
            timeout=240.0,
        )

    def attach_files(
        self,
        *,
        url: str,
        files: list[str | Path],
        model_selector: str = "",
        try_model_select: bool = True,
        model_texts: tuple[str, ...] | list[str] | None = None,
    ) -> dict[str, bool]:
        """SRT·이미지프롬프트 파일을 페이지에 첨부."""
        return self._call(
            "attach",
            {
                "url": url,
                "files": [str(Path(p)) for p in files],
                "model_selector": model_selector,
                "try_model": try_model_select,
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
        retry_count: int = 1,
        retry_wait_sec: int = 30,
        generate_timeout_sec: int = 120,
        use_existing_input: bool = False,
        srt_path: str | Path | None = None,
        interval_sec: int = 20,
        prompt_path: str | Path | None = None,
    ) -> dict[str, Any]:
        """명령 전송 → 생성 완료 대기 → 다운로드.

        실패 시 재시도하지 않는다 (호출측에서 다음 씬으로 진행).
        ``use_existing_input=True`` 이면 입력창(SRT·프롬프트+명령)을 그대로 전송한다.
        """
        del retry_wait_sec  # 재시도 없음
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
                "retry_count": 1,
                "retry_wait_sec": 0,
                "generate_timeout_sec": int(generate_timeout_sec),
                "use_existing_input": bool(use_existing_input),
                "srt_path": str(srt_path) if srt_path else "",
                "interval_sec": int(interval_sec),
                "prompt_path": str(prompt_path) if prompt_path else "",
            },
            timeout=float(max(300, generate_timeout_sec + 120)),
        )

    async def _async_worker(self) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await _launch_context(pw, self._profile_dir)
            await _install_context_same_tab_guards(context)
            page = context.pages[0] if context.pages else await context.new_page()
            _attach_filechooser_guard(page)
            await _install_same_tab_guards(page)
            for p in list(context.pages or []):
                _attach_filechooser_guard(p)
            model_ready = False
            work_url = ""
            # 붙여넣기·생성 중에는 새 탭 합치기 잠시 보류 (작업 탭 오닫힘 방지)
            merge_pause = {"v": False}
            # 이미 받은 genspark.ai/api/files/s/… → 파일명 (중복 저장 방지)
            seen_file_urls: dict[str, str] = {}
            last_saved_file_url = ""
            pending_fail_secs: list[int] = []
            char_state_tracker: Any | None = None
            try:

                def _on_new_page(p: Any) -> None:
                    # 새 탭/창 — URL·개수 로그 후, 생성 중이면 합치기 보류
                    _attach_filechooser_guard(p)

                    async def _merge() -> None:
                        nonlocal page
                        try:
                            u0 = ""
                            try:
                                u0 = (p.url or "")[:120]
                            except Exception:
                                u0 = "?"
                            _tab_log(
                                f"NEW_PAGE pause={merge_pause['v']} url={u0} · "
                                f"{await _tab_snapshot(context, page)}"
                            )
                        except Exception:
                            pass
                        if merge_pause["v"]:
                            # 생성·붙여넣기 중: 빈 팝업만 닫고, Genspark 탭은
                            # 작업 탭보다 점수가 높으면 승격만 (goto 금지)
                            try:
                                await asyncio.sleep(0.4)
                                if p.is_closed():
                                    return
                                u = (p.url or "").lower()
                                if (
                                    not u
                                    or u.startswith("about:")
                                    or u.startswith("chrome:")
                                ):
                                    if p is not page:
                                        await p.close()
                                        _tab_log("NEW_PAGE(pause): about:blank 닫음")
                                    return
                                # Genspark 대화 탭이면 승격만 (네비게이션 X)
                                if "genspark" in u:
                                    page = await _merge_popup_into_page(
                                        context, page, p, allow_navigate=False
                                    )
                                    _tab_log(
                                        f"NEW_PAGE(pause): merge/승격 · "
                                        f"{await _tab_snapshot(context, page)}"
                                    )
                            except Exception as ex:
                                _tab_log(f"NEW_PAGE(pause) 예외: {ex}")
                            return
                        try:
                            page = await _merge_popup_into_page(
                                context, page, p, allow_navigate=True
                            )
                            _tab_log(
                                f"NEW_PAGE: merge 완료 · "
                                f"{await _tab_snapshot(context, page)}"
                            )
                        except Exception as ex:
                            _tab_log(f"NEW_PAGE merge 실패: {ex}")
                            try:
                                if p is not page and not p.is_closed():
                                    await p.close()
                            except Exception:
                                pass
                            try:
                                page = await _alive_page(context, page)
                            except Exception:
                                pass

                    asyncio.create_task(_merge())

                context.on("page", _on_new_page)
            except Exception:
                pass

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
                        merge_pause["v"] = True
                        # 기존 탭 전부 닫고 새 탭 1개만
                        page = await _leave_single_tab(context, url, page)
                        page = await _alive_page(context, page)
                        work_url = page.url or url
                        await _install_same_tab_guards(page)
                        merge_pause["v"] = False
                        # storageState/쿠키로 로그인 유지 — 만료 시에만 재로그인
                        login_info = await _ensure_login(
                            page,
                            email,
                            password,
                            context=context,
                            force=False,
                        )
                        if "genspark.ai" not in (page.url or "").lower() or (
                            _score_ai_image_url(page.url or "") < 10
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
                            if _score_ai_image_url(page.url or "") < 10:
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
                        page = await _adopt_same_tab(context, page)
                        work_url = page.url or work_url or url
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
                    elif op == "paste":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        mtexts = tuple(data.get("model_texts") or []) or None
                        merge_pause["v"] = True
                        try:
                            page = await _alive_page(context, page)
                            if await _ensure_ai_image_page(
                                page, url, prefer_url=work_url or ""
                            ):
                                model_ready = False
                            page = await _alive_page(context, page)
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
                            text = (data.get("text") or data.get("prompt") or "").strip()
                            if not text:
                                raise RuntimeError("붙여넣을 텍스트가 비어 있습니다.")
                            # 랜딩 입력란 로드 대기
                            if not await _wait_editor_ready(page, timeout_sec=60.0):
                                _tab_log("paste: 입력란 대기 초과 — raw 재시도")
                                await page.wait_for_timeout(1500)
                            if data.get("append"):
                                ok = await _append_to_first_editable(page, text)
                            else:
                                follow = _is_followup_command(text)
                                ok = await _fill_first_editable(
                                    page, text, prefer_followup=follow
                                )
                            if not ok:
                                # 한 번 더: 페이지 새로고침 없이 raw 폴백만
                                raw = await _raw_visible_editors(page)
                                if raw:
                                    try:
                                        await raw[0].click(timeout=3000)
                                        if len(text) > 8_000:
                                            await page.evaluate(
                                                """async (t) => {
                                                  await navigator.clipboard.writeText(t);
                                                }""",
                                                text,
                                            )
                                            await page.keyboard.press("Control+A")
                                            await page.keyboard.press("Control+V")
                                        else:
                                            await page.keyboard.press("Control+A")
                                            await page.keyboard.insert_text(text)
                                        ok = True
                                        _tab_log("paste: raw 폴백 성공")
                                    except Exception as ex:
                                        _tab_log(f"paste: raw 폴백 실패 {ex}")
                            if not ok:
                                raise RuntimeError(
                                    "명령어 입력란을 찾지 못했습니다. "
                                    "로그인·페이지 로드 후 다시 시도하세요."
                                )
                            page = await _alive_page(context, page)
                            await page.wait_for_timeout(400)
                            resp_q.put((True, {"model_auto": bool(model_auto)}, None))
                        finally:
                            merge_pause["v"] = False
                    elif op == "attach":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        mtexts = tuple(data.get("model_texts") or []) or None
                        files = [
                            Path(p)
                            for p in (data.get("files") or [])
                            if Path(p).is_file()
                        ]
                        if not files:
                            raise RuntimeError("첨부할 파일이 없습니다.")
                        if await _ensure_ai_image_page(
                            page, url, prefer_url=work_url or ""
                        ):
                            model_ready = False
                            await page.wait_for_timeout(500)
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
                        ok = await _attach_files(page, files)
                        if not ok:
                            raise RuntimeError(
                                "파일 첨부 UI를 찾지 못했습니다. "
                                "페이지 로드·로그인 후 다시 「브라우저 열기」하세요."
                            )
                        await page.wait_for_timeout(800)
                        resp_q.put(
                            (
                                True,
                                {
                                    "model_auto": bool(model_auto),
                                    "attached": True,
                                    "n_files": len(files),
                                },
                                None,
                            )
                        )
                    elif op == "submit":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        mtexts = tuple(data.get("model_texts") or []) or None
                        page = await _adopt_same_tab(context, page)
                        if await _ensure_ai_image_page(
                            page, url, prefer_url=work_url or ""
                        ):
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
                        follow = _is_followup_command(prompt)
                        if not await _fill_first_editable(
                            page, prompt, prefer_followup=follow
                        ):
                            raise RuntimeError(
                                "명령어 입력란을 찾지 못했습니다. "
                                "로그인·페이지 로드 후 다시 시도하세요."
                            )
                        await _install_same_tab_guards(page)
                        await _ensure_submitted(page)
                        await page.wait_for_timeout(400)
                        page = await _adopt_same_tab(context, page)
                        await _close_all_extra_tabs(context, page)
                        if page.url and _score_ai_image_url(page.url) >= 35:
                            work_url = _maybe_set_work_url(work_url, page.url)
                        resp_q.put((True, {"model_auto": bool(model_auto)}, None))
                    elif op == "run_scene":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_AI_IMAGE_URL
                        prompt_raw = (data.get("prompt") or "").strip()
                        png_dir = Path(data.get("png_dir") or ".")
                        srt_sec = int(data.get("srt_sec") or 0)
                        srt_path = (data.get("srt_path") or "").strip() or None
                        interval_sec = max(1, int(data.get("interval_sec") or 20))
                        from scene_image.character_consistency import CharacterStateTracker

                        if char_state_tracker is None:
                            char_state_tracker = CharacterStateTracker.load(png_dir)
                        prompt = build_generate_command_from_sources(
                            srt_sec,
                            scene_prompt=prompt_raw or None,
                            srt_path=srt_path,
                            interval_sec=interval_sec,
                            png_dir=png_dir,
                            state_tracker=char_state_tracker,
                        )
                        if isinstance(char_state_tracker, CharacterStateTracker):
                            _tab_log(
                                f"상태키 SRT_{srt_sec:03d} · "
                                f"{char_state_tracker.summary()}"
                            )
                        mtexts = tuple(data.get("model_texts") or []) or None
                        gen_timeout = max(120, int(data.get("generate_timeout_sec") or 120))
                        use_existing_input = bool(data.get("use_existing_input"))
                        # data retry_* 무시 — 재시도 없음
                        _ = data.get("retry_count")
                        _ = data.get("retry_wait_sec")
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
                        set_tab_log_png_dir(png_dir)
                        # png 폴더에 기록된 기존 files URL 로드
                        seen_file_urls.update(_load_seen_file_urls(png_dir))
                        if not last_saved_file_url and seen_file_urls:
                            last_saved_file_url = next(reversed(seen_file_urls.keys()))
                        page = await _alive_page(context, page)
                        if pending_fail_secs:
                            late = await _salvage_late_images(
                                page,
                                png_dir,
                                pending_fail_secs,
                                seen_file_urls,
                            )
                            if late:
                                last_saved_file_url = late
                        _tab_log(
                            f"run_scene 시작 SRT_{srt_sec:03d} · "
                            f"seen_files={len(seen_file_urls)} · "
                            f"last_saved="
                            f"{normalize_genspark_file_url(last_saved_file_url)[:80]}"
                        )
                        # 재시도 없음 — 1회만 시도 후 실패 시 호출측이 다음 씬으로
                        retry_count = 1
                        retry_wait = 0
                        for attempt in range(1, retry_count + 1):
                            try:
                                # 제출~다운로드 끝까지 탭 합치기 보류
                                merge_pause["v"] = True
                                t_scene = time.perf_counter()
                                t_phase = t_scene
                                page = await _alive_page(context, page)
                                # 이미 대화 세션이면 ensure/goto 생략 (다음 씬 지연 핵심)
                                if _score_ai_image_url(page.url or "") < 40:
                                    await _ensure_ai_image_page(
                                        page, url, prefer_url=work_url or ""
                                    )
                                    page = await _alive_page(context, page)
                                await _install_same_tab_guards(page)
                                if data.get("try_model"):
                                    model_ready = await _select_nano_banana_pro(
                                        page,
                                        custom_selector=str(
                                            data.get("model_selector") or ""
                                        ),
                                        model_texts=mtexts,
                                    )
                                fail_before = await _failure_count(page)
                                send_prompt = prompt
                                forbid = set(seen_file_urls.keys())
                                prev_src = (last_saved_file_url or "").strip()
                                if not prev_src:
                                    prev_src = (
                                        await _genspark_file_src(page) or ""
                                    ).strip()
                                baseline_near = ""
                                t_phase = _timing_log(
                                    f"준비 SRT_{srt_sec:03d}",
                                    t_phase,
                                    extra=f"chars={len(send_prompt)}",
                                )
                                if use_existing_input and attempt == 1:
                                    await _install_same_tab_guards(page)
                                    await _ensure_submitted(page)
                                    t_phase = _timing_log(
                                        f"입력창전송 SRT_{srt_sec:03d}",
                                        t_phase,
                                    )
                                else:
                                    # 이전 이미지 다운로드·생성 종료 후에만 다음 명령 입력·전송
                                    idle_ok = await _wait_idle_after_download(
                                        page, timeout_sec=40.0
                                    )
                                    if not idle_ok:
                                        _tab_log(
                                            "다음명령 유휴 대기 시간 초과 — 입력 시도"
                                        )
                                    t_phase = _timing_log(
                                        f"다음명령유휴 SRT_{srt_sec:03d}",
                                        t_phase,
                                        extra=f"idle={idle_ok}",
                                    )
                                    if not await _fill_first_editable(
                                        page,
                                        send_prompt,
                                        prefer_followup=_is_followup_command(send_prompt),
                                        skip_ready_wait=True,
                                    ):
                                        raise RuntimeError(
                                            "이어쓰기 입력란을 찾지 못했습니다."
                                        )
                                    await _ensure_submitted(page)
                                    t_phase = _timing_log(
                                        f"입력·전송 SRT_{srt_sec:03d}",
                                        t_phase,
                                        extra=f"chars={len(send_prompt)}",
                                    )
                                _tab_log(
                                    f"제출 후 last_saved="
                                    f"{normalize_genspark_file_url(prev_src)[:80]}"
                                )
                                try:
                                    await page.wait_for_timeout(200)
                                except Exception:
                                    page = await _alive_page(context, page)
                                page = await _alive_page(context, page)
                                if page.url and "genspark" in (page.url or "").lower():
                                    work_url = _maybe_set_work_url(work_url, page.url)
                                t_gen = time.perf_counter()
                                ok, page = await _wait_generation_done(
                                    page,
                                    baseline_count=0,
                                    prev_src=prev_src,
                                    timeout_sec=max(120, gen_timeout),
                                    context=context,
                                    baseline_failures=fail_before,
                                    srt_sec=srt_sec,
                                    baseline_near_src=baseline_near,
                                    forbid_keys=forbid,
                                    last_saved_src=prev_src,
                                )
                                t_phase = _timing_log(
                                    f"생성대기구간 SRT_{srt_sec:03d}",
                                    t_gen,
                                    extra=f"ok={ok}",
                                )
                                if await _page_shows_failure(
                                    page, baseline_failures=fail_before
                                ) or (
                                    await _srt_label_shows_failure(page, srt_sec)
                                    and not await _srt_success_message_seen(
                                        page, srt_sec
                                    )
                                ):
                                    raise RuntimeError(
                                        "Failure 메시지 감지 — 다음 씬으로 진행"
                                    )
                                if not ok:
                                    if await _srt_success_message_seen(
                                        page, srt_sec
                                    ):
                                        raise RuntimeError(
                                            "이미지는 없고 성공 문구만 있음 "
                                            "— 다음 씬으로 진행"
                                        )
                                    raise RuntimeError(
                                        f"새 이미지 대기 초과 "
                                        f"({max(120, gen_timeout)}s) "
                                        "— 다음 씬으로 진행"
                                    )
                                dest = png_dir / srt_png_name(srt_sec)
                                t_dl = time.perf_counter()
                                saved, file_src = await _save_latest_image_to(
                                    page,
                                    dest,
                                    prefer_button=False,
                                    forbid_keys=forbid,
                                    require_new_vs=prev_src,
                                    srt_sec=srt_sec,
                                )
                                t_phase = _timing_log(
                                    f"다운로드구간 SRT_{srt_sec:03d}",
                                    t_dl,
                                    extra=dest.name,
                                )
                                if not saved.is_file() or saved.stat().st_size < 512:
                                    raise RuntimeError(
                                        f"다운로드 후 파일 없음: {dest.name}"
                                    )
                                key = _image_url_key(file_src)
                                if key:
                                    seen_file_urls[key] = dest.name
                                    _save_seen_file_urls(png_dir, seen_file_urls)
                                    last_saved_file_url = file_src
                                saved_paths = [str(saved)]
                                page = await _alive_page(context, page)
                                t_idle = time.perf_counter()
                                idle_ok = await _wait_idle_after_download(
                                    page, timeout_sec=40.0
                                )
                                _timing_log(
                                    f"다운로드후유휴 SRT_{srt_sec:03d}",
                                    t_idle,
                                    extra=f"idle={idle_ok}",
                                )
                                _timing_log(
                                    f"씬합계 SRT_{srt_sec:03d}",
                                    t_scene,
                                    extra=f"{key[:70]}",
                                )
                                if page.url:
                                    work_url = _maybe_set_work_url(work_url, page.url)
                                resp_q.put(
                                    (
                                        True,
                                        {
                                            "ok": True,
                                            "attempt": 1,
                                            "regenerated": False,
                                            "saved": saved_paths,
                                            "file_url": file_src,
                                        },
                                        None,
                                    )
                                )
                                break
                            except Exception as ex:
                                last_err = str(ex)
                                if srt_sec not in pending_fail_secs:
                                    pending_fail_secs.append(int(srt_sec))
                                _tab_log(
                                    f"run_scene 실패(재시도 없음): {last_err}"
                                )
                                resp_q.put(
                                    (
                                        False,
                                        None,
                                        RuntimeError(last_err),
                                    )
                                )
                                break
                            finally:
                                merge_pause["v"] = False
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
