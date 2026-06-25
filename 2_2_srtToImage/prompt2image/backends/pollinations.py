"""Pollinations.ai 무키 이미지 백엔드.

가격·키 없이 사용 가능. 모델: flux(기본), turbo 등.
부정 프롬프트는 본문에 'Avoid: ...' 형태로 합쳐 보냅니다.
"""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from prompt2image.backends.base import ImageBackend


class PollinationsBackend(ImageBackend):
    name = "pollinations"
    file_ext = ".png"

    def __init__(
        self,
        *,
        model: str = "flux",
        width: int = 1024,
        height: int = 1024,
        seed: int | None = None,
        nologo: bool = True,
        timeout: int = 180,
    ) -> None:
        self.model = model
        self.width = width
        self.height = height
        self.seed = seed
        self.nologo = nologo
        self.timeout = timeout

    def generate(self, prompt: str, *, negative: str = "") -> bytes:
        text = prompt.strip()
        if negative.strip():
            text = f"{text}\n\nAvoid: {negative.strip()}"

        encoded = urllib.parse.quote(text, safe="")
        params = {
            "width": str(self.width),
            "height": str(self.height),
            "model": self.model,
            "nologo": "true" if self.nologo else "false",
        }
        if self.seed is not None:
            params["seed"] = str(self.seed)
        qs = urllib.parse.urlencode(params)
        url = f"https://image.pollinations.ai/prompt/{encoded}?{qs}"

        req = urllib.request.Request(
            url,
            headers={
                "Accept": "image/png,image/*;q=0.8",
                "User-Agent": "prompt2image/0.1",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read()
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")[:400]
            raise RuntimeError(f"Pollinations 오류 {e.code}: {err}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"Pollinations 연결 실패: {e.reason}") from e

        if len(data) < 256:
            raise RuntimeError("Pollinations 응답이 비정상입니다(이미지가 너무 작습니다).")
        return data
