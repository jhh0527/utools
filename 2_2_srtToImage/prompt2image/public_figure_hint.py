# -*- coding: utf-8 -*-
"""SRT·대본에서 필수 실존 인물(연준 의장·대통령·유명 경제인 등) 감지."""

from __future__ import annotations

import re

# (패턴, 영문 실명, 장면 힌트)
_FIGURE_RULES: tuple[tuple[re.Pattern[str], str, str], ...] = (
    (
        re.compile(
            r"연준\s*의장|연준\s*총재|Fed(?:eral\s*Reserve)?\s*Chair|"
            r"Jerome\s*Powell|제롬\s*파월|파월\s*의장|파월\s*총재|"
            r"FOMC|연준\s*금리|연준\s*기준금리",
            re.I,
        ),
        "Jerome Powell",
        "Federal Reserve press conference podium, Fed seal visible",
    ),
    (
        re.compile(
            r"미국\s*대통령|백악관|White\s*House|US\s*President|"
            r"Donald\s*Trump|Joe\s*Biden|트럼프|바이든",
            re.I,
        ),
        "US President (match SRT context: Donald Trump or Joe Biden)",
        "White House or press briefing room, presidential podium",
    ),
    (
        re.compile(
            r"한국\s*대통령|청와대|용산|대통령실|"
            r"윤석열|이재명|문재인",
            re.I,
        ),
        "Korean President (match SRT named person or context)",
        "Blue House or presidential briefing, official press photo",
    ),
    (
        re.compile(
            r"ECB\s*총재|ECB\s*President|Christine\s*Lagarde|"
            r"라가르드|유럽중앙은행",
            re.I,
        ),
        "Christine Lagarde",
        "ECB press conference, European Central Bank setting",
    ),
    (
        re.compile(
            r"BOJ\s*총재|일본은행\s*총재|Bank\s*of\s*Japan\s*Governor|"
            r"우eda|植田|Kazuo\s*Ueda",
            re.I,
        ),
        "Kazuo Ueda",
        "Bank of Japan press conference",
    ),
    (
        re.compile(
            r"Elon\s*Musk|일론\s*머스크|테슬라\s*CEO|Tesla\s*CEO",
            re.I,
        ),
        "Elon Musk",
        "Tesla earnings call or product announcement, corporate press photo",
    ),
    (
        re.compile(
            r"Jensen\s*Huang|젠슨\s*황|엔비디아\s*CEO|NVIDIA\s*CEO",
            re.I,
        ),
        "Jensen Huang",
        "NVIDIA keynote or earnings presentation",
    ),
    (
        re.compile(
            r"Tim\s*Cook|팀\s*쿡|애플\s*CEO|Apple\s*CEO",
            re.I,
        ),
        "Tim Cook",
        "Apple keynote or corporate announcement",
    ),
    (
        re.compile(
            r"Warren\s*Buffett|워런\s*버핏|버핏",
            re.I,
        ),
        "Warren Buffett",
        "Berkshire Hathaway annual meeting or financial press photo",
    ),
    (
        re.compile(
            r"Ray\s*Dalio|레이\s*달리오",
            re.I,
        ),
        "Ray Dalio",
        "financial conference or media interview setting",
    ),
    (
        re.compile(
            r"재무\s*장관|Treasury\s*Secretary|Janet\s*Yellen|"
            r"옐런|Scott\s*Bessent",
            re.I,
        ),
        "US Treasury Secretary (match SRT context)",
        "US Treasury press briefing, official government photo",
    ),
    (
        re.compile(
            r"IMF\s*총재|Managing\s*Director\s*IMF|Kristalina\s*Georgieeva",
            re.I,
        ),
        "Kristalina Georgieva",
        "IMF press conference",
    ),
)


def detect_mandatory_figures(text: str) -> list[tuple[str, str]]:
    """매칭된 (영문 실명, 장면 힌트) 목록. 중복 실명 제거."""
    if not (text or "").strip():
        return []
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for pat, name, scene in _FIGURE_RULES:
        if pat.search(text):
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            out.append((name, scene))
    return out


def build_public_figure_hint(text: str) -> str:
    """Genspark 프롬프트에 붙일 필수 실존 인물 지시문."""
    figures = detect_mandatory_figures(text)
    if not figures:
        return ""
    lines = [
        "[필수 실존 인물 — 이 장면에 반드시 포함]",
        "아래 실존 공인의 뉴스·기자회견 실사(archival news photo, press conference photo)를 "
        "이미지 중심 피사체로 생성하세요. 건물·연단·로고만으로 대체하지 마세요.",
        "AI 가상 인물·무명 인물·합성 얼굴은 금지이나, 아래 **실명 공인**은 반드시 포함합니다.",
    ]
    for name, scene in figures:
        lines.append(f"- {name}: {scene}")
    return "\n".join(lines)
