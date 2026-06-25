# -*- coding: utf-8 -*-
"""PNG 이미지에서 글자 추출 (Tesseract OCR)."""

from __future__ import annotations

import re
import shutil
import os
from dataclasses import dataclass
from pathlib import Path

_OCR_TOKEN = re.compile(r"[가-힣]+|[A-Za-z0-9]+(?:\.[A-Za-z0-9]+)?")

PNG_EXTS = frozenset({".png", ".PNG"})
OCR_MAX_TOP_WORDS = 0  # 0 이면 OCR 단어 개수 제한 없음

_WIN_TESSERACT = (
    Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
    Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
)


@dataclass(frozen=True)
class SizedWord:
    text: str
    height: int
    conf: float = 0.0


@dataclass(frozen=True)
class _OcrBox:
    text: str
    left: int
    top: int
    width: int
    height: int
    block: int
    par: int
    line: int
    conf: float


_HANGUL_SYLLABLE = re.compile(r"^[가-힣]$")


def _valid_ocr_token(tok: str) -> bool:
    from png_rename.text_norm import is_valid_ocr_mapping_token

    return is_valid_ocr_mapping_token(tok)


def _tesseract_exe() -> Path | None:
    found = shutil.which("tesseract") or shutil.which("tesseract.exe")
    if found:
        return Path(found)
    for cand in _WIN_TESSERACT:
        if cand.is_file():
            return cand
    return None


def _tessdata_dir(exe: Path) -> Path:
    return exe.parent / "tessdata"


def _kor_candidates(exe: Path) -> list[Path]:
    """kor.traineddata 탐색 경로(환경변수 우선)."""
    candidates: list[Path] = []
    prefix = os.environ.get("TESSDATA_PREFIX", "").strip()
    if prefix:
        base = Path(prefix)
        candidates.append(base / "kor.traineddata")
        candidates.append(base / "tessdata" / "kor.traineddata")
    # Windows 사용자 설치(관리자 권한 없이 추가한 데이터) 기본 경로
    local = os.environ.get("LOCALAPPDATA", "").strip()
    if local:
        local_base = Path(local) / "Tesseract-OCR"
        candidates.append(local_base / "kor.traineddata")
        candidates.append(local_base / "tessdata" / "kor.traineddata")
    candidates.append(_tessdata_dir(exe) / "kor.traineddata")
    return candidates


def _tess_prefix_from_kor(kor_path: Path) -> str:
    # Tesseract 는 traineddata 가 있는 실제 폴더를 prefix 로 기대하는 환경이 있다.
    # 따라서 kor 파일의 부모 디렉터리를 그대로 사용한다.
    return str(kor_path.parent)


def ensure_tesseract_cmd() -> None:
    """PATH 또는 Windows 기본 설치 경로에서 tesseract 를 찾습니다."""
    import pytesseract

    exe = _tesseract_exe()
    if exe is None:
        raise RuntimeError(
            "Tesseract OCR 이 설치되어 있지 않습니다.\n\n"
            "PowerShell(관리자):\n"
            "  winget install UB-Mannheim.TesseractOCR\n\n"
            "또는 https://github.com/UB-Mannheim/tesseract/wiki\n"
            "설치 시 Additional language → Korean 체크"
        )
    pytesseract.pytesseract.tesseract_cmd = str(exe)

    kor = next((p for p in _kor_candidates(exe) if p.is_file()), None)
    if kor is None:
        default_kor = _tessdata_dir(exe) / "kor.traineddata"
        raise RuntimeError(
            "Tesseract 한국어(kor) 데이터가 없습니다.\n\n"
            f"다음 파일이 필요합니다:\n  {default_kor}\n\n"
            "PowerShell(관리자) 예:\n"
            '  Invoke-WebRequest -Uri '
            '"https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata" '
            f'-OutFile "{default_kor}"'
        )
    # OCR 실행 프로세스가 사용자 환경변수를 못 물고 온 경우를 대비해 강제 지정
    os.environ["TESSDATA_PREFIX"] = _tess_prefix_from_kor(kor)


def _image_to_data(rgb, lang: str):
    import pytesseract

    return pytesseract.image_to_data(rgb, lang=lang, output_type=pytesseract.Output.DICT)


def _prepare_ocr_image(im):
    """작은·저대비 이미지를 OCR 에 맞게 보정."""
    from PIL import Image, ImageOps

    rgb = im.convert("RGB")
    w, h = rgb.size
    if max(w, h) < 1400:
        scale = 1400 / max(w, h)
        rgb = rgb.resize(
            (max(1, int(w * scale)), max(1, int(h * scale))),
            Image.Resampling.LANCZOS,
        )
    return ImageOps.autocontrast(rgb)


def _is_box_valid(raw: str, conf: float, h: int, w: int) -> bool:
    if not raw:
        return False
    if conf < 0 and len(raw) < 2:
        return False
    if h < 2 or w < 1:
        return False
    return True


def _collect_word_boxes(data) -> list[_OcrBox]:
    """Tesseract word(level=5) 박스 수집."""
    boxes: list[_OcrBox] = []
    n = len(data.get("text", []))
    for i in range(n):
        try:
            level = int(data["level"][i])
        except (TypeError, ValueError):
            level = 0
        if level != 5:
            continue
        raw = str(data["text"][i]).strip()
        if not raw:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        try:
            h = int(data["height"][i])
            w = int(data["width"][i])
            left = int(data["left"][i])
            top = int(data["top"][i])
            block = int(data["block_num"][i])
            par = int(data["par_num"][i])
            line = int(data["line_num"][i])
        except (TypeError, ValueError):
            continue
        if not _is_box_valid(raw, conf, h, w):
            continue
        boxes.append(
            _OcrBox(
                text=raw,
                left=left,
                top=top,
                width=w,
                height=h,
                block=block,
                par=par,
                line=line,
                conf=conf,
            )
        )
    return boxes


def _merge_boxes_on_line(boxes: list[_OcrBox]) -> list[tuple[str, int, float]]:
    """같은 줄의 글자 박스를 가로 간격으로 묶어 단어(구) 생성."""
    if not boxes:
        return []

    def _avg_conf(bs: list[_OcrBox]) -> float:
        vals = [b.conf for b in bs if b.conf >= 0]
        if not vals:
            return 0.0
        return sum(vals) / len(vals)

    ordered = sorted(boxes, key=lambda b: b.left)
    gaps: list[int] = []
    for i in range(len(ordered) - 1):
        cur, nxt = ordered[i], ordered[i + 1]
        gaps.append(nxt.left - (cur.left + cur.width))

    if gaps:
        sorted_gaps = sorted(gaps)
        med = sorted_gaps[len(sorted_gaps) // 2]
        thresh = max(10, int(med * 1.6))
    else:
        thresh = 12

    out: list[tuple[str, int, float]] = []
    buf = ordered[0].text
    max_h = ordered[0].height
    chunk: list[_OcrBox] = [ordered[0]]
    for i in range(1, len(ordered)):
        cur = ordered[i - 1]
        nxt = ordered[i]
        gap = gaps[i - 1]
        syllable_join_limit = max(thresh, int(min(cur.height, nxt.height) * 1.2))
        should_join = gap <= thresh
        if _HANGUL_SYLLABLE.match(cur.text) and _HANGUL_SYLLABLE.match(nxt.text):
            should_join = gap <= syllable_join_limit

        if not should_join:
            if buf.strip():
                out.append((buf, max_h, _avg_conf(chunk)))
            buf = nxt.text
            max_h = nxt.height
            chunk = [nxt]
        else:
            buf += nxt.text
            max_h = max(max_h, nxt.height)
            chunk.append(nxt)
    if buf.strip():
        out.append((buf, max_h, _avg_conf(chunk)))
    return out


def _split_phrase_pieces(text: str) -> list[str]:
    """문장이 아닌 단어 토큰만 추출."""
    text = text.strip()
    if not text:
        return []
    return [
        m.group(0).strip()
        for m in _OCR_TOKEN.finditer(text)
        if _valid_ocr_token(m.group(0))
    ]


def _combine_spaced_syllables(line: str) -> list[str]:
    """``서 탄 생`` 처럼 띄어진 음절을 ``서탄생`` 으로 묶음 (image_to_string 폴백)."""
    line = line.strip()
    if not line:
        return []

    words: list[str] = []
    buf: list[str] = []

    def flush() -> None:
        if not buf:
            return
        words.append("".join(buf))
        buf.clear()

    for token in line.split():
        if _HANGUL_SYLLABLE.match(token):
            buf.append(token)
            continue
        flush()
        if token:
            words.append(token)
    flush()
    return words


def _words_from_raw_text(raw: str) -> list[tuple[str, int]]:
    """image_to_string 결과에서 단어 목록 추출."""
    found: list[tuple[str, int]] = []
    for line in raw.splitlines():
        for piece in _combine_spaced_syllables(line):
            for part in _split_phrase_pieces(piece):
                if part.strip():
                    found.append((part.strip(), 0))
    return found


def _sized_from_data(data) -> list[SizedWord]:
    """박스 위치로 글자를 묶어 단어 단위 ``SizedWord`` 목록 생성."""
    by_text: dict[str, tuple[int, float]] = {}
    boxes = _collect_word_boxes(data)
    by_line: dict[tuple[int, int, int], list[_OcrBox]] = {}
    for b in boxes:
        key = (b.block, b.par, b.line)
        by_line.setdefault(key, []).append(b)

    for line_boxes in by_line.values():
        for text, height, conf in _merge_boxes_on_line(line_boxes):
            for part in _split_phrase_pieces(text):
                prev = by_text.get(part)
                if prev is None or conf > prev[1] or (conf == prev[1] and height > prev[0]):
                    by_text[part] = (height, conf)

    sized = [SizedWord(text=t, height=h, conf=c) for t, (h, c) in by_text.items()]
    sized.sort(key=lambda sw: (-sw.conf, -len(sw.text), sw.text))
    return sized


def _read_image_ocr(path: Path) -> tuple[list[SizedWord], str]:
    """한 번 열어 ``(크기순 단어, image_to_string 원문)``."""
    import pytesseract
    from PIL import Image

    ensure_tesseract_cmd()
    with Image.open(path) as im:
        rgb = _prepare_ocr_image(im)
        try:
            data = _image_to_data(rgb, "kor+eng")
            raw = pytesseract.image_to_string(rgb, lang="kor+eng")
        except pytesseract.TesseractError:
            data = _image_to_data(rgb, "eng")
            raw = pytesseract.image_to_string(rgb, lang="eng")

    return _sized_from_data(data), raw or ""


def extract_sized_words_from_image(path: Path) -> list[SizedWord]:
    """Tesseract 단어 추출 · OCR 정확도(conf) 높은 순 정렬."""
    try:
        from PIL import Image  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "pytesseract·Pillow 가 필요합니다. pip install pytesseract Pillow"
        ) from e

    sized, _raw = _read_image_ocr(path)
    return sized


def sized_words_match_tuples(words: list[SizedWord]) -> list[tuple[str, float]]:
    """대본 매칭 점수용 (단어, conf·높이 가중치)."""
    return [
        (sw.text, sw.conf if sw.conf > 0 else float(max(1, sw.height)))
        for sw in words
    ]


def top_sized_words(
    words: list[SizedWord],
    n: int = OCR_MAX_TOP_WORDS,
) -> list[SizedWord]:
    """OCR 정확도(conf) 높은 순. ``n<=0`` 이면 전체."""
    ranked = sorted(words, key=lambda sw: (-sw.conf, -len(sw.text), sw.text))
    if n <= 0:
        return ranked
    return ranked[:n]


def sized_words_to_comma(words: list[SizedWord]) -> str:
    """정확도 순 → `, ` 구분 (글자판독 컬럼)."""
    if not words:
        return ""
    return ", ".join(sw.text for sw in words)


def sized_words_to_match_text(words: list[SizedWord]) -> str:
    """대본 매칭용: 정확도 높은 단어를 앞에 두고 이어 붙임."""
    if not words:
        return ""
    return " ".join(sw.text for sw in words)


def ocr_text_to_comma_words(text: str) -> str:
    """폴백: 단어 토큰 추출(``OCR_MAX_TOP_WORDS<=0`` 이면 전체)."""
    if not text or not text.strip():
        return ""
    words = _words_from_raw_text(text)
    if words:
        if OCR_MAX_TOP_WORDS <= 0:
            return ", ".join(w for w, _ in words)
        return ", ".join(w for w, _ in words[:OCR_MAX_TOP_WORDS])
    tokens = [
        m.group(0)
        for m in _OCR_TOKEN.finditer(text)
        if _valid_ocr_token(m.group(0))
    ]
    if OCR_MAX_TOP_WORDS > 0:
        tokens = tokens[:OCR_MAX_TOP_WORDS]
    return ", ".join(tokens)


def extract_text_from_image(path: Path) -> str:
    """이미지에서 한글·영문 OCR. Tesseract + kor 데이터 필요."""
    words = extract_sized_words_from_image(path)
    if words:
        return sized_words_to_match_text(words)
    try:
        import pytesseract
        from PIL import Image
    except ImportError as e:
        raise RuntimeError(
            "pytesseract·Pillow 가 필요합니다. pip install pytesseract Pillow"
        ) from e

    ensure_tesseract_cmd()
    with Image.open(path) as im:
        rgb = im.convert("RGB")
        try:
            return pytesseract.image_to_string(rgb, lang="kor+eng")
        except pytesseract.TesseractError:
            return pytesseract.image_to_string(rgb, lang="eng")


def text_from_filename(stem: str) -> str:
    """파일명에 한글이 있으면 보조 매칭용으로 사용."""
    parts = re.split(r"[-_.\s]+", stem)
    korean = [p for p in parts if re.search(r"[가-힣]", p)]
    return " ".join(korean)


def format_ocr_display(sized_list: list[SizedWord], ocr_text: str) -> str:
    """GUI·목록용 OCR 식별 단어 문자열."""
    preview = sized_words_to_comma(top_sized_words(sized_list))
    if preview:
        return preview
    fallback = ocr_text_to_comma_words(ocr_text)
    return fallback


def analyze_image_text(path: Path) -> tuple[str, list[SizedWord]]:
    """``(매칭용 텍스트, 정확도순 단어 목록)``."""
    try:
        sized, raw = _read_image_ocr(path)
    except RuntimeError:
        raise
    except OSError:
        sized, raw = [], ""

    stem_extra = text_from_filename(path.stem)
    if stem_extra:
        for tok in _OCR_TOKEN.findall(stem_extra):
            if not _valid_ocr_token(tok):
                continue
            if not any(sw.text == tok for sw in sized):
                sized.append(SizedWord(text=tok, height=0, conf=0.0))
        sized.sort(key=lambda sw: (-sw.conf, -len(sw.text), sw.text))

    if sized:
        sized = top_sized_words(sized)
        return sized_words_to_match_text(sized), sized

    fallback_pairs = _words_from_raw_text(raw)
    if not fallback_pairs:
        fallback_pairs = [
            (m.group(0), 0)
            for m in _OCR_TOKEN.finditer(raw)
            if _valid_ocr_token(m.group(0))
        ]
    fallback = top_sized_words(
        [SizedWord(text=t, height=h, conf=0.0) for t, h in fallback_pairs]
    )
    if fallback:
        return sized_words_to_match_text(fallback), fallback
    return "", []


def combined_image_text(path: Path) -> str:
    text, _sized = analyze_image_text(path)
    return text
