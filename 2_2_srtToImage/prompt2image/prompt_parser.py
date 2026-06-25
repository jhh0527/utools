"""이미지 프롬프트 마크다운 파서.

지원 형식 (`로스차일드_이미지프롬프트.md` 기준):

    ## 장면 01 — 1812 가을, 유덴가세 병상

    **대본 요지:** ...

    **이미지 프롬프트 (영문)**

    ```text
    ... english prompt ...
    ```

    **부정 프롬프트**

    ```text
    ... negative prompt ...
    ```
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Scene:
    number: str
    title: str
    summary: str
    prompt: str
    negative: str

    @property
    def display(self) -> str:
        return f"장면 {self.number} — {self.title}" if self.title else f"장면 {self.number}"

    @property
    def safe_stem(self) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z가-힣_\- ]+", "", f"{self.number}_{self.title}")
        cleaned = cleaned.strip().replace(" ", "_")
        return cleaned or f"scene_{self.number}"


_HEADER_RE = re.compile(r"^##\s*장면\s*([0-9]+)\s*[—\-:]?\s*(.*?)\s*$", re.MULTILINE)
_BLOCK_LABEL_RE = re.compile(
    r"\*\*(?P<label>대본\s*요지|이미지\s*프롬프트(?:\s*\(영문\))?|부정\s*프롬프트)\*\*[:：]?\s*",
)
_FENCE_RE = re.compile(r"```(?:[a-zA-Z0-9_-]*)\n(.*?)```", re.DOTALL)


def parse_markdown(md_text: str) -> list[Scene]:
    """마크다운 본문에서 장면 목록을 추출합니다."""
    headers = list(_HEADER_RE.finditer(md_text))
    if not headers:
        return []

    scenes: list[Scene] = []
    for i, m in enumerate(headers):
        start = m.end()
        end = headers[i + 1].start() if i + 1 < len(headers) else len(md_text)
        body = md_text[start:end]

        number = m.group(1).strip()
        title = m.group(2).strip().lstrip("—-: ").strip()
        title = re.sub(r"\s+", " ", title)

        summary = _extract_summary(body)
        prompt = _extract_block(body, "이미지 프롬프트")
        negative = _extract_block(body, "부정 프롬프트")

        if not prompt:
            continue

        scenes.append(
            Scene(
                number=number,
                title=title,
                summary=summary,
                prompt=prompt,
                negative=negative,
            )
        )

    return scenes


def parse_markdown_file(path: Path) -> list[Scene]:
    return parse_markdown(path.read_text(encoding="utf-8", errors="replace"))


def _extract_summary(body: str) -> str:
    m = re.search(r"\*\*대본\s*요지\*\*[:：]?\s*(.+)", body)
    if not m:
        return ""
    line = m.group(1).split("\n", 1)[0].strip()
    return line


def _extract_block(body: str, label_keyword: str) -> str:
    label_iter = list(_BLOCK_LABEL_RE.finditer(body))
    for i, lm in enumerate(label_iter):
        label = re.sub(r"\s+", "", lm.group("label"))
        if label_keyword.replace(" ", "") in label:
            after = body[lm.end():]
            fm = _FENCE_RE.search(after)
            if not fm:
                continue
            next_label_pos = -1
            for nl in label_iter[i + 1:]:
                next_label_pos = nl.start() - lm.end()
                break
            if next_label_pos != -1 and fm.start() > next_label_pos:
                continue
            return fm.group(1).strip()
    return ""
