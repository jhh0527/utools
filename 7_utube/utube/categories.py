"""YouTube ``videoCategoryId`` → 표시 이름."""

from __future__ import annotations

# https://developers.google.com/youtube/v3/docs/videoCategories/list
YOUTUBE_CATEGORY_LABELS: dict[str, str] = {
    "1": "영화/애니",
    "2": "자동차",
    "10": "음악",
    "15": "동물",
    "17": "스포츠",
    "18": "단편영화",
    "19": "여행/이벤트",
    "20": "게임",
    "21": "브이로그",
    "22": "사람/블로그",
    "23": "코미디",
    "24": "엔터테인먼트",
    "25": "뉴스/정치",
    "26": "노하우/스타일",
    "27": "교육",
    "28": "과학/기술",
    "29": "비영리/사회운동",
    "30": "영화",
    "31": "애니메이션",
    "32": "액션/모험",
    "33": "고전",
    "34": "코미디(영화)",
    "35": "다큐",
    "36": "드라마",
    "37": "가족",
    "38": "외국어",
    "39": "공포",
    "40": "SF/판타지",
    "41": "스릴러",
    "42": "쇼츠",
    "43": "프로그램",
    "44": "예고편",
}


def category_label(category_id: str | None) -> str:
    if not category_id:
        return ""
    return YOUTUBE_CATEGORY_LABELS.get(str(category_id).strip(), f"ID:{category_id}")


# GUI 카테고리 제외 선택용 (이름, videoCategoryId)
SELECTABLE_CATEGORIES: list[tuple[str, str]] = [
    ("음악", "10"),
    ("게임", "20"),
    ("뉴스", "25"),
    ("과학/기술", "28"),
    ("교육", "27"),
    ("엔터", "24"),
    ("스포츠", "17"),
]

# 기본 제외: 음악·게임
DEFAULT_EXCLUDED_CATEGORY_IDS: frozenset[str] = frozenset({"10", "20"})
