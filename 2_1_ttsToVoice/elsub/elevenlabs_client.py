# -*- coding: utf-8 -*-
"""2_1_ttsToVoice: ElevenLabs TTS HTTP 호출 + MP3 병합(ffmpeg/바이너리)."""

from __future__ import annotations

import http.client
import json
import re
import shutil
import ssl
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote

DEFAULT_HOST = "api.elevenlabs.io"
# ElevenLabs MP3 최소 크기(빈·잘린 응답 거부). ID3 헤더만 있는 경우도 걸러냄.
_MIN_MP3_BYTES = 256
# ElevenLabs 세그먼트와 동일하게 맞춤 (경계 ID3·DTS 꼬임 방지용 재인코딩)
_FFMPEG_MP3_ENCODE_ARGS = ["-c:a", "libmp3lame", "-b:a", "128k", "-ar", "44100", "-ac", "1"]

# 줄 끝 [breathes] (파트 경계 ``[short pause]`` 조합은 아래 1.0s 유지)
LINE_BREATH_BREAK = "0.5s"

_BRACKET_TAG_RE = re.compile(r"\[[^\]]*\]", re.IGNORECASE)
_BREAK_TAG_RE = re.compile(r"<break\s+[^>]*?/?>", re.IGNORECASE)
# 숫자·라틴·히라가나/가타카나·CJK·한글 — 구두점·따옴표·말줄임만 있으면 비낭독
_SPEAKABLE_RE = re.compile(
    r"[0-9A-Za-z\u00C0-\u024F\u3040-\u30FF\u3400-\u9FFF\uAC00-\uD7AF]"
)


def strip_tts_tags(text: str) -> str:
    """길이 추정·SRT용: 대괄호 태그를 제거한 낭독 텍스트."""
    return _BRACKET_TAG_RE.sub("", text)


def prepare_tts_for_api(text: str) -> str:
    """ElevenLabs API용 텍스트. ``[breathes]`` 등은 SSML ``<break>`` 로 변환합니다.

    맨 앞 ``<break>`` 는 첫 음절이 작거나 깨지는 경우가 있어 ``leading_pause_ms``·
    ``prepend_silence_mp3`` 로 처리하고, 여기서는 선행 break 를 제거합니다.
    """
    s = text.strip()
    s = re.sub(
        r"^\s*(?:<break\s+time=\"[^\"]+\"\s*/>\s*)+",
        "",
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\[short pause\]\s*\[breathes\]\s*\[continues\]",
        '<break time="1.0s" />',
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(
        r"\[short pause\]\s*\[breathes\]",
        '<break time="1.0s" />',
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\[short pause\]", '<break time="0.4s" />', s, flags=re.IGNORECASE)
    s = re.sub(
        r"\[breathes\]",
        f'<break time="{LINE_BREATH_BREAK}" />',
        s,
        flags=re.IGNORECASE,
    )
    s = re.sub(r"\[continues\]", "", s, flags=re.IGNORECASE)
    s = _BRACKET_TAG_RE.sub("", s)
    return s.strip()


def api_text_has_speech(prepared: str) -> bool:
    """API용 준비 문자열에 실제 낭독할 글자가 있는지 (break·구두점만이면 False)."""
    s = _BREAK_TAG_RE.sub(" ", prepared or "")
    return bool(_SPEAKABLE_RE.search(s))


def silence_sec_from_prepared(prepared: str, *, default_sec: float = 0.5) -> float:
    """``<break time=\"Ns\"/>`` 합산 초. 없으면 default."""
    times = re.findall(
        r'<break\s+time="([0-9]*\.?[0-9]+)s"', prepared or "", flags=re.IGNORECASE
    )
    if times:
        return max(0.05, min(3.0, sum(float(t) for t in times)))
    return max(0.05, min(3.0, float(default_sec)))


def _looks_like_mp3(data: bytes) -> bool:
    if len(data) < _MIN_MP3_BYTES:
        return False
    if data[:3] == b"ID3":
        return True
    # MPEG frame sync (mp3)
    return data[0] == 0xFF and (data[1] & 0xE0) == 0xE0


def synthesize_mp3(
    api_key: str,
    voice_id: str,
    text: str,
    *,
    model_id: str = "eleven_multilingual_v2",
    timeout: int = 120,
    retries: int = 3,
) -> bytes:
    plain = prepare_tts_for_api(text)
    if not plain or not api_text_has_speech(plain):
        raise ValueError("합성할 TTS 텍스트가 비어 있습니다.")
    vid = quote(voice_id, safe="-._~")
    path = f"/v1/text-to-speech/{vid}"
    # ensure_ascii=True: 일부 환경에서 HTTP 스택이 본문을 ASCII로 다루는 문제 회피 (API는 \\u 이스케이프 허용)
    payload = json.dumps(
        {"text": plain, "model_id": model_id},
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("utf-8")

    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json; charset=utf-8",
        "Accept": "audio/mpeg",
        "Content-Length": str(len(payload)),
        "Connection": "close",
    }

    last_err: Exception | None = None
    attempts = max(1, int(retries))
    for attempt in range(1, attempts + 1):
        ctx = ssl.create_default_context()
        conn = http.client.HTTPSConnection(DEFAULT_HOST, timeout=timeout, context=ctx)
        try:
            conn.request("POST", path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read()
            if resp.status == 429 or resp.status >= 500:
                err = data.decode("utf-8", errors="replace").strip()
                last_err = RuntimeError(
                    f"ElevenLabs API 오류 {resp.status}: {err or '(empty)'}"
                )
            elif resp.status >= 400:
                err = data.decode("utf-8", errors="replace")
                raise RuntimeError(f"ElevenLabs API 오류 {resp.status}: {err}")
            elif not _looks_like_mp3(data):
                preview = data[:120].decode("utf-8", errors="replace").strip()
                last_err = RuntimeError(
                    f"ElevenLabs 빈·비정상 MP3 응답 ({len(data)} bytes)"
                    + (f": {preview}" if preview else "")
                )
            else:
                return data
        except (TimeoutError, OSError, http.client.HTTPException) as e:
            last_err = e
        finally:
            try:
                conn.close()
            except Exception:
                pass
        if attempt < attempts:
            time.sleep(min(8.0, 1.5 * attempt))
    raise RuntimeError(
        f"음성 합성 실패 ({attempts}회 시도): {last_err}"
    ) from last_err


def write_silence_mp3(mp3_path: Path, silence_sec: float) -> None:
    """무음만 있는 MP3를 만듭니다 (태그만 있는 줄·선행 쉼 전용)."""
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg 가 필요합니다. 무음 MP3 생성을 위해 PATH에 ffmpeg 를 넣으세요."
        )
    silence_sec = max(0.05, min(3.0, float(silence_sec)))
    out = Path(mp3_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    kw: dict = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
    r = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-t",
            f"{silence_sec:.3f}",
            "-i",
            "anullsrc=r=44100:cl=mono",
            *_FFMPEG_MP3_ENCODE_ARGS,
            str(out),
        ],
        **kw,
    )
    if r.returncode != 0 or not out.is_file() or out.stat().st_size < _MIN_MP3_BYTES:
        msg = (r.stderr or r.stdout or "").strip()
        raise RuntimeError(f"무음 MP3 생성 실패: {msg or r.returncode}")


def prepend_silence_mp3(mp3_path: Path, silence_sec: float) -> None:
    """MP3 앞에 무음을 붙입니다 (파트 첫 줄 선행 쉼·호흡용).

    lavfi+concat 는 샘플레이트/채널 불일치로 Windows에서 빈 stderr·큰 exit code로
    실패하는 경우가 있어 ``adelay`` 단일 입력 필터를 우선 사용합니다.
    """
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        raise RuntimeError(
            "ffmpeg 가 필요합니다. 선행 쉼 처리를 위해 PATH에 ffmpeg 를 넣으세요."
        )
    silence_sec = max(0.05, min(3.0, float(silence_sec)))
    delay_ms = max(50, int(round(silence_sec * 1000)))
    src = Path(mp3_path).resolve()
    if not src.is_file() or src.stat().st_size < _MIN_MP3_BYTES:
        raise RuntimeError(
            f"선행 무음 대상 MP3가 비어 있거나 없습니다 "
            f"({src.stat().st_size if src.is_file() else 0} bytes): {src}"
        )
    tmp = src.with_suffix(".prepend_tmp.mp3")
    kw: dict = dict(
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
    )
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    # 채널 수와 무관하게 동작: all=1 로 전 채널 동일 delay
    af = (
        f"adelay=delays={delay_ms}:all=1,"
        f"aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono"
    )
    r = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-af",
            af,
            *_FFMPEG_MP3_ENCODE_ARGS,
            str(tmp),
        ],
        **kw,
    )
    if r.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < _MIN_MP3_BYTES:
        # 폴백: lavfi 무음 + aformat 정규화 후 concat
        r2 = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "lavfi",
                "-t",
                f"{silence_sec:.3f}",
                "-i",
                "anullsrc=r=44100:cl=mono",
                "-i",
                str(src),
                "-filter_complex",
                (
                    "[0:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[s];"
                    "[1:a]aformat=sample_fmts=fltp:sample_rates=44100:channel_layouts=mono[m];"
                    "[s][m]concat=n=2:v=0:a=1[out]"
                ),
                "-map",
                "[out]",
                *_FFMPEG_MP3_ENCODE_ARGS,
                str(tmp),
            ],
            **kw,
        )
        if r2.returncode != 0 or not tmp.is_file() or tmp.stat().st_size < _MIN_MP3_BYTES:
            msg = (r2.stderr or r.stderr or r2.stdout or r.stdout or "").strip()
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError(
                f"선행 무음 삽입 실패: {msg or f'exit adelay={r.returncode} concat={r2.returncode}'}"
            )
    tmp.replace(src)


def concat_mp3_files(parts: list[bytes], out_path: str) -> None:
    """바이너리 이어붙이기 (ffmpeg 없을 때 대안)."""
    p = Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as w:
        for blob in parts:
            w.write(blob)


def concat_mp3_files_binary_from_paths(
    segment_paths: list[Path],
    out_path: Path,
    *,
    chunk_size: int = 1024 * 1024,
) -> None:
    """MP3 파일들을 순서대로 바이트 스트림으로 이어붙입니다 (ffmpeg 실패 시 폴백)."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not segment_paths:
        raise ValueError("병합할 파일이 없습니다.")
    with out_path.open("wb") as w:
        for sp in segment_paths:
            p = Path(sp)
            if not p.is_file():
                raise FileNotFoundError(str(p))
            with p.open("rb") as r:
                while True:
                    chunk = r.read(chunk_size)
                    if not chunk:
                        break
                    w.write(chunk)


def _write_ffmpeg_concat_list(segment_paths: list[Path], out_path: Path) -> Path:
    """concat demuxer용 filelist.txt 경로를 반환합니다 (호출부에서 삭제)."""
    import tempfile

    out_path = Path(out_path)
    out_dir = out_path.parent.resolve()
    lines: list[str] = []
    for sp in segment_paths:
        sp = Path(sp).resolve()
        if not sp.is_file():
            raise FileNotFoundError(str(sp))
        try:
            rel = sp.relative_to(out_dir)
            esc = rel.as_posix().replace("'", "'\\''")
        except ValueError:
            esc = sp.as_posix().replace("'", "'\\''")
        lines.append(f"file '{esc}'")

    with tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".txt",
        delete=False,
        encoding="utf-8",
        newline="\n",
        dir=str(out_dir),
    ) as tf:
        tf.write("\n".join(lines) + "\n")
        return Path(tf.name)


def concat_mp3_files_ffmpeg(segment_paths: list[Path], out_path: Path) -> None:
    """ffmpeg concat + libmp3lame 재인코딩으로 MP3를 병합합니다.

    `-c copy`는 MP3 경계에서 DTS 비단조·중간 ID3로 클릭/길이 어긋남이 날 수 있어
    처음부터 디코드 후 한 번에 인코딩합니다. 실패 시 RuntimeError (상위에서 바이너리 폴백).
    """
    import subprocess
    import sys

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not segment_paths:
        raise ValueError("병합할 세그먼트가 없습니다.")

    list_path = _write_ffmpeg_concat_list(segment_paths, out_path)
    kw: dict = dict(capture_output=True, text=True, timeout=3600)
    if sys.platform == "win32":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]

    try:
        r = subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_path),
                *_FFMPEG_MP3_ENCODE_ARGS,
                str(out_path),
            ],
            **kw,
        )
        if r.returncode != 0:
            msg = (r.stderr or r.stdout or "").strip()
            raise RuntimeError(f"ffmpeg 병합 실패: {msg or 'exit ' + str(r.returncode)}")
    finally:
        try:
            list_path.unlink(missing_ok=True)
        except OSError:
            pass
