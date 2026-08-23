# -*- coding: utf-8 -*-
"""대본 평문 ↔ STT SRT 순차 정렬 보정 (로컬)."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from srt_edit.script_io import strip_elevenlabs_tags
from srt_edit.srt_diff import SrtCue, parse_srt_cues


def _nospace(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _rehydrate(orig: str, nospace_new: str) -> str:
    """원본 공백/줄바꿈 자리를 최대한 유지하며 새 글자열을 끼워 넣음."""
    if not nospace_new:
        return orig
    chars = list(nospace_new)
    ci = 0
    out: list[str] = []
    for ch in orig:
        if ch.isspace():
            out.append(ch)
            continue
        if ci < len(chars):
            out.append(chars[ci])
            ci += 1
        # 원본보다 짧으면 나머지 글자는 루프 후 붙임
    if ci < len(chars):
        # 남는 글자 — 마지막 비공백 뒤에 붙임
        extra = "".join(chars[ci:])
        if out and not out[-1].isspace():
            out.append(extra)
        else:
            out.append(extra)
    text = "".join(out).strip()
    return text if text else nospace_new


def _best_window(
    hay: str, needle: str, *, start: int, max_slack: int = 24
) -> tuple[int, int, float]:
    """hay[start:] 근처에서 needle 과 가장 비슷한 구간 (start,end,ratio)."""
    n = len(needle)
    if n == 0 or not hay:
        return start, start, 0.0
    # exact first
    idx = hay.find(needle, start)
    if idx >= 0 and idx <= start + max(n, 40):
        return idx, idx + n, 1.0

    window = hay[start : min(len(hay), start + n + max(n * 2, max_slack * 3))]
    if not window:
        return start, start, 0.0

    best_r = 0.0
    best_a, best_b = 0, 0
    # 길이 ±slack 슬라이딩
    for L in range(max(1, n - max_slack), n + max_slack + 1):
        if L > len(window):
            break
        step = 1 if L <= 40 else max(1, L // 20)
        for i in range(0, len(window) - L + 1, step):
            frag = window[i : i + L]
            r = SequenceMatcher(None, needle, frag, autojunk=False).ratio()
            if r > best_r:
                best_r = r
                best_a, best_b = i, i + L
                if r >= 0.98:
                    break
        if best_r >= 0.98:
            break
    return start + best_a, start + best_b, best_r


def correct_srt_with_script(
    srt_text: str, script_text: str, *, min_ratio: float = 0.52
) -> tuple[str, int]:
    """대본을 기준으로 SRT 큐 본문만 교정. (인덱스·타임코드 유지)

    ``script_text`` 는 보통 ``tts/xx.json`` 의 ``text`` 필드를 이어 붙인 평문.
    Returns:
        (보정 SRT 전체, 변경된 큐 수)
    """
    cues = parse_srt_cues(srt_text)
    script_ns = _nospace(script_text)
    # json text 줄 단위(발화 단위) — 첫 큐 오인식 시 선두 발화로 교체
    script_lines = [
        strip_elevenlabs_tags(ln.strip())
        for ln in (script_text or "").splitlines()
        if ln.strip()
    ]
    if not cues or len(script_ns) < 8:
        body = srt_text if srt_text.endswith("\n") else (srt_text + "\n" if srt_text else "")
        return body, 0

    pos = 0
    line_i = 0
    changed = 0
    new_cues: list[SrtCue] = []
    for c in cues:
        needle = _nospace(c.text)
        if not needle:
            new_cues.append(c)
            continue
        a, b, ratio = _best_window(script_ns, needle, start=pos)
        # 앞에서 많이 어긋났으면 전역 재탐색 1회
        if ratio < min_ratio:
            a2, b2, r2 = _best_window(script_ns, needle, start=0, max_slack=32)
            if r2 > ratio:
                a, b, ratio = a2, b2, r2
        # 첫 큐가 STT 오인식으로 대본과 전혀 다르면 json 첫 text 발화 사용
        if ratio < min_ratio and pos == 0 and script_lines:
            first = script_lines[0]
            new_text = strip_elevenlabs_tags(first)
            if _nospace(new_text) != needle:
                changed += 1
            new_cues.append(SrtCue(index=c.index, timing=c.timing, text=new_text))
            pos = len(_nospace(first))
            line_i = 1
            continue
        if ratio >= min_ratio and b > a:
            matched = script_ns[a:b]
            new_text = strip_elevenlabs_tags(_rehydrate(c.text, matched))
            if _nospace(new_text) != needle:
                changed += 1
            new_cues.append(SrtCue(index=c.index, timing=c.timing, text=new_text))
            pos = b
            while line_i < len(script_lines) and pos >= sum(
                len(_nospace(script_lines[k])) for k in range(line_i + 1)
            ):
                line_i += 1
        else:
            cleaned = strip_elevenlabs_tags(c.text)
            if cleaned != c.text.strip():
                changed += 1
                new_cues.append(SrtCue(index=c.index, timing=c.timing, text=cleaned))
            else:
                new_cues.append(c)
            # 대략 전진
            pos = min(len(script_ns), pos + max(1, len(needle) // 2))

    blocks: list[str] = []
    for c in new_cues:
        text = strip_elevenlabs_tags(c.text)
        blocks.append(f"{c.index}\n{c.timing}\n{text}".rstrip() + "\n")
    body = "\n".join(blocks)
    if not body.endswith("\n"):
        body += "\n"
    return body, changed
