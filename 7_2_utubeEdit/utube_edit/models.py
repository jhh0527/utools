from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class SceneSegment:
    index: int
    start_sec: float
    end_sec: float
    thumb_path: Path | None = None

    @property
    def duration_sec(self) -> float:
        return max(0.0, self.end_sec - self.start_sec)
