"""script.md → ProjectDoc (scene 리스트).

규칙:
- 선택: 파일 맨 위 `# 프로젝트 제목`
- 각 장면은 `## 제목` 으로 시작 (### 는 본문으로 취급)
- 본문 줄들 → TTS 내레이션 (줄바꿈은 공백으로 합침)
- `@image:` 줄 → image_prompt 필드
- `@effect:` 줄 → image_effect (none, pan_left, pan_right, pan_up, pan_down, zoom_in, zoom_out 또는 한글 별칭)
"""

from __future__ import annotations

import re
from pathlib import Path

from shortvid.motion import normalize_effect
from shortvid.schema import ProjectDoc, RenderSettings, Scene


def _slug_scene_index(i: int) -> str:
    return f"scene{i}"


def _normalize_script_meta_line(ln: str) -> str:
    """@image / @effect 메타줄: 전각 @·: 등을 반각으로 통일."""
    s = ln.strip()
    return s.replace("\uff1a", ":").replace("\uff20", "@")


def parse_script_md(text: str) -> ProjectDoc:
    text = text.replace("\r\n", "\n")
    lines = text.split("\n")

    doc_title = "Untitled"
    if lines and lines[0].startswith("# ") and not lines[0].startswith("##"):
        doc_title = lines[0][2:].strip() or doc_title

    # ## 로 분할
    chunks: list[tuple[str, list[str]]] = []
    cur_heading = ""
    cur_lines: list[str] = []

    for line in lines:
        if line.startswith("## ") and not line.startswith("###"):
            prior_has_text = cur_heading.strip() != "" or any(x.strip() for x in cur_lines)
            if prior_has_text:
                chunks.append((cur_heading or "Scene", cur_lines[:]))
            cur_heading = line[3:].strip()
            cur_lines = []
            continue
        if line.startswith("# ") and not line.startswith("##"):
            continue
        cur_lines.append(line)
    if cur_heading.strip() != "" or any(x.strip() for x in cur_lines):
        chunks.append((cur_heading or "Scene", cur_lines[:]))

    if not chunks:
        body = "\n".join(lines)
        narration = re.sub(r"\s+", " ", body).strip()
        if not narration:
            return ProjectDoc(title=doc_title, scenes=[], settings=RenderSettings())
        return ProjectDoc(
            title=doc_title,
            scenes=[
                Scene(
                    id=_slug_scene_index(1),
                    title="Scene 1",
                    narration=narration,
                )
            ],
            settings=RenderSettings(),
        )

    scenes: list[Scene] = []
    for i, (title, body_lines) in enumerate(chunks, start=1):
        image_prompt = ""
        image_effect = ""
        narr_parts: list[str] = []
        for ln in body_lines:
            s = _normalize_script_meta_line(ln)
            if s in ("---", "***", "* * *"):
                continue
            if s.lower().startswith("@image:"):
                image_prompt = s.split(":", 1)[1].strip()
                continue
            if s.lower().startswith("@effect:"):
                image_effect = normalize_effect(s.split(":", 1)[1].strip())
                continue
            narr_parts.append(ln)
        narration = re.sub(r"\s+", " ", "\n".join(narr_parts)).strip()
        sid = _slug_scene_index(i)
        scenes.append(
            Scene(
                id=sid,
                title=title,
                narration=narration,
                image_prompt=image_prompt,
                image_effect=image_effect,
            ),
        )

    return ProjectDoc(title=doc_title, scenes=scenes, settings=RenderSettings())


def script_md_to_doc(path: Path) -> ProjectDoc:
    return parse_script_md(path.read_text(encoding="utf-8"))
