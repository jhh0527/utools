# -*- coding: utf-8 -*-
"""Genspark AI 이미지 생성 — Chrome 열기·첨부·전송·이미지 URL 수집 (Playwright)."""

from __future__ import annotations

import asyncio
import os
import queue
import re
import subprocess
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from img_down.paths import FIXED_PROMPT
from img_down.srt_chunks import extract_srt_labels
from img_down.url_filter import is_collectable_image_url, is_tracking_url

# AI 이미지 생성 기본 URL (설정에서 변경 가능)
GENSPARK_IMAGE_URL = "https://www.genspark.ai/tools/ai-image-generator"
GENSPARK_GPT_IMAGE_2_URL = "https://www.genspark.ai/tools/gpt-image-2"
_GPT_IMAGE_2_TEXTS = (
    "GPT Image 2",
    "GPT image 2",
    "GPT Image2",
    "gpt-image-2",
)
_PROFILE_DIRNAME = ".genspark_image_profile"
_CDP_PORTS = (9222, 9223)

StatusCb = Callable[[str], None] | None
_SRT_LABEL_RE = re.compile(r"SRT[_\s-]?(\d{1,6})", re.IGNORECASE)


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


def image_profile_dir(base_dir: Path) -> Path:
    return base_dir / _PROFILE_DIRNAME


def open_genspark_image_in_chrome(
    url: str = GENSPARK_IMAGE_URL,
    *,
    profile_dir: Path | None = None,
    debug_port: int = _CDP_PORTS[0],
) -> None:
    """일반 Chrome으로 Genspark를 엽니다 (구글 수동 인증용)."""
    chrome = find_chrome_exe()
    if chrome is None:
        raise RuntimeError(
            "Google Chrome을 찾을 수 없습니다.\nChrome 설치 후 다시 시도하세요."
        )
    args: list[str] = [str(chrome)]
    if profile_dir is not None:
        profile_dir.mkdir(parents=True, exist_ok=True)
        args.append(f"--user-data-dir={profile_dir.resolve()}")
        args.append(f"--remote-debugging-port={debug_port}")
    args.append(url)
    kwargs: dict = {
        "args": args,
        "close_fds": True,
    }
    if sys.platform == "win32":
        kwargs["creationflags"] = (
            subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        )
    subprocess.Popen(**kwargs)


def open_browser_for_manual_login(url: str, profile_dir: Path) -> None:
    """Playwright 세션을 끊고 일반 Chrome으로 열어 구글 인증을 수동 입력합니다."""
    reset_image_session()
    open_genspark_image_in_chrome(
        url,
        profile_dir=profile_dir,
        debug_port=_CDP_PORTS[0],
    )


def has_playwright() -> bool:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return False
    return True


def _emit(on_status: StatusCb, msg: str) -> None:
    if on_status:
        on_status(msg)


def preferred_genspark_url(user_url: str = "") -> str:
    """GPT Image 2 전용 도구 URL 우선, 없으면 사용자·기본 URL."""
    u = (user_url or "").strip()
    if u:
        low = u.lower()
        if "gpt-image-2" in low or "gpt_image_2" in low:
            return u
    return GENSPARK_GPT_IMAGE_2_URL


def fallback_genspark_url(user_url: str = "") -> str:
    u = (user_url or "").strip()
    return u or GENSPARK_IMAGE_URL


async def _page_has_gpt_image_2(page: Any) -> bool:
    url = (page.url or "").lower()
    if "gpt-image-2" in url or "gpt_image_2" in url:
        return True
    try:
        found = await page.evaluate(
            """() => {
              const t = (document.body && document.body.innerText) || '';
              return /GPT\\s*Image\\s*2/i.test(t.slice(0, 4000));
            }"""
        )
        return bool(found)
    except Exception:
        return False


async def _click_by_text(page: Any, texts: tuple[str, ...]) -> bool:
    for text in texts:
        for sel in (
            f"button:has-text('{text}')",
            f"[role='option']:has-text('{text}')",
            f"[role='menuitem']:has-text('{text}')",
            f"li:has-text('{text}')",
            f"div:has-text('{text}')",
            f"span:has-text('{text}')",
        ):
            loc = page.locator(sel).first
            try:
                if await loc.is_visible(timeout=800):
                    await loc.click(timeout=4000)
                    await page.wait_for_timeout(600)
                    return True
            except Exception:
                continue
    return False


async def _select_gpt_image_2_model(
    page: Any, *, custom_selector: str = ""
) -> bool:
    """명령어 입력란·도구에서 GPT Image 2 모델 선택 시도. 성공 여부 반환."""
    if await _page_has_gpt_image_2(page):
        return True
    if custom_selector.strip():
        loc = page.locator(custom_selector.strip()).first
        try:
            if await loc.is_visible(timeout=1500):
                await loc.click(timeout=4000)
                await page.wait_for_timeout(400)
                picked = await _click_by_text(page, _GPT_IMAGE_2_TEXTS)
                if picked or await _page_has_gpt_image_2(page):
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
            if await _click_by_text(page, _GPT_IMAGE_2_TEXTS):
                return True
        except Exception:
            continue
    if await _click_by_text(page, _GPT_IMAGE_2_TEXTS):
        return True
    return await _page_has_gpt_image_2(page)


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


async def _attach_file(page: Any, path: Path) -> bool:
    if not path.is_file():
        return False
    # 파일 input이 숨겨져 있어도 set_input_files 가능
    for sel in ("input[type='file']", "input[type=file]"):
        loc = page.locator(sel)
        try:
            n = await loc.count()
        except Exception:
            continue
        for i in range(min(n, 6)):
            try:
                await loc.nth(i).set_input_files(str(path.resolve()))
                await page.wait_for_timeout(800)
                return True
            except Exception:
                continue
    # 첨부 버튼 클릭 후 다시 시도
    for sel in (
        "button:has-text('Attach')",
        "button:has-text('첨부')",
        "button:has-text('Upload')",
        "button:has-text('파일')",
        "[aria-label*='Attach' i]",
        "[aria-label*='upload' i]",
        "[aria-label*='첨부' i]",
    ):
        btn = page.locator(sel).first
        try:
            if await btn.is_visible(timeout=1200):
                await btn.click(timeout=3000)
                await page.wait_for_timeout(500)
        except Exception:
            continue
    loc = page.locator("input[type='file']")
    try:
        n = await loc.count()
        for i in range(min(n, 6)):
            try:
                await loc.nth(i).set_input_files(str(path.resolve()))
                await page.wait_for_timeout(800)
                return True
            except Exception:
                continue
    except Exception:
        pass
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
    """페이지에서 (SRT초|None, 이미지URL) 목록 수집."""
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
            if (/\\.(png|jpe?g|webp|gif|avif)(\\?|$|#)/i.test(url)) return true;
            try {
              const host = new URL(url).hostname.toLowerCase();
              return goodHostParts.some(p => host.includes(p));
            } catch (e) { return false; }
          };
          const push = (url, label, w, h) => {
            if (!url || seen.has(url) || isSkip(url)) return;
            if (!looksImage(url) && (w < 256 || h < 256)) return;
            if (!url.startsWith('blob:') && (!w || !h) && !looksImage(url)) return;
            seen.add(url);
            out.push({url, label: label || '', w, h});
          };
          const imgs = Array.from(document.querySelectorAll('img'));
          for (const img of imgs) {
            const w = img.naturalWidth || img.width || 0;
            const h = img.naturalHeight || img.height || 0;
            const src = img.currentSrc || img.src || '';
            let label = '';
            const near = (img.closest('figure,article,div,li,section') || img.parentElement);
            if (near) label = (near.innerText || '').slice(0, 800);
            const alt = img.alt || '';
            push(src, (label + ' ' + alt).trim(), w, h);
            const ds = img.getAttribute('data-src') || img.getAttribute('data-original') || '';
            if (ds) push(ds, label, w, h);
          }
          for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href || '';
            if (!looksImage(href) && !/download/i.test(href)) continue;
            const t = ((a.innerText || '') + ' ' + (a.getAttribute('download') || '')).trim();
            push(href, t, 0, 0);
          }
          for (const el of document.querySelectorAll('[style*="background"]')) {
            const st = el.style && el.style.backgroundImage || '';
            const m = st.match(/url\\(["']?([^"')]+)["']?\\)/i);
            if (m && m[1]) push(m[1], (el.innerText || '').slice(0, 400), 0, 0);
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
        secs = extract_srt_labels(label)
        sec = secs[0] if secs else None
        if sec is None:
            m = _SRT_LABEL_RE.search(url)
            if m:
                sec = int(m.group(1))
        items.append((sec, url))
    return items


async def _collect_page_images(page: Any) -> list[tuple[str, str | None]]:
    """현재 페이지의 이미지 URL과 파일명 힌트 목록 수집."""
    try:
        await page.evaluate(
            """async () => {
              const sleep = (ms) => new Promise(r => setTimeout(r, ms));
              const maxY = document.body && document.body.scrollHeight || 0;
              const step = Math.max(600, Math.floor(window.innerHeight * 0.8));
              for (let y = 0; y <= maxY; y += step) {
                window.scrollTo(0, y);
                await sleep(120);
              }
              window.scrollTo(0, Math.max(0, maxY - step));
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
          const isSkip = (url) => {
            if (!url) return true;
            const u = url.toLowerCase();
            if (u.startsWith('data:')) return true;
            if (u.includes('/action/0?') && u.includes('bing')) return true;
            return skipParts.some(p => u.includes(p));
          };
          const push = (url, name, w, h) => {
            if (!url || seen.has(url) || isSkip(url)) return;
            if (!url.startsWith('blob:') && !/^https?:/i.test(url)) return;
            seen.add(url);
            out.push({url, name: name || '', w: w || 0, h: h || 0});
          };
          const fileish = (s) => /\\.(png|jpe?g|webp|gif|bmp|avif)(\\?|$|#)/i.test(s || '');
          for (const img of document.querySelectorAll('img')) {
            const w = img.naturalWidth || img.width || 0;
            const h = img.naturalHeight || img.height || 0;
            if (w && h && (w < 128 || h < 128)) continue;
            const src = img.currentSrc || img.src || img.getAttribute('data-src') || '';
            const hint =
              img.getAttribute('download') ||
              img.getAttribute('data-filename') ||
              img.getAttribute('data-file-name') ||
              img.getAttribute('data-name') ||
              (fileish(img.alt) ? img.alt : '') ||
              (fileish(img.title) ? img.title : '');
            push(src, hint, w, h);
          }
          for (const a of document.querySelectorAll('a[href]')) {
            const href = a.href || '';
            const download = a.getAttribute('download') || '';
            if (!download && !fileish(href)) continue;
            push(href, download || (a.textContent || '').trim(), 0, 0);
          }
          for (const el of document.querySelectorAll('[style*="background"]')) {
            const st = el.style && el.style.backgroundImage || '';
            const m = st.match(/url\\(["']?([^"')]+)["']?\\)/i);
            if (m && m[1]) push(m[1], el.getAttribute('data-filename') || '', 0, 0);
          }
          return out;
        }"""
    )
    items: list[tuple[str, str | None]] = []
    for row in raw or []:
        if not isinstance(row, dict):
            continue
        url = str(row.get("url") or "").strip()
        hint = str(row.get("name") or "").strip() or None
        w = int(row.get("w") or 0)
        h = int(row.get("h") or 0)
        if is_tracking_url(url):
            continue
        if not url.startswith("blob:") and not is_collectable_image_url(
            url, width=w, height=h
        ):
            continue
        items.append((url, hint))
    return items


async def _launch_context(playwright: Any, profile_dir: Path) -> Any:
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
    profile_dir.mkdir(parents=True, exist_ok=True)
    return await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir.resolve()),
        channel="chrome",
        headless=False,
        locale="ko-KR",
        accept_downloads=True,
        args=["--disable-blink-features=AutomationControlled"],
    )


class GensparkImageSession:
    """Playwright 세션 — 같은 창에서 청크 전송·이미지 수집."""

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

    def open_page(self, url: str) -> None:
        self._call("open", url)

    def run_chunk(
        self,
        *,
        url: str,
        guide_path: Path | None,
        chunk_text: str,
        prompt: str = FIXED_PROMPT,
        attach_guide: bool = True,
        try_model_select: bool = False,
        model_selector: str = "",
    ) -> dict[str, bool]:
        return self._call(
            "run_chunk",
            {
                "url": url,
                "guide": str(guide_path) if guide_path else "",
                "chunk": chunk_text,
                "prompt": prompt,
                "attach": attach_guide,
                "try_model": try_model_select,
                "model_selector": model_selector,
            },
            timeout=240.0,
        )

    def start_generation(
        self,
        *,
        user_url: str,
        guide_path: Path | None,
        chunk_text: str,
        prompt: str = FIXED_PROMPT,
        attach_guide: bool = True,
        model_selector: str = "",
    ) -> dict[str, bool]:
        """GPT Image 2 URL·모델 선택 시도 후 지침·청크 전송."""
        primary = preferred_genspark_url(user_url)
        result = self.run_chunk(
            url=primary,
            guide_path=guide_path,
            chunk_text=chunk_text,
            prompt=prompt,
            attach_guide=attach_guide,
            try_model_select=True,
            model_selector=model_selector,
        )
        if isinstance(result, dict) and result.get("model_auto"):
            return result
        fallback = fallback_genspark_url(user_url)
        if fallback != primary:
            result = self.run_chunk(
                url=fallback,
                guide_path=guide_path,
                chunk_text=chunk_text,
                prompt=prompt,
                attach_guide=attach_guide,
                try_model_select=True,
                model_selector=model_selector,
            )
        return result if isinstance(result, dict) else {"model_auto": False}

    def collect_images(self, *, wait_ms: int = 2000) -> list[tuple[int | None, str]]:
        return self._call("collect", wait_ms, timeout=120.0)

    def collect_page_images(
        self, *, url: str, wait_ms: int = 3000
    ) -> list[tuple[str, str | None]]:
        return self._call(
            "collect_page",
            {"url": url, "wait_ms": wait_ms},
            timeout=180.0,
        )

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

    def download_named_via_page(
        self,
        items: list[tuple[str, str | None]],
        png_dir: Path,
    ) -> list[str]:
        return self._call(
            "download_named",
            {"items": items, "png_dir": str(png_dir)},
            timeout=300.0,
        )

    async def _async_worker(self) -> None:
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            context = await _launch_context(pw, self._profile_dir)
            page = context.pages[0] if context.pages else await context.new_page()
            guide_attached = False
            model_ready = False

            while True:
                try:
                    op, arg, resp_q = self._cmd_q.get_nowait()
                except queue.Empty:
                    await asyncio.sleep(0.15)
                    continue
                try:
                    if op == "open":
                        await page.goto(
                            str(arg),
                            wait_until="domcontentloaded",
                            timeout=90_000,
                        )
                        await page.wait_for_timeout(1500)
                        resp_q.put((True, None, None))
                    elif op == "run_chunk":
                        data = arg or {}
                        url = data.get("url") or GENSPARK_IMAGE_URL
                        need_nav = "genspark.ai" not in (page.url or "")
                        if need_nav or url not in (page.url or ""):
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                            await page.wait_for_timeout(1500)
                            model_ready = False
                        model_auto = model_ready
                        if data.get("try_model") and not model_ready:
                            model_auto = await _select_gpt_image_2_model(
                                page,
                                custom_selector=str(
                                    data.get("model_selector") or ""
                                ),
                            )
                            model_ready = model_auto
                        guide = data.get("guide") or ""
                        if data.get("attach") and guide and not guide_attached:
                            ok = await _attach_file(page, Path(guide))
                            if ok:
                                guide_attached = True
                        chunk = (data.get("chunk") or "").strip()
                        prompt = (data.get("prompt") or FIXED_PROMPT).strip()
                        body = f"{prompt}\n\n===== SRT 대본 =====\n{chunk}"
                        if not await _fill_first_editable(page, body):
                            raise RuntimeError(
                                "명령어 입력란을 찾지 못했습니다. "
                                "로그인·페이지 로드 후 다시 시도하세요."
                            )
                        await _submit(page)
                        await page.wait_for_timeout(1200)
                        resp_q.put((True, {"model_auto": bool(model_auto)}, None))
                    elif op == "collect":
                        wait_ms = int(arg or 2000)
                        await page.wait_for_timeout(max(0, wait_ms))
                        items = await _collect_images(page)
                        resp_q.put((True, items, None))
                    elif op == "collect_page":
                        data = arg or {}
                        url = str(data.get("url") or "").strip()
                        if url and url != (page.url or ""):
                            await page.goto(
                                url,
                                wait_until="domcontentloaded",
                                timeout=90_000,
                            )
                        wait_ms = int(data.get("wait_ms") or 3000)
                        await page.wait_for_timeout(max(0, wait_ms))
                        items = await _collect_page_images(page)
                        resp_q.put((True, items, None))
                    elif op == "download":
                        data = arg or {}
                        png_dir = Path(data.get("png_dir") or ".")
                        png_dir.mkdir(parents=True, exist_ok=True)
                        from img_down.download import assign_srt_secs, download_url
                        from img_down.srt_chunks import srt_png_name

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
                                      for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
                                      return btoa(s);
                                    }""",
                                    url,
                                )
                                import base64

                                dest.write_bytes(base64.b64decode(b64))
                            else:
                                download_url(url, dest)
                            saved.append(str(dest))
                        resp_q.put((True, saved, None))
                    elif op == "download_named":
                        data = arg or {}
                        png_dir = Path(data.get("png_dir") or ".")
                        png_dir.mkdir(parents=True, exist_ok=True)
                        from img_down.download import (
                            sanitize_filename,
                            save_named_images,
                            unique_path,
                        )

                        items = list(data.get("items") or [])
                        normal_items: list[tuple[str, str | None]] = []
                        saved: list[str] = []
                        for i, row in enumerate(items, start=1):
                            url = str((row or ["", ""])[0] or "").strip()
                            hint = str((row or ["", ""])[1] or "").strip() or None
                            if not url:
                                continue
                            if not url.startswith("blob:"):
                                normal_items.append((url, hint))
                                continue
                            name = sanitize_filename(
                                hint or "", fallback=f"image_{i:03d}.png"
                            )
                            dest = unique_path(png_dir / name)
                            b64 = await page.evaluate(
                                """async (u) => {
                                  const r = await fetch(u);
                                  const buf = await r.arrayBuffer();
                                  const bytes = new Uint8Array(buf);
                                  let s = '';
                                  for (let i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
                                  return btoa(s);
                                }""",
                                url,
                            )
                            import base64

                            dest.write_bytes(base64.b64decode(b64))
                            saved.append(str(dest))
                        saved.extend(str(p) for p in save_named_images(normal_items, png_dir))
                        resp_q.put((True, saved, None))
                    elif op == "stop":
                        resp_q.put((True, None, None))
                        break
                    else:
                        resp_q.put((False, None, RuntimeError(f"알 수 없는 명령: {op}")))
                except Exception as ex:
                    resp_q.put((False, None, ex))


_session: GensparkImageSession | None = None
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


def get_image_session(profile_dir: Path) -> GensparkImageSession:
    global _session
    with _session_lock:
        if _session is None:
            _session = GensparkImageSession(profile_dir)
        return _session


def build_submit_text(chunk_text: str, *, prompt: str = FIXED_PROMPT) -> str:
    return f"{prompt}\n\n===== SRT 대본 =====\n{chunk_text.strip()}"
