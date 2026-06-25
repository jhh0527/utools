# -*- coding: utf-8 -*-
"""대본·OCR 텍스트 정규화 및 매칭 점수."""

from __future__ import annotations

import re

_HANGUL = re.compile(r"[가-힣]+")
_STRIP_CHARS = re.compile(r"[\s\.,!?…·:;\"'“”‘’()\[\]{}<>«»—–\-_/\\|@#$%^&*+=~`]+")
_CUE_TOKEN = re.compile(r"[가-힣]{2,}|[A-Za-z]{2,}|\d{2,}")
_MODIFIER_PREFIXES = (
    "더",
    "매우",
    "아주",
    "조금",
    "너무",
    "참",
    "정말",
    "진짜",
    "약간",
    "무척",
    "상당히",
    "굉장히",
    "엄청",
    "되게",
    "꽤",
    "좀",
)
_VERB_TAIL_RE = re.compile(
    r"(?:해|되|하|이|어|아)?(?:지고|지며|지만|지면|진다|한다|된다|였다|입니다|세요|요|다)$"
)
_PARTICLE_SUFFIXES = (
    "으로",
    "부터",
    "까지",
    "처럼",
    "이며",
    "하며",
    "에서",
    "에게",
    "과",
    "와",
    "은",
    "는",
    "이",
    "가",
    "을",
    "를",
    "에",
    "의",
    "로",
    "도",
    "만",
)
OCR_MAPPING_MAX_WORDS = 0  # 0 이면 매핑 단어 개수 제한 없음


def is_valid_ocr_mapping_token(word: str) -> bool:
    """매핑용 토큰: 2글자 이상, 1자리 숫자·1자리 문자 제외."""
    w = normalize_text(word)
    if len(w) < 2:
        return False
    if re.fullmatch(r"\d", w):
        return False
    if len(w) == 1:
        return False
    return True


def normalize_text(text: str) -> str:
    """공백·구두점 제거, 한글·영숫자만 남김."""
    t = text.strip()
    if not t:
        return ""
    t = _STRIP_CHARS.sub("", t)
    return t.lower() if t.isascii() else t


def hangul_runs(text: str, *, min_len: int = 3) -> list[str]:
    return [m.group(0) for m in _HANGUL.finditer(text) if len(m.group(0)) >= min_len]


def score_text_match_sized(
    sized_words: list[tuple[str, int | float]],
    cue_text: str,
) -> int:
    """OCR 정확도(또는 글자 높이) 가중치로 대본과 비교."""
    norm_cue = normalize_text(cue_text)
    if not norm_cue:
        return 0

    score = 0
    for word, weight_raw in sized_words:
        nw = normalize_text(word)
        if len(nw) < 2:
            continue
        weight = max(1, int(weight_raw) if weight_raw else 1)
        if nw in norm_cue:
            score += weight * len(nw)
        for run in hangul_runs(word, min_len=2):
            nr = normalize_text(run)
            if len(nr) >= 2 and nr in norm_cue:
                score += weight * len(nr)

    if sized_words:
        joined = " ".join(w for w, _ in sized_words)
        score = max(score, score_text_match(joined, cue_text))
    return score


def score_text_match(ocr_text: str, cue_text: str) -> int:
    """OCR·대본 일치 점수 (클수록 유사). 0 이면 매칭 없음."""
    norm_ocr = normalize_text(ocr_text)
    norm_cue = normalize_text(cue_text)
    if not norm_ocr or not norm_cue:
        return 0

    score = 0
    if len(norm_cue) >= 4 and norm_cue in norm_ocr:
        score = max(score, len(norm_cue) + 20)
    if len(norm_ocr) >= 4 and norm_ocr in norm_cue:
        score = max(score, len(norm_ocr) + 10)

    for run in hangul_runs(cue_text, min_len=3):
        nr = normalize_text(run)
        if len(nr) >= 3 and nr in norm_ocr:
            score += len(nr)

    for run in hangul_runs(ocr_text, min_len=3):
        nr = normalize_text(run)
        if len(nr) >= 3 and nr in norm_cue:
            score += len(nr)

    return score


def _stem_token_variants(token: str) -> set[str]:
    """``생리학과`` → ``생리학`` 등 조사를 뗀 어휘 형태."""
    nt = normalize_text(token)
    if len(nt) < 2:
        return set()
    out = {nt}
    for suf in sorted(_PARTICLE_SUFFIXES, key=len, reverse=True):
        if nt.endswith(suf) and len(nt) > len(suf) + 1:
            stem = nt[: -len(suf)]
            if len(stem) >= 2:
                out.add(stem)
    return out


def _tokens_in_cue(cue_text: str) -> set[str]:
    """대본 한 줄에서 추출한 의미 토큰(조사 분리 포함)."""
    out: set[str] = set()
    for m in _CUE_TOKEN.finditer(cue_text or ""):
        out |= _stem_token_variants(m.group(0))
    return {t for t in out if len(t) >= 2}


def is_meaningful_mapping_word(
    word: str,
    cues: list[tuple[int, str]],
    *,
    vocab: set[str] | None = None,
) -> bool:
    """대본 어휘 토큰과 일치하는 OCR 단어만 True (하며·리가 등 조각 제외)."""
    vocab = vocab if vocab is not None else _cue_vocab(cues)
    core = canonical_ocr_mapping_word(word, vocab)
    if not is_valid_ocr_mapping_token(core):
        return False
    nw = normalize_text(core)
    if nw not in vocab:
        return False
    return bool(cue_ids_for_word(core, cues, vocab=vocab))


def _sized_tuples(
    sized_words: list[tuple[str, int | float]] | None,
    ocr_text: str,
) -> list[tuple[str, int | float]]:
    if sized_words:
        return sized_words
    return [(m.group(0), 0) for m in re.finditer(r"[가-힣]+|[A-Za-z0-9]+", ocr_text)]


def extract_ocr_word_tokens(
    ocr_text: str,
    sized_words: list[tuple[str, int | float]] | None = None,
    *,
    max_words: int = OCR_MAPPING_MAX_WORDS,
) -> list[str]:
    """OCR 조합 단어 목록(중복 제거, 2글자 이상 · ``max_words<=0`` 이면 전체)."""
    sized = _sized_tuples(sized_words, ocr_text)
    if max_words > 0:
        sized = sized[:max_words]
    seen: set[str] = set()
    tokens: list[str] = []
    for word, _height in sized:
        w = word.strip()
        if not w:
            continue
        if not is_valid_ocr_mapping_token(w):
            continue
        nw = normalize_text(w)
        if nw in seen:
            continue
        seen.add(nw)
        tokens.append(w)
    if not tokens and (ocr_text or "").strip():
        for part in re.split(r"[,，\s]+", ocr_text):
            w = part.strip()
            if not w:
                continue
            if not is_valid_ocr_mapping_token(w):
                continue
            nw = normalize_text(w)
            if nw not in seen:
                seen.add(nw)
                tokens.append(w)
                if max_words > 0 and len(tokens) >= max_words:
                    break
    return tokens


def _cue_vocab(cues: list[tuple[int, str]]) -> set[str]:
    vocab: set[str] = set()
    for _mid, text in cues:
        vocab |= _tokens_in_cue(text)
    return vocab


def _split_word_by_vocab(word: str, vocab: set[str]) -> list[str]:
    """붙은 단어를 대본 어휘 기준으로 분할 시도."""
    raw = word.strip()
    if not raw:
        return []
    if not re.fullmatch(r"[가-힣A-Za-z0-9]+", raw):
        return [raw]
    nraw = normalize_text(raw)
    if len(nraw) < 4:
        return [raw]

    best: dict[int, list[str]] = {0: []}
    n = len(nraw)
    for i in range(n):
        if i not in best:
            continue
        for j in range(i + 2, n + 1):
            part = nraw[i:j]
            if part not in vocab:
                continue
            piece = raw[i:j]
            cand = [*best[i], piece]
            prev = best.get(j)
            if prev is None or len(cand) > len(prev):
                best[j] = cand
    out = best.get(n)
    if out and len(out) > 1:
        return out
    return [raw]


def canonical_ocr_mapping_word(word: str, vocab: set[str]) -> str:
    """수식어·어미를 제거한 뒤 대본 어휘에 맞는 핵심 단어."""
    raw = word.strip()
    if not raw or not is_valid_ocr_mapping_token(raw):
        return raw
    nraw = normalize_text(raw)
    if not vocab:
        return raw

    best = ""
    for v in sorted(vocab, key=len, reverse=True):
        if len(v) >= 2 and v in nraw and len(v) > len(best):
            best = v
    if best:
        idx = nraw.find(best)
        return raw[idx : idx + len(best)] if idx >= 0 else best

    cand = nraw
    for pref in sorted(_MODIFIER_PREFIXES, key=len, reverse=True):
        if cand.startswith(pref) and len(cand) > len(pref) + 1:
            rest = cand[len(pref) :]
            if rest in vocab or any(v in rest for v in vocab if len(v) >= 2):
                cand = rest
                break

    tail = _VERB_TAIL_RE.search(cand)
    if tail:
        stem = cand[: tail.start()]
        if len(stem) >= 2:
            if stem in vocab:
                return stem
            for v in sorted(vocab, key=len, reverse=True):
                if len(v) >= 2 and v in stem:
                    j = stem.find(v)
                    return stem[j : j + len(v)]
            cand = stem

    if cand in vocab:
        return cand
    return raw


def split_ocr_words_for_mapping(
    ocr_preview: str,
    cues: list[tuple[int, str]],
    *,
    max_words: int = OCR_MAPPING_MAX_WORDS,
) -> list[str]:
    """OCR 단어를 분리해 매핑용 상위 단어 목록 반환."""
    src = [w.strip() for w in (ocr_preview or "").split(",") if w.strip()]
    if not src:
        return []
    vocab = _cue_vocab(cues)
    out: list[str] = []
    seen: set[str] = set()
    for word in src:
        parts: list[str] = [word.strip()]
        if len(normalize_text(word)) >= 4:
            parts.extend(_split_word_by_vocab(word, vocab))
        for run in hangul_runs(word, min_len=2):
            if normalize_text(run) in vocab:
                parts.append(run)
        for part in parts:
            core = canonical_ocr_mapping_word(part, vocab)
            if not is_valid_ocr_mapping_token(core):
                continue
            nw = normalize_text(core)
            if nw in seen:
                continue
            if not is_meaningful_mapping_word(core, cues, vocab=vocab):
                continue
            seen.add(nw)
            out.append(core)
            if max_words > 0 and len(out) >= max_words:
                return out
    return out


def ocr_words_in_cue_text(
    ocr_text: str,
    cue_text: str,
    *,
    sized_words: list[tuple[str, int | float]] | None = None,
) -> tuple[bool, list[str]]:
    """OCR 단어가 해당 대본 문장에 포함되면 True 와 매칭된 단어 목록."""
    norm_cue = normalize_text(cue_text)
    if not norm_cue:
        return False, []

    matched: list[str] = []
    for word in extract_ocr_word_tokens(ocr_text, sized_words):
        nw = normalize_text(word)
        if len(nw) >= 2 and nw in norm_cue:
            matched.append(word)
            continue
        for run in hangul_runs(word, min_len=2):
            nr = normalize_text(run)
            if len(nr) >= 2 and nr in norm_cue:
                matched.append(run)
                break
    return bool(matched), matched


def cue_ids_for_word(
    word: str,
    cues: list[tuple[int, str]],
    *,
    vocab: set[str] | None = None,
) -> list[int]:
    """단어가 대본 토큰으로 등장하는 번호 목록(부분 문자열 매칭 제외)."""
    vocab = vocab if vocab is not None else _cue_vocab(cues)
    core = canonical_ocr_mapping_word(word, vocab)
    if not is_valid_ocr_mapping_token(core):
        return []
    nw = normalize_text(core)
    if nw not in vocab:
        return []
    out: list[int] = []
    for map_id, text in cues:
        if nw in _tokens_in_cue(text):
            out.append(int(map_id))
    return out


def format_ocr_mapping_display(
    ocr_preview: str,
    cues: list[tuple[int, str]],
) -> str:
    """OCR 상위 단어별 대본 번호: ``단어·389번`` 형식."""
    words = split_ocr_words_for_mapping(
        ocr_preview, cues, max_words=OCR_MAPPING_MAX_WORDS
    )
    if not words:
        return "—"
    vocab = _cue_vocab(cues)
    parts: list[str] = []
    for word in words:
        mids = cue_ids_for_word(word, cues, vocab=vocab)
        if not mids:
            continue
        if len(mids) == 1:
            parts.append(f"{word}·{mids[0]}번")
        else:
            joined = "/".join(str(m) for m in mids[:6])
            parts.append(f"{word}·{joined}번")
    return ", ".join(parts) if parts else "—"


def collect_ocr_mapping_candidates(
    ocr_preview: str,
    cues: list[tuple[int, str]],
) -> list[int]:
    """OCR 매핑 후보 대본 번호(중복 제거, 오름차순)."""
    vocab = _cue_vocab(cues)
    found: set[int] = set()
    for word in split_ocr_words_for_mapping(
        ocr_preview, cues, max_words=OCR_MAPPING_MAX_WORDS
    ):
        for mid in cue_ids_for_word(word, cues, vocab=vocab):
            found.add(int(mid))
    return sorted(found)


def best_cue_match(
    ocr_text: str,
    cues: list[tuple[int, str]],
    *,
    min_score: int = 6,
    sized_words: list[tuple[str, int | float]] | None = None,
) -> tuple[int, str, int] | None:
    sized = _sized_tuples(sized_words, ocr_text)
    best: tuple[int, str, int] | None = None
    for map_id, text in cues:
        in_cue, matched_words = ocr_words_in_cue_text(ocr_text, text, sized_words=sized)
        if not in_cue:
            continue
        sc = score_text_match_sized(sized, text)
        if sc <= 0:
            sc = max(1, sum(len(normalize_text(w)) for w in matched_words))
        if best is None or sc > best[2]:
            best = (map_id, text, sc)
    return best


def best_cue_word_hint(
    ocr_text: str,
    cues: list[tuple[int, str]],
    *,
    sized_words: list[tuple[str, int | float]] | None = None,
) -> tuple[int, str, int] | None:
    """일치 기준 미달이어도 OCR 단어가 겹치는 대본 중 최고 점수 항목."""
    sized = _sized_tuples(sized_words, ocr_text)
    best: tuple[int, str, int] | None = None
    for map_id, text in cues:
        sc = score_text_match_sized(sized, text)
        if sc <= 0:
            continue
        if best is None or sc > best[2]:
            best = (map_id, text, sc)
    return best


def ocr_words_have_cue(
    ocr_text: str,
    cues: list[tuple[int, str]],
    *,
    sized_words: list[tuple[str, int | float]] | None = None,
) -> bool:
    """OCR 단어가 어떤 대본 문장에든 포함되면 True."""
    if not (ocr_text or "").strip():
        return False
    for _map_id, text in cues:
        in_cue, _matched = ocr_words_in_cue_text(ocr_text, text, sized_words=sized_words)
        if in_cue:
            return True
    return False
