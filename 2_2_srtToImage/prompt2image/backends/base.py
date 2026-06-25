"""백엔드 공통 인터페이스."""

from __future__ import annotations

from abc import ABC, abstractmethod


class ImageBackend(ABC):
    name: str = "base"
    file_ext: str = ".png"

    @abstractmethod
    def generate(self, prompt: str, *, negative: str = "") -> bytes:
        """프롬프트로 이미지를 합성해 바이트로 돌려줍니다."""
