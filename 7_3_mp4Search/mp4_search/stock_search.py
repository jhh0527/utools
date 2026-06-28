# -*- coding: utf-8 -*-
"""Pexels·Pixabay·Mixkit 무료 스톡 영상 검색."""

from __future__ import annotations

import concurrent.futures
import json
import os
import re
import threading
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from mp4_search.paths import stock_api_config_candidates, stock_api_config_write_path
from mp4_search.translate_util import compact_search_query, search_query_from_cue

_ITEM_LINK = re.compile(
    r'href="(/free-stock-video/[a-z0-9-]+-(\d+)/)"[^>]*>\s*([^<]+?)\s*</a>',
    re.IGNORECASE,
)
_MP4_ACTIVE = re.compile(
    r"https://assets\.mixkit\.co/active_storage/video_items/\d+/\d+/(\d+)-video-(\d+)\.mp4"
)
_MP4_LEGACY = re.compile(
    r"https://assets\.mixkit\.co/videos/(\d+)/\1-(360|480|720)\.mp4"
)
_QUERY_STOP = frozenset(
    """
    a an the and or of on in at to for with from is are was were be been being
    this that these those it its as by into through over under about up down out
    off not no nor so if but than then also very just only even still already
    there their they them we you your our can could would should will shall may
    might must do does did done have has had having am i me my he she his her
    what when where which who whom how why all each every both few more most some
    such other another one two three first last new old same than too top view
    video videos clip clips footage scene scenes background free stock
    """.split()
)


@dataclass(frozen=True)
class StockVideo:
    provider: str
    video_id: str
    title: str
    thumbnail_url: str
    download_url: str
    duration: int
    width: int
    page_url: str


def query_keywords(query: str, *, min_len: int = 3) -> list[str]:
    words = re.findall(r"[a-z0-9]+", (query or "").lower())
    out: list[str] = []
    for w in words:
        if len(w) < min_len or w in _QUERY_STOP:
            continue
        if w not in out:
            out.append(w)
    return out


def normalize_search_query(query: str) -> str:
    q = " ".join((query or "").split())
    if not q:
        return ""
    compact = compact_search_query(q, max_words=4)
    return compact or q


def _token_match(keyword: str, token: str) -> bool:
    if keyword == token:
        return True
    if len(keyword) >= 4 and token.startswith(keyword):
        return True
    if len(token) >= 4 and keyword.startswith(token):
        return True
    return False


def _keyword_in_text(keyword: str, text: str) -> bool:
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    return any(_token_match(keyword, t) for t in tokens)


def video_relevance(video: StockVideo, keywords: list[str]) -> int:
    if not keywords:
        return 1
    hay = f"{video.title} {video.page_url}".lower()
    hits = 0
    score = 0
    for k in keywords:
        if _keyword_in_text(k, hay):
            hits += 1
            score += len(k)
    if hits == 0:
        return 0
    return score + hits * 5


def video_cache_key(video: StockVideo) -> str:
    return f"{video.provider}:{video.video_id}"


def rank_videos(videos: list[StockVideo], query: str) -> list[StockVideo]:
    keywords = query_keywords(normalize_search_query(query))
    if not keywords:
        return videos
    scored: list[tuple[int, StockVideo]] = []
    for v in videos:
        s = video_relevance(v, keywords)
        if len(keywords) >= 2 and s > 0:
            hay = f"{v.title} {v.page_url}".lower()
            hit_n = sum(1 for k in keywords if _keyword_in_text(k, hay))
            if hit_n < 2:
                s = max(1, s // 3)
        scored.append((s, v))
    scored.sort(key=lambda x: (-x[0], x[1].provider))
    relevant = [v for s, v in scored if s > 0]
    return relevant if relevant else [v for _, v in scored]


def _merge_api_keys_from_file(path: Path, keys: dict[str, str]) -> None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    if not isinstance(data, dict):
        return
    for name in ("pexels_api_key", "pixabay_api_key", "coverr_api_key"):
        v = data.get(name)
        if isinstance(v, str) and v.strip() and name not in keys:
            keys[name] = v.strip()


def load_api_keys() -> dict[str, str]:
    keys: dict[str, str] = {}
    for env_key, name in (
        ("PEXELS_API_KEY", "pexels_api_key"),
        ("PIXABAY_API_KEY", "pixabay_api_key"),
        ("COVERR_API_KEY", "coverr_api_key"),
    ):
        v = os.environ.get(env_key, "").strip()
        if v:
            keys[name] = v
    for p in stock_api_config_candidates():
        if p.is_file() and p.name == "stock_api.json":
            _merge_api_keys_from_file(p, keys)
    if not any(keys.get(n) for n in ("pexels_api_key", "pixabay_api_key", "coverr_api_key")):
        for p in stock_api_config_candidates():
            if p.is_file() and p.name == "stock_api.example.json":
                _merge_api_keys_from_file(p, keys)
    return keys


def api_keys_status() -> tuple[list[str], Path, Path | None]:
    """(활성 제공자 라벨, 권장 저장 경로, 실제 로드된 파일)."""
    keys = load_api_keys()
    labels: list[str] = []
    if keys.get("pexels_api_key"):
        labels.append("Pexels")
    if keys.get("pixabay_api_key"):
        labels.append("Pixabay")
    if keys.get("coverr_api_key"):
        labels.append("Coverr")
    labels.append("Mixkit")
    loaded_from: Path | None = None
    for p in stock_api_config_candidates():
        if not p.is_file():
            continue
        probe: dict[str, str] = {}
        _merge_api_keys_from_file(p, probe)
        if probe:
            loaded_from = p
            if p.name == "stock_api.json":
                break
    return labels, stock_api_config_write_path(), loaded_from


def _http_json(url: str, *, headers: dict[str, str] | None = None, timeout: float = 30) -> dict:
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("API 응답 형식 오류")
    return data


def _http_text(url: str, *, timeout: float = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _mixkit_slugs(query: str) -> list[str]:
    words = query_keywords(normalize_search_query(query))
    if not words:
        words = [w for w in re.findall(r"[a-z0-9]+", (query or "").lower()) if len(w) >= 3 and w not in _QUERY_STOP]
    slugs: list[str] = []
    if len(words) >= 2:
        slugs.append("-".join(words[:2]))
        if len(words) >= 3:
            slugs.append("-".join(words[:3]))
    for w in sorted(set(words), key=len, reverse=True):
        slugs.append(w)
    out: list[str] = []
    for s in slugs:
        if s and s not in out:
            out.append(s)
    return out


def _best_mixkit_file(resolutions: dict[int, str]) -> tuple[str, int]:
    for prefer in (720, 480, 360):
        if prefer in resolutions:
            return resolutions[prefer], prefer
    best = max(resolutions)
    return resolutions[best], best


def _parse_mixkit_html(html: str, *, list_url: str) -> list[StockVideo]:
    titles: dict[str, tuple[str, str]] = {}
    for m in _ITEM_LINK.finditer(html):
        path, vid, title = m.group(1), m.group(2), m.group(3).strip()
        if title and len(title) > 2 and vid not in titles:
            titles[vid] = (title, f"https://mixkit.co{path}")

    active: dict[str, dict[int, str]] = {}
    for m in _MP4_ACTIVE.finditer(html):
        vid, res_s, url = m.group(1), int(m.group(2)), m.group(0)
        active.setdefault(vid, {})[res_s] = url

    legacy: dict[str, dict[int, str]] = {}
    for m in _MP4_LEGACY.finditer(html):
        vid, res_s, url = m.group(1), int(m.group(2)), m.group(0)
        legacy.setdefault(vid, {})[res_s] = url

    by_id: dict[str, StockVideo] = {}
    all_ids = set(active) | set(legacy) | set(titles)
    for vid in all_ids:
        if vid in by_id:
            continue
        files = {**legacy.get(vid, {}), **active.get(vid, {})}
        if not files:
            continue
        dl, res = _best_mixkit_file(files)
        if vid in active:
            base = dl.rsplit("-video-", 1)[0]
            thumb = f"{base}-video-thumb-{res}-0.jpg"
        else:
            thumb = f"https://assets.mixkit.co/videos/{vid}/{vid}-thumb-720-0.jpg"
        title, page = titles.get(vid, (f"Mixkit #{vid}", list_url))
        by_id[vid] = StockVideo(
            provider="mixkit",
            video_id=vid,
            title=title[:80],
            thumbnail_url=thumb,
            download_url=dl,
            duration=0,
            width=res,
            page_url=page,
        )

    return list(by_id.values())


def search_mixkit(query: str, *, per_page: int = 6) -> list[StockVideo]:
    """Mixkit 카테고리 slug 검색 (API 키 불필요). 관련 없는 목록은 제외."""
    keywords = query_keywords(normalize_search_query(query))
    merged: list[StockVideo] = []
    seen: set[str] = set()

    for slug in _mixkit_slugs(query):
        list_url = f"https://mixkit.co/free-stock-video/{urllib.parse.quote(slug)}/"
        try:
            html = _http_text(list_url, timeout=25)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                continue
            continue
        except (urllib.error.URLError, TimeoutError):
            continue

        items = _parse_mixkit_html(html, list_url=list_url)
        if keywords:
            items = [v for v in items if video_relevance(v, keywords) > 0]
        if not items:
            continue

        for v in items:
            key = v.download_url or f"mixkit:{v.video_id}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(v)

        ranked = rank_videos(merged, query)
        if len(ranked) >= per_page:
            return ranked[:per_page]

    return rank_videos(merged, query)[:per_page]


def search_coverr(query: str, *, api_key: str, per_page: int = 6) -> list[StockVideo]:
    q = urllib.parse.quote(normalize_search_query(query))
    if not q or not api_key:
        return []
    url = (
        f"https://api.coverr.co/videos?query={q}&page_size={per_page}"
        f"&urls=true&page=0"
    )
    data = _http_json(url, headers={"Authorization": f"Bearer {api_key}"})
    out: list[StockVideo] = []
    for hit in data.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        urls = hit.get("urls") if isinstance(hit.get("urls"), dict) else {}
        dl = str(urls.get("mp4") or urls.get("mp4_download") or "").strip()
        if not dl:
            continue
        title = str(hit.get("title") or hit.get("description") or f"Coverr #{hit.get('id', '')}")
        thumb = str(hit.get("thumbnail") or hit.get("poster") or urls.get("mp4_preview") or "")
        out.append(
            StockVideo(
                provider="coverr",
                video_id=str(hit.get("id") or ""),
                title=title[:80],
                thumbnail_url=thumb,
                download_url=dl,
                duration=int(hit.get("duration") or 0),
                width=int(hit.get("width") or 0),
                page_url=str(hit.get("url") or "https://coverr.co/"),
            )
        )
    return out


def search_pexels(query: str, *, api_key: str, per_page: int = 6) -> list[StockVideo]:
    q = urllib.parse.quote(normalize_search_query(query))
    if not q or not api_key:
        return []
    url = f"https://api.pexels.com/v1/videos/search?query={q}&per_page={per_page}&orientation=landscape"
    data = _http_json(url, headers={"Authorization": api_key})
    out: list[StockVideo] = []
    for v in data.get("videos") or []:
        if not isinstance(v, dict):
            continue
        files = v.get("video_files") or []
        best = None
        for f in files:
            if not isinstance(f, dict) or not f.get("link"):
                continue
            w = int(f.get("width") or 0)
            if best is None or w > int(best.get("width") or 0):
                best = f
        if not best:
            continue
        tags = " ".join(str(t) for t in (v.get("tags") or []) if t)
        title = tags.strip() or f"Pexels #{v.get('id', '')}"
        out.append(
            StockVideo(
                provider="pexels",
                video_id=str(v.get("id", "")),
                title=title[:80],
                thumbnail_url=str(v.get("image") or ""),
                download_url=str(best.get("link") or ""),
                duration=int(v.get("duration") or 0),
                width=int(best.get("width") or 0),
                page_url=str(v.get("url") or ""),
            )
        )
    return out


def search_pixabay(query: str, *, api_key: str, per_page: int = 6) -> list[StockVideo]:
    q = urllib.parse.quote(normalize_search_query(query))
    if not q or not api_key:
        return []
    url = (
        f"https://pixabay.com/api/videos/?key={urllib.parse.quote(api_key)}"
        f"&q={q}&per_page={per_page}&video_type=film"
    )
    data = _http_json(url)
    out: list[StockVideo] = []
    for v in data.get("hits") or []:
        if not isinstance(v, dict):
            continue
        videos = v.get("videos") or {}
        pick = None
        for key in ("large", "medium", "small", "tiny"):
            cand = videos.get(key)
            if isinstance(cand, dict) and cand.get("url"):
                pick = cand
                if key == "large":
                    break
        if not pick:
            continue
        tags = str(v.get("tags") or "")
        out.append(
            StockVideo(
                provider="pixabay",
                video_id=str(v.get("id", "")),
                title=tags[:60] or f"Pixabay #{v.get('id', '')}",
                thumbnail_url=f"https://i.vimeocdn.com/video/{v.get('picture_id', '')}_640.jpg"
                if v.get("picture_id")
                else "",
                download_url=str(pick.get("url") or ""),
                duration=int(v.get("duration") or 0),
                width=int(pick.get("width") or 0),
                page_url=f"https://pixabay.com/videos/id-{v.get('id', '')}/",
            )
        )
    return out


def _merge_results(chunks: list[list[StockVideo]], *, limit: int) -> list[StockVideo]:
    out: list[StockVideo] = []
    seen: set[str] = set()
    for chunk in chunks:
        for v in chunk:
            key = v.download_url or f"{v.provider}:{v.video_id}"
            if key in seen:
                continue
            seen.add(key)
            out.append(v)
            if len(out) >= limit:
                return out
    return out


def search_stock_videos(
    cue_text: str = "",
    *,
    query: str | None = None,
    per_page: int = 6,
    on_progress: Callable[[str, float], None] | None = None,
) -> tuple[str, list[StockVideo]]:
    """자막 텍스트 또는 지정 키워드 → (검색 쿼리, 결과 목록)."""

    def prog(label: str, pct: float) -> None:
        if on_progress:
            on_progress(label, min(100.0, max(0.0, pct)))

    stop_pulse = threading.Event()

    def pulse(label: str, start: float, end: float) -> None:
        pct = start
        while not stop_pulse.is_set() and pct < end:
            prog(label, pct)
            if stop_pulse.wait(0.35):
                break
            pct = min(end - 0.5, pct + 2.0)

    prog("준비", 3)
    if query is None or not str(query).strip():
        stop_pulse.clear()
        pulse_th = threading.Thread(target=pulse, args=("키워드 번역", 8, 28), daemon=True)
        pulse_th.start()
        try:
            q = search_query_from_cue(cue_text)
        finally:
            stop_pulse.set()
            pulse_th.join(timeout=1.0)
    else:
        q = normalize_search_query(str(query).strip())
        prog("키워드 확인", 28)

    if not q:
        raise RuntimeError("검색 키워드가 비어 있습니다.")

    keys = load_api_keys()
    pex = keys.get("pexels_api_key", "")
    pix = keys.get("pixabay_api_key", "")
    cov = keys.get("coverr_api_key", "")
    provider_per = max(6, per_page)

    provider_jobs: list[tuple[str, Callable[[], list[StockVideo]]]] = []
    if pex:
        provider_jobs.append(("Pexels", lambda: search_pexels(q, api_key=pex, per_page=provider_per)))
    if pix:
        provider_jobs.append(("Pixabay", lambda: search_pixabay(q, api_key=pix, per_page=provider_per)))
    if cov:
        provider_jobs.append(("Coverr", lambda: search_coverr(q, api_key=cov, per_page=provider_per)))
    provider_jobs.append(("Mixkit", lambda: search_mixkit(q, per_page=provider_per)))

    errors: list[str] = []
    chunks: list[list[StockVideo]] = []
    done_count = 0
    total = len(provider_jobs)

    stop_pulse.clear()
    pulse_th = threading.Thread(target=pulse, args=("영상 검색", 35, 88), daemon=True)
    pulse_th.start()
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, total)) as pool:
            futs = {pool.submit(fn): name for name, fn in provider_jobs}
            for fut in concurrent.futures.as_completed(futs):
                name = futs[fut]
                done_count += 1
                pct = 35 + (done_count / total) * 50
                prog(f"{name} 완료", pct)
                try:
                    chunk = fut.result(timeout=50)
                    if chunk:
                        chunks.append(chunk)
                except (
                    concurrent.futures.TimeoutError,
                    urllib.error.URLError,
                    urllib.error.HTTPError,
                    RuntimeError,
                    TimeoutError,
                ) as e:
                    errors.append(f"{name}: {e}")
    finally:
        stop_pulse.set()
        pulse_th.join(timeout=1.0)

    merged = _merge_results(chunks, limit=max(per_page * 2, provider_per * 2))
    results = rank_videos(merged, q)[:per_page]

    prog("정리", 94)
    if not results:
        msg = "검색어와 관련된 영상을 찾지 못했습니다."
        msg += f"\n\n검색 키워드: {q}"
        if errors:
            msg += "\n\n" + "\n".join(errors)
        elif not pex and not pix and not cov:
            cfg = stock_api_config_write_path()
            msg += (
                f"\n\nAPI 키가 로드되지 않았습니다.\n"
                f"아래 파일에 키를 저장하세요 (폴더 없으면 만들기):\n{cfg}\n\n"
                f"config/stock_api.example.json 을 복사해 stock_api.json 으로 저장한 뒤 키를 넣으세요."
            )
        raise RuntimeError(msg)
    prog("완료", 100)
    return q, results
