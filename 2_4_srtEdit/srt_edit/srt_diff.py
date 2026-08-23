# -*- coding: utf-8 -*-
"""원본 SRT vs 보정 SRT — 추출·검증·변경 줄 위치(노란 표시용)."""

from __future__ import annotations

import re
from dataclasses import dataclass


_TC_RE = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}"
)
# Genspark 한 줄 형식: "214 00:13:53,740 --> 00:13:56,640 그가 …"
_ONELINE_CUE_RE = re.compile(
    r"^(\d+)\s+"
    r"(\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})\s+"
    r"(\S.*)$"
)
# start/end 구분자 — 단독 줄이든 큐와 같은 줄이든, 사이 본문을 보정 SRT 로 취급
# 출력 마커: 줄 단위 start / end (같은 줄 끝 "… end" 도 허용)
_START_LINE_RE = re.compile(r"(?im)^\s*(?:==\s*)?start(?:\s*==)?\s*$")
# ``start 1 00:00:…`` / ``start1 …`` — start 가 첫 큐와 같은 줄
_START_INLINE_PREFIX_RE = re.compile(
    r"(?im)^(\s*)(?:==\s*)?start(?:\s*==)?(?:[ \t]+|(?=\d))(?=\d)"
)
_END_LINE_RE = re.compile(r"(?im)^\s*(?:==\s*)?end(?:\s*==)?\s*$")
_END_INLINE_RE = re.compile(r"(?i)\s+(?:==\s*)?end(?:\s*==)?\s*$")
# start … end — start 다음 같은 줄에 큐가 와도 됨, end 는 줄 끝 첨부도 허용
_START_END_RE = re.compile(
    r"(?is)(?:^|\n)\s*(?:==\s*)?start(?:\s*==)?\s*"
    r"(.*?)\s*"
    r"(?:==\s*)?end(?:\s*==)?\s*(?:\n|$)"
)
# start 만 있고 end 없음 — start 다음부터 끝까지
_START_ONLY_RE = re.compile(
    r"(?is)(?:^|\n)\s*(?:==\s*)?start(?:\s*==)?\s*(.*)\Z"
)
_FENCE_RE = re.compile(r"```(?:srt)?\s*(.*?)```", flags=re.S | re.I)
_TRAILING_END_RE = re.compile(r"(?is)(?:\n|\s)*(?:==\s*)?end(?:\s*==)?\s*$")


def slice_between_start_end(text: str) -> list[str]:
    """``start``~``end`` 구분자 사이 본문만 모은다 (줄 분리 여부와 무관)."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for m in _START_END_RE.finditer(raw):
        body = (m.group(1) or "").strip()
        if body:
            out.append(body)
    if out:
        return out
    m_only = _START_ONLY_RE.search(raw)
    if m_only:
        body = _strip_trailing_end_marker(m_only.group(1) or "").strip()
        if body:
            out.append(body)
    return out


def normalize_inline_start_marker(text: str) -> str:
    """``start 1 00:…`` → ``start`` + 다음 줄 큐 (파싱 편의)."""
    raw = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for ln in raw.split("\n"):
        m = _START_INLINE_PREFIX_RE.match(ln)
        if m:
            rest = ln[m.end() :].strip()
            out.append("start")
            if rest:
                out.append(rest)
            continue
        out.append(ln)
    return "\n".join(out)


def normalize_start_end_boundaries(text: str) -> str:
    """인라인 start/end 를 파싱하기 쉽게 정리 (추출용, 모델 출력 강제 아님)."""
    raw = normalize_inline_start_marker(text or "")
    raw = raw.replace("\r\n", "\n").replace("\r", "\n")
    out: list[str] = []
    for ln in raw.split("\n"):
        s = ln.strip()
        if _END_LINE_RE.match(s):
            out.append("end")
            continue
        if _END_INLINE_RE.search(s) and not _END_LINE_RE.match(s):
            body = _END_INLINE_RE.sub("", s).rstrip()
            if body:
                out.append(body)
            out.append("end")
            continue
        out.append(ln)
    return "\n".join(out)


def expand_oneline_srt(text: str) -> str:
    """한 줄 큐를 표준 3줄(+빈줄) SRT 로 펼친다."""
    raw = normalize_start_end_boundaries(text)
    out: list[str] = []
    for ln in raw.split("\n"):
        s = ln.strip()
        if _START_LINE_RE.match(s) or _END_LINE_RE.match(s):
            out.append(s.lower() if s.lower() in ("start", "end") else s)
            continue
        # "… 있었다. end" 는 normalize 에서 이미 분리됐어야 함
        end_here = bool(_END_INLINE_RE.search(s)) and not _END_LINE_RE.match(s)
        if end_here:
            s = _END_INLINE_RE.sub("", s).rstrip()
        m = _ONELINE_CUE_RE.match(s)
        if m:
            out.append(m.group(1))
            out.append(m.group(2).strip())
            out.append(m.group(3).strip())
            out.append("")
            if end_here:
                out.append("end")
        else:
            out.append(ln)
            if end_here and not _END_LINE_RE.match(ln.strip()):
                if out:
                    out[-1] = _END_INLINE_RE.sub("", out[-1]).rstrip()
                out.append("end")
    return "\n".join(out)


def has_start_marker(text: str) -> bool:
    t = text or ""
    if _START_LINE_RE.search(t):
        return True
    return bool(_START_INLINE_PREFIX_RE.search(t))


def has_end_marker(text: str) -> bool:
    """end 단독 줄 또는 큐 줄 끝 ``… end`` (페이지 하단 UI 문구는 무시)."""
    t = text or ""
    if _END_LINE_RE.search(t):
        return True
    lines = [ln for ln in (t.splitlines()) if ln.strip()]
    # 하단 "Claude …" 등 때문에 절대 마지막 줄만 보면 실패함 → 끝쪽 SRT 구간 검사
    for ln in reversed(lines[-120:]):
        s = ln.strip()
        if _END_LINE_RE.match(s) or _END_INLINE_RE.search(s):
            return True
    return False


def has_start_end_markers(text: str) -> bool:
    """start 와 end 가 모두 있으면 True (end 는 줄 끝 첨부도 인정)."""
    return has_start_marker(text) and has_end_marker(text)


def reaches_last_original_cue(text: str, original: str | None) -> bool:
    """응답(한 줄 형식)에 원본 마지막 큐가 보이면 True.

    프롬프트의 여러 줄 SRT(번호 단독 줄)와 구분하기 위해
    ``402 00:26:…`` 한 줄 형식만 센다.
    """
    orig = parse_srt_cues(original or "")
    if not orig:
        return False
    last = (orig[-1].index or "").strip()
    if not last:
        return False
    t = text or ""
    # \s 대신 공백/탭만 — 여러 줄 SRT의 "402\n00:26" 오인 방지
    hits = len(
        re.findall(
            rf"(?m)^\s*(?:(?:==\s*)?start(?:\s*==)?[ \t]+)?"
            rf"{re.escape(last)}[ \t]+\d{{1,2}}:\d{{2}}:",
            t,
        )
    )
    return hits >= 1


def _strip_trailing_end_marker(body: str) -> str:
    """본문 끝의 end / ==end== 마커 제거."""
    s = (body or "").rstrip()
    s = _TRAILING_END_RE.sub("", s).rstrip()
    lines = s.split("\n")
    while lines and _END_LINE_RE.match(lines[-1]):
        lines.pop()
    if lines:
        lines[-1] = re.sub(
            r"(?i)\s+(?:==\s*)?end(?:\s*==)?\s*$", "", lines[-1]
        ).rstrip()
    # 선행 start 줄 제거
    while lines and _START_LINE_RE.match(lines[0]):
        lines.pop(0)
    return "\n".join(lines).strip()


@dataclass(frozen=True)
class SrtCue:
    index: str
    timing: str
    text: str


def cues_to_srt(cues: list[SrtCue]) -> str:
    blocks: list[str] = []
    for c in cues:
        blocks.append(f"{c.index}\n{c.timing}\n{c.text}".rstrip() + "\n")
    body = "\n".join(blocks)
    return body if body.endswith("\n") else body + "\n"


def parse_srt_cues(text: str) -> list[SrtCue]:
    raw = expand_oneline_srt(text or "").replace("\r\n", "\n").replace("\r", "\n")
    # start/end 마커 줄은 큐 파싱에서 제외 (바로 다음 큐와 붙지 않게)
    kept: list[str] = []
    for ln in raw.split("\n"):
        if _START_LINE_RE.match(ln) or _END_LINE_RE.match(ln):
            if kept and kept[-1].strip():
                kept.append("")
            continue
        kept.append(ln)
    raw = "\n".join(kept).strip()
    if not raw:
        return []
    blocks = re.split(r"\n\s*\n", raw)
    cues: list[SrtCue] = []
    for block in blocks:
        lines = [ln.rstrip() for ln in block.split("\n")]
        while lines and not lines[0].strip():
            lines.pop(0)
        while lines and not lines[-1].strip():
            lines.pop()
        if not lines:
            continue
        if len(lines) == 1:
            m = _ONELINE_CUE_RE.match(lines[0].strip())
            if m:
                cues.append(
                    SrtCue(
                        index=m.group(1),
                        timing=m.group(2).strip(),
                        text=m.group(3).strip(),
                    )
                )
            continue
        if len(lines) < 2:
            continue
        idx = lines[0].strip()
        timing = lines[1].strip()
        if _TC_RE.match(idx) and not _TC_RE.match(timing):
            timing = idx
            idx = str(len(cues) + 1)
            body = "\n".join(lines[1:])
        elif not _TC_RE.match(timing):
            m = _ONELINE_CUE_RE.match(idx)
            if m:
                cues.append(
                    SrtCue(
                        index=m.group(1),
                        timing=m.group(2).strip(),
                        text=m.group(3).strip(),
                    )
                )
            continue
        else:
            body = "\n".join(lines[2:])
        cues.append(SrtCue(index=idx, timing=timing, text=body))
    return cues


def normalize_timing(timing: str) -> str:
    """타임코드 비교용 키 (공백·콤마/점 정규화)."""
    t = (timing or "").strip().lower().replace(".", ",")
    return re.sub(r"\s+", "", t)


def _trim_to_srt_body(text: str) -> str:
    """앞뒤 잡문 제거 — 첫 큐(번호·타임코드·한 줄 큐)부터."""
    lines = expand_oneline_srt(text or "").replace("\r\n", "\n").replace("\r", "\n").split(
        "\n"
    )
    start = 0
    for i, ln in enumerate(lines):
        s = ln.strip()
        if not s:
            continue
        if s.isdigit() or _TC_RE.match(s) or _ONELINE_CUE_RE.match(s):
            start = i
            break
    return "\n".join(lines[start:]).strip()


def _candidate_bodies(
    text: str, *, original: str | None = None, log_detail: bool = True
) -> list[str]:
    from srt_edit import diag_log

    # 1) start~end 구분자 사이 = 보정 SRT (줄 분리 여부 무관)
    delim_bodies = slice_between_start_end(text or "")
    raw = normalize_start_end_boundaries(text or "")
    s = expand_oneline_srt(raw)
    out: list[str] = []

    def add(body: str) -> None:
        body = _strip_trailing_end_marker(expand_oneline_srt(body))
        if "-->" in body and parse_srt_cues(body):
            out.append(body)

    for body in delim_bodies:
        add(body)
    # 정규화본에서도 한 번 더 (중복은 아래에서 큐 수로 걸러짐)
    if not out:
        for src in (raw, s):
            for m in _START_END_RE.finditer(src):
                add(m.group(1) or "")
            if not out:
                m_only = _START_ONLY_RE.search(src)
                if m_only and "-->" in (m_only.group(1) or ""):
                    add(m_only.group(1) or "")

    start_end_n = len(out)
    cue_counts = [len(parse_srt_cues(b)) for b in out]
    if cue_counts and log_detail:
        diag_log.log(
            f"추출후보 start/end블록={start_end_n} 큐수={cue_counts}"
        )

    orig_n = len(parse_srt_cues(original or "")) if original else 0
    if out and orig_n > 0:
        thr = max(10, (orig_n + 1) // 2)
        # 원본의 절반 이상 큐가 있는 블록만 — MD 예시(2큐) 제외
        big = [b for b in out if len(parse_srt_cues(b)) >= thr]
        if big:
            if log_detail:
                diag_log.log(
                    f"추출후보 큰블록만 유지 thr>={thr} → "
                    f"{[len(parse_srt_cues(b)) for b in big]}"
                )
            return big
        # 큰 블록이 없으면 가장 큰 것만
        out.sort(key=lambda b: len(parse_srt_cues(b)), reverse=True)
        if len(parse_srt_cues(out[0])) >= 10:
            if log_detail:
                diag_log.log(
                    f"추출후보 큰블록없음 → 최대큐만 사용 "
                    f"n={len(parse_srt_cues(out[0]))}"
                )
            return [out[0]]
        if log_detail:
            diag_log.log(
                f"추출후보 전부 작음(원본{orig_n}) → 예시·잘림 의심 큐={cue_counts}"
            )

    if out:
        return out

    for m in _FENCE_RE.finditer(s):
        add(m.group(1) or "")
    if out:
        if log_detail:
            diag_log.log(
                f"추출후보 fence블록={len(out)} "
                f"큐={[len(parse_srt_cues(b)) for b in out]}"
            )
        return out

    if "-->" in s:
        add(_trim_to_srt_body(s))
        if out and log_detail:
            diag_log.log(
                f"추출후보 trim본문 큐={len(parse_srt_cues(out[0]))}"
            )
    return out


def changed_cue_count(body: str, original: str | None) -> int:
    """원본과 본문이 다른 큐 개수 (타임코드 기준)."""
    if not original:
        return 0
    o_by_t = {
        normalize_timing(c.timing): (c.text or "").strip()
        for c in parse_srt_cues(original)
    }
    n = 0
    for c in parse_srt_cues(body):
        ot = o_by_t.get(normalize_timing(c.timing))
        if ot is None or ot != (c.text or "").strip():
            n += 1
    return n


def cue_count_fit(n: int, orig_n: int, *, loose: bool = False) -> bool:
    """원본 대비 허용 큐 수. 기본 ±8%(최소 5), loose 면 ±15%(최소 8)."""
    if orig_n <= 0:
        return n > 0
    frac = 0.15 if loose else 0.08
    tol = max(8 if loose else 5, int(orig_n * frac))
    return abs(n - orig_n) <= tol


def align_body_to_original(body: str, original: str | None) -> str:
    """여러 SRT가 이어 붙은 본문에서 원본 타임코드에 맞는 한 구간만 고른다.

    페이지에 MD 예시·원본 첨부·응답이 중복되면 큐가 원본의 2~3배가 된다.
    원본과 타임코드가 연속 일치하는 구간을 찾고, 본문 변경·뒤쪽 구간을 우선한다.
    """
    if not original or not body:
        return body
    orig = parse_srt_cues(original)
    corr = parse_srt_cues(body)
    if not orig or not corr:
        return body
    orig_n = len(orig)

    def _looks_like_md_head(cues: list[SrtCue]) -> bool:
        if not cues:
            return False
        return (
            normalize_timing(cues[0].timing) != normalize_timing(orig[0].timing)
            and "안녕하세요" in (cues[0].text or "")
        )

    if cue_count_fit(len(corr), orig_n) and not _looks_like_md_head(corr):
        return cues_to_srt(corr)

    from collections import defaultdict

    pos: dict[str, list[int]] = defaultdict(list)
    for i, c in enumerate(corr):
        pos[normalize_timing(c.timing)].append(i)

    best = (-1, -1, -1, 0)  # match, diffs, corr_i, orig_j
    for j in range(min(8, orig_n)):
        t = normalize_timing(orig[j].timing)
        for i in pos.get(t, []):
            m = 0
            diffs = 0
            while j + m < orig_n and i + m < len(corr):
                if normalize_timing(corr[i + m].timing) != normalize_timing(
                    orig[j + m].timing
                ):
                    break
                if (corr[i + m].text or "").strip() != (orig[j + m].text or "").strip():
                    diffs += 1
                m += 1
            key = (m, diffs, i)
            if key > (best[0], best[1], best[2]):
                best = (m, diffs, i, j)

    match, diffs, i, j = best
    min_match = max(1, int(orig_n * 0.70))
    if match < min_match:
        return cues_to_srt(corr)

    # 앞쪽 큐가 잘렸으면 원본으로 채우고, 본문은 매칭 구간 텍스트 사용
    out: list[SrtCue] = []
    if j > 0:
        out.extend(orig[:j])
    take = min(orig_n - len(out), len(corr) - i)
    out.extend(corr[i : i + take])
    while len(out) < orig_n:
        out.append(orig[len(out)])

    fixed = [
        SrtCue(index=orig[k].index, timing=orig[k].timing, text=out[k].text)
        for k in range(orig_n)
    ]
    from srt_edit import diag_log

    diag_log.log(
        f"정렬창 선택 match={match}/{orig_n} diffs={diffs} "
        f"corr_i={i} orig_j={j} (전체큐 {len(corr)}→{orig_n})"
    )
    return cues_to_srt(fixed)


def extract_srt_payload(
    text: str, *, original: str | None = None, log_detail: bool = True
) -> str:
    """채팅/붙여넣기에서 실보정 SRT 본문 추출.

    ``start``~``end`` 구분자 사이 본문을 최우선으로 쓰고(줄 분리 여부 무관),
    Genspark 한 줄 형식도 표준화한다. 지침 MD 짧은 예시는 원본 큐 수로 버린다.
    """
    from srt_edit import diag_log

    raw = text or ""
    s = normalize_start_end_boundaries(raw)
    orig_n = len(parse_srt_cues(original or ""))
    if log_detail:
        diag_log.log(
            f"추출시작 chars={len(raw)} start={has_start_marker(s)} "
            f"end={has_end_marker(s)} 원본큐={orig_n}"
        )
    candidates = _candidate_bodies(
        raw, original=original, log_detail=log_detail
    )
    if not candidates:
        if "-->" in s:
            body = _strip_trailing_end_marker(_trim_to_srt_body(s))
            body = align_body_to_original(body, original)
            cues = parse_srt_cues(body)
            out = cues_to_srt(cues) if cues else body + "\n"
            if log_detail:
                diag_log.log(
                    f"추출폴백 trim 큐={len(cues)} head={diag_log.preview(out)}"
                )
            return out
        if log_detail:
            diag_log.log("추출실패 — SRT 후보 없음")
        return (s.strip() + "\n") if s.strip() else ""

    # 원본 큐 수에 가까운 후보 우선
    if orig_n > 0:
        near = [b for b in candidates if cue_count_fit(len(parse_srt_cues(b)), orig_n)]
        if near:
            candidates = near
        else:
            # 전부 과다/과소면 정렬창으로 줄일 수 있는 큰 본문 유지
            candidates = [
                align_body_to_original(b, original) for b in candidates
            ]
            near = [
                b for b in candidates if cue_count_fit(len(parse_srt_cues(b)), orig_n)
            ]
            if near:
                candidates = near

    def rank(item: tuple[str, int]) -> tuple:
        body, idx = item
        n = len(parse_srt_cues(body))
        diff = changed_cue_count(body, original)
        same_as_orig = (
            1
            if orig_n > 0 and diff == 0 and abs(n - orig_n) <= max(2, orig_n // 50)
            else 0
        )
        # 나중 블록(응답) 우선 → idx 클수록 가점
        if orig_n > 0:
            return (-same_as_orig, -abs(n - orig_n), diff, idx)
        return (diff, n, idx)

    ranked = [(body, i) for i, body in enumerate(candidates)]
    if log_detail:
        for i, body in enumerate(candidates):
            n = len(parse_srt_cues(body))
            diff = changed_cue_count(body, original)
            diag_log.log(
                f"  후보[{i}] 큐={n} 원본대비변경={diff} "
                f"head={diag_log.preview(body, head=80, tail=40)}"
            )
    best, best_i = max(ranked, key=rank)
    best = _strip_trailing_end_marker(best)
    best = align_body_to_original(best, original)
    cues = parse_srt_cues(best)
    out = cues_to_srt(cues) if cues else best + "\n"
    if log_detail:
        sample214 = next((c.text for c in cues if c.index == "214"), "")
        diag_log.log(
            f"추출선택 후보[{best_i}] 큐={len(cues)} "
            f"변경={changed_cue_count(out, original)} "
            f"cue214={diag_log.preview(sample214, head=60, tail=0) or '-'} "
            f"head={diag_log.preview(out)}"
        )
    return out


def validate_corrected_against_original(
    original: str, corrected: str
) -> tuple[bool, str]:
    """저장 전 검사 — 예시·잘린 응답으로 new.srt 가 깨지지 않게."""
    from srt_edit import diag_log

    body = extract_srt_payload(
        corrected, original=original, log_detail=False
    )
    corr = parse_srt_cues(body)
    if not corr:
        diag_log.log("검증실패 — 큐 없음")
        return False, "보정 SRT에서 자막 큐를 찾지 못했습니다."
    orig = parse_srt_cues(original or "")
    if not orig:
        diag_log.log("검증경고 — 원본 SRT 큐 0 (검사 생략·저장 허용)")
        return True, ""
    # 원본의 85% 이상 큐가 있어야 저장 (이전 1/2 는 너무 느슨/예시 혼동)
    min_cues = max(1, int(len(orig) * 0.85))
    if len(corr) < min_cues:
        reason = (
            f"큐 수가 너무 적습니다 (원본 {len(orig)} · 보정 {len(corr)}). "
            f"지침 예시이거나 응답이 잘린 것 같습니다."
        )
        diag_log.log(f"검증실패 — {reason}")
        return False, reason
    # 원본보다 많이 많으면 예시+원본+응답이 이어 붙은 것
    max_cues = len(orig) + max(8, int(len(orig) * 0.15))
    if len(corr) > max_cues:
        reason = (
            f"큐 수가 너무 많습니다 (원본 {len(orig)} · 보정 {len(corr)}). "
            f"여러 SRT가 이어 붙었거나 예시가 섞인 것 같습니다."
        )
        diag_log.log(f"검증실패 — {reason}")
        return False, reason
    orig_t = {normalize_timing(c.timing) for c in orig}
    matched = sum(1 for c in corr if normalize_timing(c.timing) in orig_t)
    # 타임코드 70% 이상이면 저장 (Genspark가 일부 구간만 고쳐도 허용)
    min_match = max(1, int(len(orig) * 0.70))
    if matched < min_match:
        reason = (
            f"타임코드 일치가 부족합니다 ({matched}/{len(orig)}). "
            f"다른 SRT이거나 예시 블록일 수 있습니다."
        )
        diag_log.log(f"검증실패 — {reason}")
        return False, reason
    # 첫 큐가 MD 예시(안녕하세요) 이고 원본 첫 타임과 다르면 거부
    o0 = orig[0]
    c0 = corr[0]
    if (
        normalize_timing(c0.timing) != normalize_timing(o0.timing)
        and "안녕하세요" in (c0.text or "")
    ):
        reason = (
            "보정본 앞머리가 지침 MD 예시(안녕하세요…) 입니다. "
            "실보정 SRT가 아닙니다."
        )
        diag_log.log(f"검증실패 — {reason}")
        return False, reason
    diff = changed_cue_count(body, original)
    diag_log.log(
        f"검증통과 원본={len(orig)} 보정={len(corr)} "
        f"타임일치={matched} 변경큐={diff}"
    )
    return True, ""


def changed_line_ranges(
    original: str, corrected: str
) -> tuple[str, list[tuple[int, int]]]:
    """보정본 전체 텍스트와, 변경된 본문 줄의 1-based inclusive (start, end).

    원본 매칭은 **타임코드** 우선, 없으면 인덱스.
    """
    corr = extract_srt_payload(corrected, original=original, log_detail=False)
    orig_list = parse_srt_cues(original)
    by_timing = {normalize_timing(c.timing): c for c in orig_list}
    by_index = {c.index: c for c in orig_list}
    lines = corr.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    ranges: list[tuple[int, int]] = []
    i = 0
    n = len(lines)
    while i < n:
        if not lines[i].strip():
            i += 1
            continue
        # 번호 + 타임코드
        if i + 1 < n and _TC_RE.match(lines[i + 1].strip()):
            idx = lines[i].strip()
            timing = lines[i + 1].strip()
            body0 = i + 2
        elif _TC_RE.match(lines[i].strip()):
            idx = ""
            timing = lines[i].strip()
            body0 = i + 1
        else:
            i += 1
            continue
        j = body0
        while j < n and lines[j].strip() != "":
            j += 1
        body = "\n".join(lines[body0:j])
        o = by_timing.get(normalize_timing(timing))
        if o is None and idx:
            o = by_index.get(idx)
        if body0 < j and (o is None or o.text.strip() != body.strip()):
            ranges.append((body0 + 1, j))
        i = j if j > i else i + 1
    return corr, ranges
