from __future__ import annotations

from dataclasses import dataclass

from utube.format_util import is_youtube_shorts, shorts_label


@dataclass(frozen=True, slots=True)
class VideoItem:
    video_id: str
    title: str
    channel: str
    view_count: int
    like_count: int | None
    comment_count: int | None
    published_at: str
    duration: str
    duration_seconds: int = 0
    category_id: str | None = None
    tags: tuple[str, ...] = ()
    region_code: str = ""
    description: str = ""

    @property
    def is_shorts(self) -> bool:
        return is_youtube_shorts(self.duration_seconds)

    @property
    def shorts_display(self) -> str:
        return shorts_label(self.duration_seconds)

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.video_id}"


@dataclass(frozen=True, slots=True)
class KeywordItem:
    keyword: str
    score: int
    source: str
