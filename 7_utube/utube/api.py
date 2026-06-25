from __future__ import annotations

import json
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone

from utube.format_util import parse_iso8601_duration, parse_iso8601_duration_seconds
from utube.models import KeywordItem, VideoItem

_API = "https://www.googleapis.com/youtube/v3"
_API_PAGE_SIZE = 50
_MAX_RESULTS = 500


def _clamp_results(n: int) -> int:
    return max(1, min(_MAX_RESULTS, int(n)))


class YouTubeApiError(RuntimeError):
    pass


def _get(path: str, params: dict[str, str], api_key: str) -> dict:
    q = dict(params)
    q["key"] = api_key
    url = f"{_API}/{path}?{urllib.parse.urlencode(q)}"
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", errors="replace")
        except OSError:
            pass
        msg = body
        try:
            err = json.loads(body).get("error", {})
            msg = err.get("message") or body
        except (json.JSONDecodeError, AttributeError):
            pass
        raise YouTubeApiError(f"YouTube API HTTP {e.code}: {msg}") from e
    except urllib.error.URLError as e:
        raise YouTubeApiError(f"네트워크 오류: {e.reason}") from e
    return json.loads(raw)


def _items_from_videos_response(data: dict, *, region_code: str = "") -> list[VideoItem]:
    out: list[VideoItem] = []
    for it in data.get("items") or []:
        vid = str(it.get("id") or "")
        if not vid:
            continue
        sn = it.get("snippet") or {}
        st = it.get("statistics") or {}
        cd = it.get("contentDetails") or {}
        vc = st.get("viewCount")
        lc = st.get("likeCount")
        cc = st.get("commentCount")
        iso_dur = str(cd.get("duration") or "")
        raw_tags = sn.get("tags") or []
        tags = tuple(str(t).strip() for t in raw_tags if str(t).strip())
        out.append(
            VideoItem(
                video_id=vid,
                title=str(sn.get("title") or "").replace("\n", " "),
                channel=str(sn.get("channelTitle") or ""),
                view_count=int(vc) if vc is not None else 0,
                like_count=int(lc) if lc is not None else None,
                comment_count=int(cc) if cc is not None else None,
                published_at=str(sn.get("publishedAt") or ""),
                duration=parse_iso8601_duration(iso_dur),
                duration_seconds=parse_iso8601_duration_seconds(iso_dur),
                category_id=str(sn.get("categoryId") or "") or None,
                tags=tags,
                region_code=region_code.upper()[:2] if region_code else "",
                description=str(sn.get("description") or ""),
            )
        )
    return out


def _tag_videos_region(videos: list[VideoItem], region_code: str) -> list[VideoItem]:
    reg = region_code.upper()[:2]
    if not reg:
        return videos
    out: list[VideoItem] = []
    for v in videos:
        if v.region_code == reg:
            out.append(v)
        else:
            out.append(
                VideoItem(
                    video_id=v.video_id,
                    title=v.title,
                    channel=v.channel,
                    view_count=v.view_count,
                    like_count=v.like_count,
                    comment_count=v.comment_count,
                    published_at=v.published_at,
                    duration=v.duration,
                    duration_seconds=v.duration_seconds,
                    category_id=v.category_id,
                    tags=v.tags,
                    region_code=reg,
                    description=v.description,
                )
            )
    return out


def _merge_videos(
    lists: list[list[VideoItem]],
    max_results: int,
    *,
    sort_by_views: bool,
) -> list[VideoItem]:
    seen: set[str] = set()
    out: list[VideoItem] = []
    for lst in lists:
        for v in lst:
            if v.video_id in seen:
                continue
            seen.add(v.video_id)
            out.append(v)
    if sort_by_views:
        out.sort(key=lambda v: v.view_count, reverse=True)
    return out[: _clamp_results(max_results)]


def _fetch_trending_once(
    api_key: str,
    *,
    region: str,
    max_results: int,
    category_id: str | None,
) -> list[VideoItem]:
    params: dict[str, str] = {
        "part": "snippet,statistics,contentDetails",
        "chart": "mostPopular",
        "regionCode": region.upper()[:2],
        "maxResults": str(max_results),
    }
    if category_id:
        params["videoCategoryId"] = category_id
    try:
        data = _get("videos", params, api_key)
    except YouTubeApiError as e:
        # 지역·카테고리 조합에 인기 차트가 없으면 404 — 다른 카테고리는 계속 조회
        if "404" in str(e):
            return []
        raise
    return _items_from_videos_response(data, region_code=region.upper()[:2])


def fetch_trending(
    api_key: str,
    *,
    region: str = "KR",
    regions: list[str] | None = None,
    max_results: int = 50,
    category_id: str | None = None,
    category_ids: list[str] | None = None,
) -> list[VideoItem]:
    """지역별 인기 급상승(mostPopular) 영상."""
    if not api_key.strip():
        raise YouTubeApiError("YouTube API 키가 없습니다. config/youtube_api.json 또는 YOUTUBE_API_KEY 를 설정하세요.")
    max_results = _clamp_results(max_results)
    regs = list(regions or [])
    if not regs:
        regs = [region.upper()[:2]]
    ids = list(category_ids or [])
    if category_id and category_id not in ids:
        ids.insert(0, category_id)

    lists: list[list[VideoItem]] = []
    for reg in regs:
        if not ids:
            batch = _fetch_trending_once(
                api_key, region=reg, max_results=max_results, category_id=None
            )
            if batch:
                lists.append(_tag_videos_region(batch, reg))
            continue
        for cid in ids:
            batch = _fetch_trending_once(
                api_key, region=reg, max_results=max_results, category_id=cid
            )
            if batch:
                lists.append(_tag_videos_region(batch, reg))
    if ids and not lists:
        raise YouTubeApiError(
            "선택한 카테고리에 인기 급상승 데이터가 없습니다. "
            "카테고리를 줄이거나 「카테고리 (전체)」로 조회하세요."
        )
    if not lists:
        return []
    return _merge_videos(lists, max_results, sort_by_views=True)


def _search_video_ids(
    api_key: str,
    *,
    query: str,
    region: str,
    days: int,
    max_results: int,
    order: str,
    require_query: bool,
    category_id: str | None = None,
) -> list[str]:
    q = query.strip()
    if require_query and not q:
        raise YouTubeApiError("검색어를 입력하세요.")
    if not q:
        return _search_video_ids_broad(
            api_key,
            region=region,
            days=days,
            max_results=max_results,
            order=order,
        )
    max_results = _clamp_results(max_results)
    days = max(1, min(365, int(days)))
    after = datetime.now(timezone.utc) - timedelta(days=days)
    search_params: dict[str, str] = {
        "part": "snippet",
        "type": "video",
        "order": order,
        "regionCode": region.upper()[:2],
        "publishedAfter": after.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if q:
        search_params["q"] = q
    if category_id:
        search_params["videoCategoryId"] = category_id
    ids: list[str] = []
    page_token = ""
    while len(ids) < max_results:
        batch = min(_API_PAGE_SIZE, max_results - len(ids))
        search_params["maxResults"] = str(batch)
        if page_token:
            search_params["pageToken"] = page_token
        else:
            search_params.pop("pageToken", None)
        try:
            search_data = _get("search", search_params, api_key)
        except YouTubeApiError as e:
            if "404" in str(e):
                break
            raise
        for it in search_data.get("items") or []:
            vid = (it.get("id") or {}).get("videoId")
            if vid:
                ids.append(str(vid))
        page_token = str(search_data.get("nextPageToken") or "")
        if not page_token:
            break
    return ids[:max_results]


def _videos_by_ids(api_key: str, ids: list[str], *, region_code: str = "") -> list[VideoItem]:
    if not ids:
        return []
    by_id: dict[str, VideoItem] = {}
    for i in range(0, len(ids), _API_PAGE_SIZE):
        chunk = ids[i : i + _API_PAGE_SIZE]
        videos_data = _get(
            "videos",
            {
                "part": "snippet,statistics,contentDetails",
                "id": ",".join(chunk),
                "maxResults": str(len(chunk)),
            },
            api_key,
        )
        for v in _items_from_videos_response(videos_data, region_code=region_code):
            by_id[v.video_id] = v
    return [by_id[i] for i in ids if i in by_id]


def _fetch_top_by_views_region(
    api_key: str,
    *,
    query: str,
    region: str,
    days: int,
    max_results: int,
) -> list[VideoItem]:
    """지역·기간 내 조회수 순. 검색어 없으면 인기 급상승 + 넓은 시드 검색을 합친다."""
    reg = region.upper()[:2]
    max_r = _clamp_results(max_results)
    days_n = max(1, min(365, int(days)))
    after = datetime.now(timezone.utc) - timedelta(days=days_n)
    after_key = after.strftime("%Y-%m-%d")

    def _within_days(videos: list[VideoItem]) -> list[VideoItem]:
        kept = [v for v in videos if v.published_at and v.published_at[:10] >= after_key]
        return kept or videos

    if not query.strip():
        lists: list[list[VideoItem]] = []
        try:
            trending = fetch_trending(api_key, region=reg, max_results=min(_MAX_RESULTS, max_r))
            if trending:
                lists.append(_tag_videos_region(trending, reg))
        except YouTubeApiError:
            pass
        fetch_n = min(_MAX_RESULTS, max(max_r, max_r * 5))
        ids = _search_video_ids(
            api_key,
            query="",
            region=reg,
            days=days_n,
            max_results=fetch_n,
            order="viewCount",
            require_query=False,
        )
        if ids:
            lists.append(_tag_videos_region(_videos_by_ids(api_key, ids, region_code=reg), reg))
        if not lists:
            return []
        merged = _merge_videos(lists, min(max_r, _MAX_RESULTS), sort_by_views=True)
        merged = _within_days(merged)
        merged.sort(key=lambda v: v.view_count, reverse=True)
        return merged[:max_r]

    fetch_n = min(_MAX_RESULTS, max(max_r, max_r * 5))
    ids = _search_video_ids(
        api_key,
        query=query,
        region=reg,
        days=days_n,
        max_results=fetch_n,
        order="viewCount",
        require_query=False,
    )
    if not ids:
        ids = _search_video_ids(
            api_key,
            query=query,
            region=reg,
            days=days_n,
            max_results=min(_MAX_RESULTS, fetch_n),
            order="date",
            require_query=False,
        )
    videos = _tag_videos_region(_videos_by_ids(api_key, ids, region_code=reg), reg)
    videos.sort(key=lambda v: v.view_count, reverse=True)
    return videos[:max_r]


def _fetch_search_videos(
    api_key: str,
    *,
    query: str,
    region: str,
    regions: list[str] | None,
    days: int,
    max_results: int,
    order: str,
    category_ids: list[str] | None,
) -> list[VideoItem]:
    regs = list(regions or [])
    if not regs:
        regs = [region.upper()[:2]]
    cids = list(category_ids or [])
    lists: list[list[VideoItem]] = []
    for reg in regs:
        if order == "viewCount" and not cids:
            batch = _fetch_top_by_views_region(
                api_key,
                query=query,
                region=reg,
                days=days,
                max_results=max_results,
            )
            if batch:
                lists.append(batch)
            continue
        if not cids:
            ids = _search_video_ids(
                api_key,
                query=query,
                region=reg,
                days=days,
                max_results=max_results,
                order=order,
                require_query=False,
            )
            batch = _tag_videos_region(_videos_by_ids(api_key, ids, region_code=reg), reg)
            if batch:
                lists.append(batch)
            continue
        for cid in cids:
            ids = _search_video_ids(
                api_key,
                query=query,
                region=reg,
                days=days,
                max_results=max_results,
                order=order,
                require_query=False,
                category_id=cid,
            )
            batch = _tag_videos_region(_videos_by_ids(api_key, ids, region_code=reg), reg)
            if batch:
                lists.append(batch)
    if not lists:
        return []
    return _merge_videos(lists, max_results, sort_by_views=(order == "viewCount"))


def fetch_keyword_search(
    api_key: str,
    *,
    query: str,
    region: str = "KR",
    regions: list[str] | None = None,
    days: int = 30,
    max_results: int = 50,
    category_ids: list[str] | None = None,
) -> list[VideoItem]:
    """키워드로 영상 검색 (관련도 순). 검색어가 비어 있으면 기간·지역 기준 전체 검색."""
    if not api_key.strip():
        raise YouTubeApiError("YouTube API 키가 없습니다.")
    return _fetch_search_videos(
        api_key,
        query=query,
        region=region,
        regions=regions,
        days=days,
        max_results=max_results,
        order="relevance",
        category_ids=category_ids,
    )


def fetch_top_by_views(
    api_key: str,
    *,
    query: str = "",
    region: str = "KR",
    regions: list[str] | None = None,
    days: int = 30,
    max_results: int = 50,
    category_ids: list[str] | None = None,
) -> list[VideoItem]:
    """키워드(선택) + 기간 내 업로드 영상을 조회수 순으로 검색."""
    if not api_key.strip():
        raise YouTubeApiError("YouTube API 키가 없습니다.")
    return _fetch_search_videos(
        api_key,
        query=query,
        region=region,
        regions=regions,
        days=days,
        max_results=max_results,
        order="viewCount",
        category_ids=category_ids,
    )


_REGION_GL: dict[str, str] = {
    "KR": "kr",
    "US": "us",
    "JP": "jp",
    "GB": "gb",
    "DE": "de",
    "FR": "fr",
    "IN": "in",
    "BR": "br",
}

_SUGGEST_SEEDS_KO = ("", "가", "나", "다", "라", "마", "바", "사", "아", "오", "주", "한", "202")
_SUGGEST_SEEDS_EN = ("", "a", "b", "c", "s", "t", "m", "n", "202")

# search.list 는 q 없이 호출하면 결과가 비므로, 「전체」 조회 시 넓은 시드로 대체
_BROAD_SEEDS_KR = ("*", "a", "2026", "영상", "뉴스", "한국", "드라마", "음악")
_BROAD_SEEDS_EN = ("*", "a", "2026", "video", "news", "music", "movie", "sport")


def _broad_seeds_for_region(region: str) -> tuple[str, ...]:
    return _BROAD_SEEDS_KR if region.upper()[:2] == "KR" else _BROAD_SEEDS_EN


def _search_video_ids_broad(
    api_key: str,
    *,
    region: str,
    days: int,
    max_results: int,
    order: str,
) -> list[str]:
    """검색어 없이 기간·지역 전체 조회 — 넓은 시드 검색 결과를 합친다."""
    target = _clamp_results(max_results)
    seen: set[str] = set()
    out: list[str] = []
    per_seed = min(_API_PAGE_SIZE, max(10, target // 2))
    for seed in _broad_seeds_for_region(region):
        if len(out) >= target:
            break
        batch = _search_video_ids(
            api_key,
            query=seed,
            region=region,
            days=days,
            max_results=per_seed,
            order=order,
            require_query=False,
        )
        for vid in batch:
            if vid not in seen:
                seen.add(vid)
                out.append(vid)
    return out[:target]


def _youtube_suggest(query: str, *, region: str) -> list[str]:
    """YouTube 검색 자동완성(인기 연관 키워드). API 키·할당량 불필요."""
    gl = _REGION_GL.get(region.upper()[:2], region.lower()[:2])
    hl = "ko" if gl == "kr" else "en"
    params = {
        "client": "firefox",
        "ds": "yt",
        "q": query,
        "hl": hl,
        "gl": gl,
    }
    url = f"https://suggestqueries.google.com/complete/search?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError):
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list) or len(data) < 2:
        return []
    return [str(x).strip() for x in data[1] if str(x).strip()]


def _keyword_weight(view_count: int) -> int:
    if view_count <= 0:
        return 1
    return max(1, int(view_count ** 0.5 // 1000))


def fetch_popular_keywords(
    api_key: str,
    *,
    region: str = "KR",
    regions: list[str] | None = None,
    max_results: int = 50,
    category_ids: list[str] | None = None,
    exclude_shorts: bool = False,
    excluded_category_ids: set[str] | frozenset[str] | None = None,
) -> list[KeywordItem]:
    """지역 인기 영상 태그·제목 + YouTube 자동완성으로 인기 키워드 목록."""
    if not api_key.strip():
        raise YouTubeApiError("YouTube API 키가 없습니다.")
    max_results = _clamp_results(max_results)

    videos = fetch_trending(
        api_key,
        region=region,
        regions=regions,
        max_results=min(_MAX_RESULTS, max_results),
        category_ids=category_ids,
    )
    if exclude_shorts:
        videos = [v for v in videos if not v.is_shorts]
    if excluded_category_ids:
        exc = set(excluded_category_ids)
        videos = [v for v in videos if not v.category_id or v.category_id not in exc]

    scores: Counter[str] = Counter()
    sources: dict[str, set[str]] = defaultdict(set)

    for v in videos:
        weight = _keyword_weight(v.view_count)
        for tag in v.tags:
            kw = tag.strip()
            if len(kw) >= 2:
                scores[kw] += weight
                sources[kw].add("태그")
        for m in re.findall(r"#([\w가-힣]+)", v.title):
            kw = m.strip()
            if len(kw) >= 2:
                scores[kw] += weight
                sources[kw].add("제목")

    seeds = _SUGGEST_SEEDS_KO if (regions or [region])[0].upper()[:2] == "KR" else _SUGGEST_SEEDS_EN
    suggest_region = (regions or [region])[0]
    for seed in seeds:
        for sug in _youtube_suggest(seed, region=suggest_region):
            if len(sug) >= 2:
                scores[sug] += 3
                sources[sug].add("자동완성")

    top_tag_seeds = [kw for kw, _ in scores.most_common(8)]
    for seed in top_tag_seeds:
        for sug in _youtube_suggest(seed, region=suggest_region):
            if len(sug) >= 2 and sug != seed:
                scores[sug] += 2
                sources[sug].add("자동완성")

    ranked = scores.most_common(max_results)
    out: list[KeywordItem] = []
    for kw, sc in ranked:
        src = "/".join(sorted(sources[kw]))
        out.append(KeywordItem(keyword=kw, score=sc, source=src))
    return out
