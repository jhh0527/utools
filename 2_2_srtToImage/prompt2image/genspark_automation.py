# -*- coding: utf-8 -*-
"""Genspark ai_image — 생성 이미지 클릭·확대·다운로드 자동화 (Playwright)."""

from __future__ import annotations

import asyncio
import base64
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

from prompt2image.browser_launch import (
    CDP_PORTS,
    GENSPARK_URL,
    ensure_chrome_cdp,
)
from prompt2image.public_figure_hint import build_public_figure_hint
from prompt2image.srt_naming import format_srt_filename
StatusCb = Callable[[str], None] | None


def ensure_playwright() -> None:
    try:
        import playwright  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "자동 다운로드에 Playwright 가 필요합니다.\n\n"
            "설치:\n"
            "  pip install playwright\n"
            "  playwright install chrome"
        ) from e


def _emit(on_status: StatusCb, msg: str) -> None:
    if on_status:
        on_status(msg)


def _first_locator(page: Any, selectors: list[str]) -> Any | None:
    for sel in selectors:
        loc = page.locator(sel)
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


def _looks_like_login_url(url: str) -> bool:
    from prompt2image.genspark_selectors import LOGIN_URL_HINTS

    u = (url or "").lower()
    return any(h in u for h in LOGIN_URL_HINTS)


async def _safe_scroll(loc: Any) -> None:
    try:
        await loc.scroll_into_view_if_needed(timeout=2000)
    except Exception:
        pass


async def _resolve_editable_locator(item: Any) -> Any:
    """래퍼를 클릭한 경우 내부 textarea·contenteditable 을 찾습니다."""
    try:
        tag = (await item.evaluate("el => (el.tagName || '').toUpperCase()")) or ""
    except Exception:
        tag = ""
    if tag in ("TEXTAREA", "INPUT"):
        return item
    try:
        is_editable = await item.evaluate(
            """el => !!(
                el.isContentEditable
                || el.getAttribute('contenteditable') === 'true'
                || el.getAttribute('role') === 'textbox'
            )"""
        )
        if is_editable:
            return item
    except Exception:
        pass
    for sel in (
        "textarea",
        "input:not([type='hidden'])",
        "[contenteditable='true']",
        "[role='textbox']",
    ):
        try:
            inner_loc = item.locator(sel)
            if await inner_loc.count() > 0:
                return inner_loc.first
        except Exception:
            continue
    return item


async def _locator_from_custom_selector(page: Any, selector: str) -> Any | None:
    sel = (selector or "").strip()
    if not sel:
        return None
    try:
        loc = page.locator(sel).first
        if await loc.count() == 0:
            return None
        return await _resolve_editable_locator(loc)
    except Exception:
        return None


async def _find_prompt_input(
    page: Any,
    *,
    custom_selector: str | None = None,
) -> Any | None:
    from prompt2image.genspark_selectors import PROMPT_INPUTS

    item = await _locator_from_custom_selector(page, custom_selector or "")
    if item is not None:
        return item

    for sel in PROMPT_INPUTS:
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
                box = await item.bounding_box()
                if box and (box.get("width", 0) < 40 or box.get("height", 0) < 12):
                    continue
                return item
            except Exception:
                continue

    for ph in ("image", "이미지", "Describe", "prompt", "프롬프트", "무엇", "Ask"):
        try:
            loc = page.get_by_placeholder(ph, exact=False)
            if await loc.count() > 0:
                item = loc.first
                if await item.is_visible():
                    return item
        except Exception:
            continue
    return None


async def _fill_prompt_via_js(item: Any, text: str) -> bool:
    try:
        ok = await item.evaluate(
            """(el, t) => {
              const pick = () => {
                if (!el) return null;
                const tag = (el.tagName || '').toUpperCase();
                if (tag === 'TEXTAREA' || tag === 'INPUT') return el;
                if (
                  el.isContentEditable
                  || el.getAttribute('contenteditable') === 'true'
                  || el.getAttribute('role') === 'textbox'
                ) return el;
                return el.querySelector(
                  'textarea, input:not([type="hidden"]), [contenteditable="true"], [role="textbox"]'
                );
              };
              const target = pick();
              if (!target) return false;
              target.focus();
              if (target.tagName === 'TEXTAREA' || target.tagName === 'INPUT') {
                target.value = t;
              } else {
                target.textContent = t;
              }
              target.dispatchEvent(new Event('input', { bubbles: true }));
              target.dispatchEvent(new Event('change', { bubbles: true }));
              return true;
            }""",
            text,
        )
        return bool(ok)
    except Exception:
        return False


async def _fill_prompt_input(page: Any, item: Any, text: str) -> bool:
    item = await _resolve_editable_locator(item)

    if await _fill_prompt_via_js(item, text):
        return True

    for use_force in (False, True):
        try:
            await _safe_scroll(item)
            await item.click(timeout=5000, force=use_force)
            tag = ""
            try:
                tag = (await item.evaluate("el => el.tagName")) or ""
            except Exception:
                pass
            if str(tag).upper() == "TEXTAREA":
                try:
                    await item.fill(text, timeout=12_000, force=use_force)
                except Exception:
                    await page.keyboard.press("Control+A")
                    await page.keyboard.insert_text(text)
            else:
                await page.keyboard.press("Control+A")
                await page.keyboard.press("Backspace")
                await page.keyboard.insert_text(text)
            return True
        except Exception:
            continue

    return await _fill_prompt_via_js(item, text)


async def _wait_and_fill_prompt(
    page: Any,
    text: str,
    *,
    wait_ms: int = 90_000,
    on_status: StatusCb = None,
    custom_selector: str | None = None,
) -> bool:
    """SPA·로그인 대기 후 프롬프트 입력란에 텍스트를 넣습니다."""
    deadline = time.monotonic() + wait_ms / 1000.0
    last_status = 0.0
    while time.monotonic() < deadline:
        url = page.url or ""
        if _looks_like_login_url(url):
            if time.monotonic() - last_status > 4.0:
                _emit(
                    on_status,
                    "Genspark 로그인 화면 — 열린 Chrome에서 로그인하세요…",
                )
                last_status = time.monotonic()
        else:
            item = await _find_prompt_input(page, custom_selector=custom_selector)
            if item is not None:
                if await _fill_prompt_input(page, item, text):
                    return True
            elif custom_selector and time.monotonic() - last_status > 4.0:
                _emit(
                    on_status,
                    "지정한 입력란을 찾는 중… (Genspark 화면·지정 셀렉터 확인)",
                )
                last_status = time.monotonic()

        await asyncio.sleep(0.6)

    return False


_PICK_PROMPT_SETUP_JS = """
() => {
  if (window.__wisdom_pick_cleanup) {
    window.__wisdom_pick_cleanup();
  }
  window.__wisdom_picked_selector = null;

  const overlay = document.createElement("div");
  overlay.id = "__wisdom_pick_overlay";
  overlay.textContent =
    "Genspark 프롬프트 입력란을 클릭하세요 (wisdom 입력란 지정)";
  overlay.style.cssText =
    "position:fixed;top:0;left:0;right:0;padding:14px 16px;" +
    "background:#1565c0;color:#fff;z-index:2147483647;text-align:center;" +
    "font:600 15px/1.4 system-ui,sans-serif;box-shadow:0 2px 8px rgba(0,0,0,.25);";

  const buildSelector = (el) => {
    if (!(el instanceof Element)) return "";
    if (el.id) return "#" + CSS.escape(el.id);
    const attrs = ["data-testid", "data-id", "name", "aria-label", "placeholder"];
    for (const a of attrs) {
      const v = el.getAttribute(a);
      if (v) {
        const tag = el.tagName.toLowerCase();
        return `${tag}[${a}="${v.replace(/"/g, '\\\\"')}"]`;
      }
    }
    const parts = [];
    let cur = el;
    while (cur && cur.nodeType === 1 && parts.length < 6) {
      let part = cur.tagName.toLowerCase();
      const role = cur.getAttribute("role");
      if (role) part += `[role="${role}"]`;
      const parent = cur.parentElement;
      if (parent) {
        const same = Array.from(parent.children).filter(
          (c) => c.tagName === cur.tagName
        );
        if (same.length > 1) {
          part += `:nth-of-type(${same.indexOf(cur) + 1})`;
        }
      }
      parts.unshift(part);
      cur = parent;
    }
    return parts.join(" > ");
  };

  const pickEditable = (el) => {
    if (!(el instanceof Element)) return null;
    const tag = (el.tagName || "").toUpperCase();
    if (tag === "TEXTAREA" || tag === "INPUT") return el;
    if (
      el.isContentEditable
      || el.getAttribute("contenteditable") === "true"
      || el.getAttribute("role") === "textbox"
    ) return el;
    const inner = el.querySelector(
      'textarea, input:not([type="hidden"]), [contenteditable="true"], [role="textbox"]'
    );
    return inner || el;
  };

  const onClick = (e) => {
    if (overlay.contains(e.target)) return;
    e.preventDefault();
    e.stopPropagation();
    const el = pickEditable(e.target);
    if (!el) return;
    window.__wisdom_picked_selector = buildSelector(el);
    cleanup();
  };

  const cleanup = () => {
    document.removeEventListener("click", onClick, true);
    overlay.remove();
    window.__wisdom_pick_cleanup = null;
  };

  window.__wisdom_pick_cleanup = cleanup;
  document.body.appendChild(overlay);
  document.addEventListener("click", onClick, true);
}
"""


async def _interactive_pick_prompt_selector(
    page: Any,
    *,
    wait_ms: int = 120_000,
    on_status: StatusCb = None,
) -> str:
    """사용자가 Genspark 입력란을 클릭하면 CSS 셀렉터를 반환합니다."""
    _emit(on_status, "자동화 Chrome — Genspark 입력란을 클릭하세요…")
    await page.evaluate(_PICK_PROMPT_SETUP_JS)
    deadline = time.monotonic() + wait_ms / 1000.0
    while time.monotonic() < deadline:
        try:
            sel = await page.evaluate("() => window.__wisdom_picked_selector || ''")
            if isinstance(sel, str) and sel.strip():
                return sel.strip()
        except Exception:
            pass
        await asyncio.sleep(0.25)
    try:
        await page.evaluate(
            "() => { if (window.__wisdom_pick_cleanup) window.__wisdom_pick_cleanup(); }"
        )
    except Exception:
        pass
    raise RuntimeError(
        "입력란 지정 시간이 초과되었습니다.\n\n"
        "자동화 Chrome에서 Genspark 프롬프트 입력란을 클릭해 주세요."
    )


async def pick_genspark_prompt_selector(
    *,
    png_dir: Path,
    on_status: StatusCb = None,
) -> str:
    """Genspark 페이지에서 사용자가 클릭한 입력란의 CSS 셀렉터를 얻습니다."""
    ensure_playwright()
    from playwright.async_api import async_playwright

    png_dir.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as p:
        context = await _launch_context(p, png_dir=png_dir, on_status=on_status)
        page = await _find_genspark_ai_image_page(context, on_status=on_status)
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=20_000)
        except Exception:
            pass
        return await _interactive_pick_prompt_selector(page, on_status=on_status)


async def _gpt_image_2_selected(page: Any) -> bool:
    from prompt2image.genspark_selectors import GPT_IMAGE_2_SELECTED_HINTS

    for label in GPT_IMAGE_2_SELECTED_HINTS:
        for factory in (
            lambda t: page.locator(f"button:has-text('{t}')"),
            lambda t: page.locator(f"[role='button']:has-text('{t}')"),
            # Genspark 상단 칩/라벨이 button이 아닐 수 있어 텍스트 자체도 확인
            lambda t: page.get_by_text(t, exact=False),
            lambda t: page.locator(f":text('{t}')"),
            lambda t: page.locator(f"[aria-selected='true']:has-text('{t}')"),
            lambda t: page.locator(f"[data-selected='true']:has-text('{t}')"),
        ):
            try:
                loc = factory(label).first
                if await loc.is_visible(timeout=600):
                    return True
            except Exception:
                continue
    return False


async def _open_model_picker(page: Any) -> bool:
    from prompt2image.genspark_selectors import MODEL_PICKER_TRIGGERS

    for sel in MODEL_PICKER_TRIGGERS:
        btn = page.locator(sel).first
        try:
            if await btn.is_visible(timeout=800):
                await btn.click(timeout=5000)
                await page.wait_for_timeout(400)
                return True
        except Exception:
            continue
    return False


async def _click_gpt_image_2_option(page: Any) -> bool:
    from prompt2image.genspark_selectors import GPT_IMAGE_2_OPTIONS

    for label in GPT_IMAGE_2_OPTIONS:
        for factory in (
            lambda t: page.get_by_role("option", name=t, exact=False),
            lambda t: page.get_by_role("menuitem", name=t, exact=False),
            lambda t: page.locator(f"[role='option']:has-text('{t}')"),
            lambda t: page.locator(f"[role='menuitem']:has-text('{t}')"),
            lambda t: page.locator(f"button:has-text('{t}')"),
            lambda t: page.locator(f"div:has-text('{t}')"),
            lambda t: page.get_by_text(t, exact=False),
        ):
            try:
                loc = factory(label).first
                if await loc.is_visible(timeout=600):
                    await loc.click(timeout=5000)
                    await page.wait_for_timeout(500)
                    return True
            except Exception:
                continue
    return False


async def _ensure_gpt_image_2(page: Any, *, on_status: StatusCb = None) -> None:
    """Genspark 이미지 생성 모델을 GPT Image 2 로 맞춥니다."""
    if await _gpt_image_2_selected(page):
        return
    _emit(on_status, "이미지 모델 GPT Image 2 선택…")
    if await _click_gpt_image_2_option(page):
        if await _gpt_image_2_selected(page):
            return
    if await _open_model_picker(page):
        if await _click_gpt_image_2_option(page):
            if await _gpt_image_2_selected(page):
                return
    _emit(on_status, "GPT Image 2 자동 선택 실패 — 화면에서 모델을 GPT Image 2로 바꿔 주세요.")
    raise RuntimeError(
        "이미지 모델이 GPT Image 2로 선택되지 않았습니다.\n\n"
        "Genspark 화면에서 모델을 GPT Image 2로 바꾼 뒤 다시 시도하세요."
    )


async def _connect_cdp_context(playwright: Any, *, on_status: StatusCb = None) -> Any:
    """열린 Chrome(CDP)에 연결합니다."""
    for port in CDP_PORTS:
        try:
            browser = await playwright.chromium.connect_over_cdp(
                f"http://127.0.0.1:{port}"
            )
            if browser.contexts:
                _emit(on_status, "열린 Chrome에 연결…")
                return browser.contexts[0]
        except Exception:
            continue
    return None


async def _launch_context(
    playwright: Any,
    *,
    png_dir: Path,
    on_status: StatusCb = None,
) -> Any:
    """Genspark 전용 Chrome(CDP)에 연결합니다."""
    context = await _connect_cdp_context(playwright, on_status=on_status)
    if context is not None:
        return context

    _emit(on_status, "Genspark 전용 Chrome 시작…")
    try:
        await asyncio.to_thread(
            ensure_chrome_cdp,
            png_dir=png_dir,
            url=GENSPARK_URL,
        )
    except Exception as ex:
        raise RuntimeError(
            "Genspark 전용 Chrome을 준비하지 못했습니다.\n\n"
            f"{ex}\n\n"
            "「브라우저 열기」로 Genspark 창을 연 뒤 다시 시도하세요."
        ) from ex

    for _ in range(40):
        await asyncio.sleep(0.5)
        context = await _connect_cdp_context(playwright, on_status=on_status)
        if context is not None:
            return context

    raise RuntimeError(
        "자동화 Chrome에 연결하지 못했습니다.\n\n"
        "① 기본 Chrome에서 Genspark에 로그인되어 있는지 확인\n"
        "② 「자동 생성·다운로드」를 다시 시도하세요\n"
        "(기본 Chrome 쿠키를 자동화 창으로 복사합니다)"
    )


async def _sync_login_from_default_chrome(
    context: Any,
    page: Any,
    *,
    on_status: StatusCb = None,
) -> bool:
    """기본 Chrome(로그인된 창) 쿠키를 자동화 Chrome 에 복사합니다."""
    from prompt2image.genspark_cookies import load_genspark_cookies

    cookies = load_genspark_cookies()
    if not cookies:
        return False
    _emit(on_status, "기본 Chrome 로그인 쿠키 복사…")
    try:
        await page.goto(
            "https://www.genspark.ai/",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        await context.add_cookies(cookies)
        return True
    except Exception:
        return False


async def _find_genspark_ai_image_page(
    context: Any,
    *,
    on_status: StatusCb = None,
) -> Any:
    """CDP Chrome 에서 ai_image 탭을 찾거나 엽니다."""
    for page in context.pages:
        url = (page.url or "").lower()
        if "genspark.ai" in url and "ai_image" in url:
            _emit(on_status, "열린 Genspark ai_image 탭 사용…")
            return page
    for page in context.pages:
        url = (page.url or "").lower()
        if "genspark.ai" in url:
            await page.goto(GENSPARK_URL, wait_until="load", timeout=90_000)
            return page
    page = context.pages[0] if context.pages else await context.new_page()
    await _sync_login_from_default_chrome(context, page, on_status=on_status)
    await page.goto(GENSPARK_URL, wait_until="load", timeout=90_000)
    url = (page.url or "").lower()
    if _looks_like_login_url(url):
        await _sync_login_from_default_chrome(context, page, on_status=on_status)
        await page.goto(GENSPARK_URL, wait_until="load", timeout=90_000)
    return page


async def _click_generate(page: Any) -> None:
    from prompt2image.genspark_selectors import GENERATE_BUTTONS

    for sel in GENERATE_BUTTONS:
        btn = page.locator(sel).first
        try:
            if await btn.is_visible(timeout=1500):
                await btn.click(timeout=5000)
                return
        except Exception:
            continue
    # Enter 로 전송 시도
    await page.keyboard.press("Enter")


async def _count_result_images(page: Any) -> int:
    from prompt2image.genspark_selectors import RESULT_IMAGES

    best = 0
    for sel in RESULT_IMAGES:
        try:
            c = await page.locator(sel).count()
            best = max(best, c)
        except Exception:
            continue
    return best


async def _wait_new_image(page: Any, before: int, timeout_ms: int) -> None:
    deadline = time.monotonic() + timeout_ms / 1000.0
    while time.monotonic() < deadline:
        now = await _count_result_images(page)
        if now > before:
            return
        await asyncio.sleep(0.8)
    raise TimeoutError("이미지 생성 대기 시간이 초과되었습니다.")


async def _safe_click(loc: Any, *, timeout: int = 8000) -> None:
    await _safe_scroll(loc)
    try:
        await loc.click(timeout=timeout)
    except Exception:
        await loc.click(timeout=timeout, force=True)


async def _click_latest_result_image(page: Any) -> None:
    from prompt2image.genspark_selectors import RESULT_IMAGES

    best_sel = None
    best_n = 0
    for sel in RESULT_IMAGES:
        try:
            n = await page.locator(sel).count()
            if n > best_n:
                best_n = n
                best_sel = sel
        except Exception:
            continue
    if not best_sel or best_n == 0:
        raise RuntimeError("생성된 이미지를 찾지 못했습니다.")
    target = page.locator(best_sel).nth(best_n - 1)
    await _safe_click(target)


async def _click_download_in_ui(page: Any) -> None:
    from prompt2image.genspark_selectors import DOWNLOAD_BUTTONS

    for sel in DOWNLOAD_BUTTONS:
        btn = page.locator(sel).first
        try:
            if await btn.is_visible(timeout=2000):
                await btn.click(timeout=5000)
                return
        except Exception:
            continue
    raise RuntimeError("다운로드 버튼을 찾지 못했습니다. 화면에서 직접 눌러 주세요.")


async def _save_via_network_fallback(
    page: Any,
    dest: Path,
    *,
    timeout_ms: int,
    min_bytes: int = 40_000,
) -> bool:
    """클릭 다운로드 실패 시 큰 이미지 응답 URL 로 저장."""
    deadline = time.monotonic() + timeout_ms / 1000.0
    candidates: list[str] = []

    async def _download_bytes_via_browser(url: str) -> bytes | None:
        """
        Node(APIRequestContext) 쪽 TLS 검증이 막히는 환경(사내 프록시 self-signed 등)에서,
        브라우저가 신뢰하는 인증서 체인을 사용해 바이트를 가져옵니다.
        """
        tmp = None
        try:
            tmp = await page.context.new_page()
            await tmp.goto(url, wait_until="domcontentloaded", timeout=45_000)
            # same-origin(fetch location.href) 로 CORS를 피하고 응답 바이트 확보
            data_url = await tmp.evaluate(
                """async () => {
                  const r = await fetch(location.href, { credentials: "include" });
                  if (!r.ok) return null;
                  const buf = await r.arrayBuffer();
                  let bin = "";
                  const bytes = new Uint8Array(buf);
                  const chunk = 0x8000;
                  for (let i = 0; i < bytes.length; i += chunk) {
                    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
                  }
                  return "data:application/octet-stream;base64," + btoa(bin);
                }"""
            )
            if not data_url or not isinstance(data_url, str) or "base64," not in data_url:
                return None
            b64 = data_url.split("base64,", 1)[1]
            return base64.b64decode(b64)
        except Exception:
            return None
        finally:
            try:
                if tmp is not None:
                    await tmp.close()
            except Exception:
                pass

    def on_response(resp: Any) -> None:
        try:
            ct = (resp.headers.get("content-type") or "").lower()
            if "image" not in ct:
                return
            url = resp.url
            if not url or url.startswith("data:"):
                return
            if any(x in url.lower() for x in (".svg", "favicon", "logo", "icon")):
                return
            candidates.append(url)
        except Exception:
            pass

    page.on("response", on_response)
    try:
        while time.monotonic() < deadline:
            if candidates:
                url = candidates[-1]
                body: bytes | None = None
                try:
                    resp = await page.request.get(url)
                    body = await resp.body()
                except Exception:
                    # 사내 프록시/보안SW 환경에서 APIRequestContext(TLS)가 막히는 경우 브라우저로 우회
                    body = await _download_bytes_via_browser(url)

                if body and len(body) >= min_bytes:
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(body)
                    return True
            await asyncio.sleep(0.5)
    finally:
        try:
            page.remove_listener("response", on_response)
        except Exception:
            pass
    return False


async def automate_genspark_download(
    *,
    guide: str,
    srt_text: str,
    png_dir: Path,
    target_number: int,
    timeout_ms: int = 180_000,
    on_status: StatusCb = None,
    prompt_selector: str | None = None,
) -> Path:
    """
    Genspark 에 지침·대본 입력 → 생성 대기 → 이미지 클릭 → 확대 화면 다운로드.
    저장 경로: ``png_dir / SRT_XXX.png``
    """
    ensure_playwright()
    from playwright.async_api import async_playwright

    guide = (guide or "").strip()
    srt_text = (srt_text or "").strip()
    if not srt_text:
        raise ValueError("SRT 대본 내용이 비어 있습니다.")
    if guide.startswith("(") and "찾을 수 없" in guide:
        guide = ""

    png_dir.mkdir(parents=True, exist_ok=True)
    dest = png_dir / format_srt_filename(target_number)
    if dest.exists():
        dest.unlink()

    prompt_body = srt_text
    figure_hint = build_public_figure_hint(srt_text)
    if guide:
        parts = [f"[시스템 지침]\n{guide}"]
        if figure_hint:
            parts.append(figure_hint)
        parts.append(
            f"[이번에 생성할 SRT 대본]\n{srt_text}\n\n"
            "위 대본에 맞는 이미지 1장을 생성하세요. "
            f"파일명은 {format_srt_filename(target_number)} 를 참고하세요."
        )
        if figure_hint:
            parts.append(
                "★ §7-2 필수 실존 인물: 위 [필수 실존 인물]에 해당하면 "
                "반드시 해당 공인의 뉴스 실사를 중심 피사체로 포함하세요. "
                "건물·연단만으로 대체하지 마세요."
            )
        prompt_body = "\n\n".join(parts)
    elif figure_hint:
        prompt_body = (
            f"{figure_hint}\n\n"
            f"[이번에 생성할 SRT 대본]\n{srt_text}\n\n"
            "위 대본에 맞는 이미지 1장을 생성하세요. "
            f"파일명은 {format_srt_filename(target_number)} 를 참고하세요."
        )

    async with async_playwright() as p:
        context = await _launch_context(p, png_dir=png_dir, on_status=on_status)
        page = await _find_genspark_ai_image_page(context, on_status=on_status)
        try:
            await page.wait_for_load_state("networkidle", timeout=15_000)
        except Exception:
            pass

        await _ensure_gpt_image_2(page, on_status=on_status)

        before_imgs = await _count_result_images(page)

        _emit(
            on_status,
            "지침·대본 입력… (열린 Chrome · GPT Image 2)",
        )
        if not await _wait_and_fill_prompt(
            page,
            prompt_body,
            wait_ms=90_000,
            on_status=on_status,
            custom_selector=prompt_selector,
        ):
            url = page.url or ""
            if _looks_like_login_url(url):
                raise RuntimeError(
                    "Genspark 로그인이 필요합니다.\n\n"
                    "열린 Chrome에서 Genspark에 로그인한 뒤 다시 시도하세요."
                )
            raise RuntimeError(
                "Genspark 입력란을 찾지 못했습니다.\n\n"
                "ai_image 페이지가 완전히 로드됐는지 확인하고, "
                "모델이 GPT Image 2 인지 확인한 뒤\n"
                "「브라우저에서 입력란 지정」으로 프롬프트 입력칸을 직접 지정해 주세요."
            )

        _emit(on_status, "이미지 생성 요청…")
        await _click_generate(page)

        _emit(on_status, "이미지 생성 대기…")
        gen_timeout = max(60_000, timeout_ms - 60_000)
        await _wait_new_image(page, before_imgs, gen_timeout)
        await page.wait_for_timeout(800)

        _emit(on_status, "이미지 클릭 → 확대…")
        await _click_latest_result_image(page)
        await page.wait_for_timeout(1200)

        saved = False
        _emit(on_status, "다운로드…")
        try:
            async with page.expect_download(timeout=45_000) as dl_info:
                await _click_download_in_ui(page)
            download = await dl_info.value
            await download.save_as(dest)
            saved = dest.is_file()
        except Exception:
            pass

        if not saved:
            _emit(on_status, "다운로드 버튼 재시도·URL 저장…")
            try:
                async with page.expect_download(timeout=30_000) as dl_info:
                    await page.keyboard.press("Escape")
                    await page.wait_for_timeout(400)
                    await _click_latest_result_image(page)
                    await page.wait_for_timeout(800)
                    await _click_download_in_ui(page)
                download = await dl_info.value
                await download.save_as(dest)
                saved = dest.is_file()
            except Exception:
                pass

        if not saved:
            saved = await _save_via_network_fallback(
                page, dest, timeout_ms=30_000
            )

        if not saved or not dest.is_file():
            raise RuntimeError(
                "이미지를 자동으로 저장하지 못했습니다. "
                "브라우저에서 확대 후 다운로드를 직접 눌러 주세요."
            )

        _emit(on_status, f"저장 완료: {dest.name}")
        return dest


def run_genspark_automation_sync(
    *,
    guide: str,
    srt_text: str,
    png_dir: Path,
    target_number: int,
    timeout_ms: int = 180_000,
    on_status: StatusCb = None,
    prompt_selector: str | None = None,
) -> Path:
    """Tkinter 스레드용 동기 래퍼."""
    return asyncio.run(
        automate_genspark_download(
            guide=guide,
            srt_text=srt_text,
            png_dir=png_dir,
            target_number=target_number,
            timeout_ms=timeout_ms,
            on_status=on_status,
            prompt_selector=prompt_selector,
        )
    )


def run_pick_prompt_selector_sync(
    *,
    png_dir: Path,
    on_status: StatusCb = None,
) -> str:
    """Tkinter 스레드용 — Genspark 입력란 클릭 지정."""
    return asyncio.run(
        pick_genspark_prompt_selector(png_dir=png_dir, on_status=on_status)
    )
