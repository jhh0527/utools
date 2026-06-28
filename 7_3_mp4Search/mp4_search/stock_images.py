# -*- coding: utf-8 -*-
"""Pexels·Pixabay 무료 스톡 이미지 검색."""

from __future__ import annotations

import concurrent.futures
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from mp4_search.stock_search import _http_json, load_api_keys, normalize_search_query


@dataclass(frozen=True)
class StockImage:
    provider: str
    image_id: str
    title: str
    thumbnail_url: str
    download_url: str
    page_url: str


def image_cache_key(image: StockImage) -> str:
    return f"{image.provider}:{image.image_id}"


def search_pexels_images(query: str, *, api_key: str, per_page: int = 8) -> list[StockImage]:
    q = urllib.parse.quote(normalize_search_query(query))
    if not q or not api_key:
        return []
    url = f"https://api.pexels.com/v1/search?query={q}&per_page={per_page}"
    data = _http_json(url, headers={"Authorization": api_key})
    out: list[StockImage] = []
    for hit in data.get("photos") or []:
        if not isinstance(hit, dict):
            continue
        src = hit.get("src") if isinstance(hit.get("src"), dict) else {}
        dl = str(src.get("large2x") or src.get("large") or src.get("medium") or "")
        thumb = str(src.get("medium") or src.get("small") or dl)
        if not dl:
            continue
        out.append(
            StockImage(
                provider="pexels",
                image_id=str(hit.get("id", "")),
                title=str(hit.get("alt") or f"Pexels #{hit.get('id', '')}")[:80],
                thumbnail_url=thumb,
                download_url=dl,
                page_url=str(hit.get("url") or ""),
            )
        )
    return out


def search_pixabay_images(query: str, *, api_key: str, per_page: int = 8) -> list[StockImage]:
    q = urllib.parse.quote(normalize_search_query(query))
    if not q or not api_key:
        return []
    url = (
        f"https://pixabay.com/api/?key={urllib.parse.quote(api_key)}"
        f"&q={q}&image_type=photo&per_page={per_page}&safesearch=true"
    )
    data = _http_json(url)
    out: list[StockImage] = []
    for hit in data.get("hits") or []:
        if not isinstance(hit, dict):
            continue
        dl = str(hit.get("largeImageURL") or hit.get("webformatURL") or "")
        thumb = str(hit.get("previewURL") or hit.get("webformatURL") or dl)
        if not dl:
            continue
        tags = str(hit.get("tags") or "")
        out.append(
            StockImage(
                provider="pixabay",
                image_id=str(hit.get("id", "")),
                title=tags[:80] or f"Pixabay #{hit.get('id', '')}",
                thumbnail_url=thumb,
                download_url=dl,
                page_url=f"https://pixabay.com/photos/id-{hit.get('id', '')}/",
            )
        )
    return out


def search_stock_images(query: str, *, per_page: int = 8) -> list[StockImage]:
    keys = load_api_keys()
    pex = keys.get("pexels_api_key", "")
    pix = keys.get("pixabay_api_key", "")
    chunks: list[list[StockImage]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futs = []
        if pex:
            futs.append(pool.submit(search_pexels_images, query, api_key=pex, per_page=per_page))
        if pix:
            futs.append(pool.submit(search_pixabay_images, query, api_key=pix, per_page=per_page))
        for fut in futs:
            try:
                chunk = fut.result(timeout=40)
                if chunk:
                    chunks.append(chunk)
            except (
                concurrent.futures.TimeoutError,
                urllib.error.URLError,
                urllib.error.HTTPError,
                RuntimeError,
                TimeoutError,
            ):
                continue
    out: list[StockImage] = []
    seen: set[str] = set()
    for chunk in chunks:
        for img in chunk:
            key = img.download_url or image_cache_key(img)
            if key in seen:
                continue
            seen.add(key)
            out.append(img)
            if len(out) >= per_page:
                return out
    return out
