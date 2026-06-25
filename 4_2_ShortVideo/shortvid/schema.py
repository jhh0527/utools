"""scene.json 로드·저장 및 기본 검증."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from shortvid.motion import normalize_effect

DEFAULT_OUTRO_TEXT = ""


def resolve_outro_text(raw: str | None) -> str:
    """엔딩 자막. 비어 있으면 기본값(공백·자막 없음)."""
    s = (raw or "").strip()
    return s if s else DEFAULT_OUTRO_TEXT


@dataclass
class RenderSettings:
    width: int = 1080
    height: int = 1920
    fps: int = 30
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    youtube_faststart: bool = True
    # 장면에 image_effect 없을 때 (none | pan_left | pan_right | pan_up | pan_down | zoom_in | zoom_out)
    default_image_effect: str = "none"
    # 본편 끝: 마지막 화면 유지 + 감사 자막 (무음)
    outro_enabled: bool = False
    outro_text: str = ""  # 비우면 resolve_outro_text → DEFAULT_OUTRO_TEXT
    outro_duration_sec: float = 3.0


@dataclass
class Scene:
    id: str
    title: str
    narration: str
    image_prompt: str = ""
    # 상대경로(project root 기준 권장)
    image_file: str = ""
    audio_file: str = ""
    subtitle_file: str = ""
    # 이미지 모션: none, pan_left, pan_right, pan_up, pan_down, zoom_in, zoom_out (또는 script @effect:)
    image_effect: str = ""

    def resolved_paths(self, root: Path) -> tuple[Path, Path, Path]:
        img = root / (self.image_file or f"images/{self.id}.png")
        aud = root / (self.audio_file or f"audio/{self.id}.mp3")
        sub = root / (self.subtitle_file or f"subtitles/{self.id}.srt")
        return img, aud, sub


@dataclass
class ProjectDoc:
    title: str
    scenes: list[Scene]
    settings: RenderSettings = field(default_factory=RenderSettings)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "scenes": [
                {
                    "id": s.id,
                    "title": s.title,
                    "narration": s.narration,
                    "image_prompt": s.image_prompt,
                    "image_file": s.image_file or f"images/{s.id}.png",
                    "audio_file": s.audio_file or f"audio/{s.id}.mp3",
                    "subtitle_file": s.subtitle_file or f"subtitles/{s.id}.srt",
                    "image_effect": (s.image_effect or "").strip(),
                }
                for s in self.scenes
            ],
            "settings": asdict(self.settings),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> ProjectDoc:
        scenes_raw = data.get("scenes") or []
        scenes: list[Scene] = []
        for item in scenes_raw:
            raw_eff = item.get("image_effect")
            if raw_eff is None or not str(raw_eff).strip():
                ieff: str = ""
            else:
                ieff = normalize_effect(str(raw_eff))
            scenes.append(
                Scene(
                    id=str(item["id"]),
                    title=str(item.get("title") or item["id"]),
                    narration=str(item.get("narration") or "").strip(),
                    image_prompt=str(item.get("image_prompt") or ""),
                    image_file=str(item.get("image_file") or ""),
                    audio_file=str(item.get("audio_file") or ""),
                    subtitle_file=str(item.get("subtitle_file") or ""),
                    image_effect=ieff,
                )
            )
        st = data.get("settings") or {}
        settings = RenderSettings(
            width=int(st.get("width", 1080)),
            height=int(st.get("height", 1920)),
            fps=int(st.get("fps", 30)),
            video_codec=str(st.get("video_codec", "libx264")),
            audio_codec=str(st.get("audio_codec", "aac")),
            youtube_faststart=bool(st.get("youtube_faststart", True)),
            default_image_effect=normalize_effect(str(st.get("default_image_effect") or "none")),
            outro_enabled=bool(st.get("outro_enabled", True)),
            outro_text=str(st.get("outro_text", "")),
            outro_duration_sec=float(st.get("outro_duration_sec", 3.0)),
        )
        return ProjectDoc(
            title=str(data.get("title") or "Untitled"),
            scenes=scenes,
            settings=settings,
        )


def load_project(path: Path) -> ProjectDoc:
    data = json.loads(path.read_text(encoding="utf-8"))
    return ProjectDoc.from_dict(data)


def save_project(doc: ProjectDoc, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc.to_dict(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
