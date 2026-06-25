from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from utube.api import YouTubeApiError, fetch_keyword_search, fetch_top_by_views, fetch_trending
from utube.categories import category_label
from utube.config import load_api_key
from utube.format_util import format_count, format_published


def _print_rows(rows: list, *, limit: int) -> None:
    for i, v in enumerate(rows[:limit], start=1):
        cat = category_label(v.category_id)
        cat_s = f"[{cat[:8]}] " if cat else ""
        print(
            f"{i:3}. {format_count(v.view_count):>8}  {format_published(v.published_at)}  "
            f"{cat_s}{v.channel[:18]:18}  {v.title[:56]}"
        )
        print(f"     {v.url}")


def cmd_trending(args: argparse.Namespace) -> int:
    key = load_api_key()
    try:
        rows = fetch_trending(
            key,
            region=args.region,
            max_results=args.max,
            category_id=args.category or None,
        )
    except YouTubeApiError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print_rows(rows, limit=args.max)
    if args.csv:
        _write_csv(rows, Path(args.csv))
        print(f"\nCSV 저장: {args.csv}")
    return 0


def cmd_keyword(args: argparse.Namespace) -> int:
    key = load_api_key()
    try:
        rows = fetch_keyword_search(
            key,
            query=args.query,
            region=args.region,
            days=args.days,
            max_results=args.max,
        )
    except YouTubeApiError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print_rows(rows, limit=args.max)
    if args.csv:
        _write_csv(rows, Path(args.csv))
        print(f"\nCSV 저장: {args.csv}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    key = load_api_key()
    try:
        rows = fetch_top_by_views(
            key,
            query=args.query or "",
            region=args.region,
            days=args.days,
            max_results=args.max,
        )
    except YouTubeApiError as e:
        print(str(e), file=sys.stderr)
        return 1
    _print_rows(rows, limit=args.max)
    if args.csv:
        _write_csv(rows, Path(args.csv))
        print(f"\nCSV 저장: {args.csv}")
    return 0


def _write_csv(rows: list, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["순위", "제목", "채널", "카테고리", "조회수", "좋아요", "업로드", "길이", "쇼츠", "URL"]
        )
        for i, v in enumerate(rows, start=1):
            w.writerow(
                [
                    i,
                    v.title,
                    v.channel,
                    category_label(v.category_id),
                    v.view_count,
                    v.like_count or "",
                    format_published(v.published_at),
                    v.duration,
                    v.shorts_display,
                    v.url,
                ]
            )


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="utube", description="YouTube 인기·고조회 영상 조회")
    sub = p.add_subparsers(dest="cmd", required=True)

    pt = sub.add_parser("trending", help="지역 인기 급상승(mostPopular)")
    pt.add_argument("--region", default="KR", help="국가 코드 (기본 KR)")
    pt.add_argument("--max", type=int, default=25, help="최대 개수 (1~50)")
    pt.add_argument("--category", default="", help="videoCategoryId (선택)")
    pt.add_argument("--csv", default="", help="CSV 저장 경로")
    pt.set_defaults(func=cmd_trending)

    pk = sub.add_parser("keyword", help="키워드 검색 (관련도 순)")
    pk.add_argument("--query", "-q", default="", help="검색어 (비우면 전체)")
    pk.add_argument("--region", default="KR")
    pk.add_argument("--days", type=int, default=30, help="최근 N일 (1~365)")
    pk.add_argument("--max", type=int, default=25)
    pk.add_argument("--csv", default="")
    pk.set_defaults(func=cmd_keyword)

    ps = sub.add_parser("search", help="기간 내 조회수 순 검색")
    ps.add_argument("--query", "-q", default="", help="검색어 (선택)")
    ps.add_argument("--region", default="KR")
    ps.add_argument("--days", type=int, default=30, help="최근 N일 (1~365)")
    ps.add_argument("--max", type=int, default=25)
    ps.add_argument("--csv", default="")
    ps.set_defaults(func=cmd_search)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
