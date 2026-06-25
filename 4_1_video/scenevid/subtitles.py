"""장면 단위 SRT 생성: 내레이션을 문장 단위 큐로 나누고 MP3 재생 시간에 비례 배분."""

from __future__ import annotations

import re
import shutil
from pathlib import Path

# 1080p YouTube 채널형: wisdom/fonts/GmarketSansTTFBold.ttf (libass FontName=Gmarket Sans TTF)
COMPOSE_SUBTITLE_FONT_FILE = "GmarketSansTTFBold.ttf"
COMPOSE_SUBTITLE_FONT_NAME = "Gmarket Sans TTF"
COMPOSE_SUBTITLE_FORCE_STYLE = (
    f"FontName={COMPOSE_SUBTITLE_FONT_NAME},FontSize=25,Bold=1,"
    "PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,"
    "BorderStyle=1,Outline=2,Shadow=0,MarginV=32,Alignment=2"
)


def compose_subtitle_fonts_dir() -> Path | None:
    """합성 자막용 TTF가 있는 ``wisdom/fonts`` (없으면 None)."""
    try:
        from wisdom_root import resolve_wisdom_root

        d = resolve_wisdom_root() / "fonts"
        if (d / COMPOSE_SUBTITLE_FONT_FILE).is_file():
            return d.resolve()
    except (ImportError, OSError):
        pass
    return None


def stage_compose_font_for_work(work_dir: Path) -> Path | None:
    """FFmpeg ``fontsdir``용: wisdom 폰트를 작업 폴더 ``fonts/`` 로 복사 (cwd 기준 상대 경로)."""
    src_root = compose_subtitle_fonts_dir()
    if src_root is None:
        return None
    src = src_root / COMPOSE_SUBTITLE_FONT_FILE
    dest_dir = work_dir.resolve() / "fonts"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / COMPOSE_SUBTITLE_FONT_FILE
    try:
        if not dest.is_file() or dest.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dest)
    except OSError:
        return None
    return dest_dir


def seconds_to_srt_ts(sec: float) -> str:
    if sec < 0:
        sec = 0.0
    h = int(sec // 3600)
    m = int((sec % 3600) // 60)
    s = sec % 60
    ms = int(round((s - int(s)) * 1000))
    si = int(s)
    if ms >= 1000:
        si += 1
        ms = 0
    return f"{h:02d}:{m:02d}:{si:02d},{ms:03d}"


_SENT_SPLIT = re.compile(r"(?<=[.!?。？！…])\s+")

_MAX_CHARS_PER_LINE_IN_CUE = 44


def _wrap_cue_lines(text: str, line_len: int = _MAX_CHARS_PER_LINE_IN_CUE) -> str:
    t = text.replace("\r\n", "\n").strip().replace("\n", " ")
    if len(t) <= line_len:
        return t or " "
    lines: list[str] = []
    i = 0
    while i < len(t):
        chunk_end = min(i + line_len, len(t))
        chunk = t[i:chunk_end]
        if chunk_end < len(t) and " " in chunk[:-6]:
            cut = chunk.rfind(" ")
            if cut >= line_len // 2:
                chunk = chunk[:cut]
                i += cut + 1
                lines.append(chunk.strip())
                continue
        lines.append(chunk.strip())
        i = chunk_end
    return "\n".join(x for x in lines if x) or t or " "


def _split_paragraph_into_cues(para: str, *, soft_max_chars: int = 160) -> list[str]:
    para = para.strip()
    if not para:
        return []
    sentence_bits = [_x.strip() for _x in _SENT_SPLIT.split(para)]
    sentences = [x for x in sentence_bits if x]
    if not sentences:
        sentences = [para]
    cues: list[str] = []
    buf = ""
    for s in sentences:
        if buf and len(buf) + 1 + len(s) > soft_max_chars:
            cues.append(buf)
            buf = s
        elif buf:
            buf = buf + " " + s
        else:
            buf = s
    if buf:
        cues.append(buf)

    refined: list[str] = []
    for c in cues:
        if len(c) <= soft_max_chars:
            refined.append(c)
            continue
        start = 0
        while start < len(c):
            end = min(start + soft_max_chars, len(c))
            if end < len(c):
                cut = max(c.rfind(" ", start, end), c.rfind("，", start, end), c.rfind(",", start, end))
                if cut > start + soft_max_chars // 3:
                    end = cut + 1
            piece = c[start:end].strip()
            if piece:
                refined.append(piece)
            start = end
    return refined


def _split_into_cues(narration: str) -> list[str]:
    t = narration.strip().replace("\r\n", "\n")
    if not t:
        return [" "]

    paragraphs = [p.strip() for p in re.split(r"\n\s*\n+", t) if p.strip()]
    if len(paragraphs) == 1 and "\n" in paragraphs[0] and "```" not in paragraphs[0]:
        paragraphs = [ln.strip() for ln in paragraphs[0].split("\n") if ln.strip()]

    cues: list[str] = []
    for para in paragraphs:
        cues.extend(_split_paragraph_into_cues(para))

    cues = [c for c in cues if c.strip()]
    return cues if cues else [" "]


def _cue_time_ranges(duration_sec: float, weights: list[int]) -> list[tuple[float, float]]:
    """[0, duration_sec] 구간을 weights 비례로 큐 시간으로 나눕니다."""
    dur = max(0.1, duration_sec)
    n = len(weights)
    if n <= 0:
        return [(0.0, dur)]
    ws = [max(12, int(w)) for w in weights]
    denom = sum(ws) or float(n)

    head = [(dur * (ws[i] / denom)) for i in range(n - 1)]
    used = sum(head)
    last = dur - used
    if last < 0.06:
        last = 0.06
        rescale = (dur - last) / used if used > 1e-9 else 0.0
        head = [h * rescale for h in head]

    deltas = head + [max(0.06, dur - sum(head))]
    spans: list[tuple[float, float]] = []
    t = 0.0
    for dlt in deltas:
        spans.append((t, t + dlt))
        t += dlt
    spans[-1] = (spans[-1][0], dur)
    return spans


def write_single_cue_srt(path: Path, text: str, duration_sec: float) -> None:
    """한 큐만 담은 SRT (0초~duration) — compose 시 구간별 자막 번인용."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dur = max(0.1, float(duration_sec))
    t = (text or " ").strip() or " "
    wrapped = _wrap_cue_lines(t)
    body_lines = [
        "1",
        f"{seconds_to_srt_ts(0)} --> {seconds_to_srt_ts(dur)}",
        wrapped,
        "",
    ]
    path.write_text("\n".join(body_lines), encoding="utf-8")


def write_scene_srt(
    path: Path,
    narration: str,
    duration_sec: float,
    *,
    start_sec: float = 0.0,
) -> None:
    """scene.json narration + 해당 장면 MP3 재생 길이(초)로 장면별 SRT를 씁니다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    dur_total = max(0.1, float(duration_sec))
    scene_start = float(start_sec)

    cues = _split_into_cues(narration)
    n = len(cues)
    weights = [max(14, len(c)) for c in cues]
    spans = _cue_time_ranges(dur_total, weights)

    body_lines: list[str] = []
    for ci, cue in enumerate(cues):
        lt, rt = spans[ci]
        st = scene_start + lt
        en = scene_start + rt
        if en <= st:
            en = st + 0.1

        wrapped = _wrap_cue_lines(cue)
        body_lines.extend([
            str(ci + 1),
            f"{seconds_to_srt_ts(st)} --> {seconds_to_srt_ts(en)}",
            wrapped,
            "",
        ])

    path.write_text("\n".join(body_lines), encoding="utf-8")
