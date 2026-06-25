"""OpenAI Image API 백엔드 (선택). OPENAI_API_KEY 필요."""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request

from prompt2image.backends.base import ImageBackend


class OpenAIImageBackend(ImageBackend):
    name = "openai"
    file_ext = ".png"

    def __init__(
        self,
        *,
        model: str = "gpt-image-1",
        size: str = "1024x1024",
        quality: str = "high",
        timeout: int = 180,
    ) -> None:
        self.model = model
        self.size = size
        self.quality = quality
        self.timeout = timeout

    def generate(self, prompt: str, *, negative: str = "") -> bytes:
        key = os.environ.get("OPENAI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("환경 변수 OPENAI_API_KEY가 설정되어 있지 않습니다.")

        text = prompt.strip()
        if negative.strip():
            text = f"{text}\n\nAvoid: {negative.strip()}"

        body = json.dumps(
            {
                "model": self.model,
                "prompt": text,
                "size": self.size,
                "n": 1,
                "quality": self.quality,
            },
            ensure_ascii=False,
        ).encode("utf-8")

        req = urllib.request.Request(
            "https://api.openai.com/v1/images/generations",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {key}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"OpenAI 오류 {e.code}: {err}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"OpenAI 연결 실패: {e.reason}") from e

        try:
            b64 = payload["data"][0]["b64_json"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError(f"OpenAI 응답 형식이 예상과 다릅니다: {payload}") from e
        return base64.b64decode(b64)
