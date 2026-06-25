# -*- coding: utf-8 -*-
"""SRT 대본 ↔ 이미지 글자 매칭 후 ``SRT_XXX.png`` 로 이름 변경."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from png_rename.naming import (
    is_clean_srt_png_name,
    normalized_srt_png_name,
    parse_srt_number_from_filename,
    srt_png_name,
)
from png_rename.ocr import (
    PNG_EXTS,
    analyze_image_text,
    format_ocr_display,
    sized_words_match_tuples,
)
from png_rename.srt_parse import nearest_cue_id, parse_srt_cues
from png_rename.text_norm import (
    best_cue_match,
    best_cue_word_hint,
    format_ocr_mapping_display,
    ocr_words_have_cue,
    ocr_words_in_cue_text,
    score_text_match_sized,
)

_SKIP_STEMS = frozenset({"thumbnail_youtube", "thumbnail"})


class ScanCancelledError(Exception):
    """목록 조회(OCR·매칭)가 사용자에 의해 취소됨."""


@dataclass
class MatchPreview:
    """목록 조회용 매칭 결과."""

    source: Path
    srt_number: int
    target_name: str
    cue_text: str
    score: int
    matched: bool
    ocr_preview: str = ""
    word_srt_number: int = -1
    word_cue_text: str = ""
    status: str = ""
    can_rename: bool = False
    match_reason: str = ""

    @property
    def match_label(self) -> str:
        if "썸네일" in self.status:
            return "—"
        return "일치" if filename_matches_script_number(self) else "불일치"


@dataclass
class RenameResult:
    source: Path
    target: Path
    srt_number: int
    score: int
    ocr_preview: str
    cue_preview: str


@dataclass
class RenameSkip:
    source: Path
    reason: str


def iter_png_files(folder: Path, *, recursive: bool = False) -> list[Path]:
    d = folder.resolve()
    if not d.is_dir():
        raise NotADirectoryError(d)
    if recursive:
        files = [p for p in d.rglob("*") if p.is_file() and p.suffix in PNG_EXTS]
    else:
        files = [p for p in d.iterdir() if p.is_file() and p.suffix in PNG_EXTS]
    return sorted(files, key=lambda p: p.name.lower())


def _ocr_word_location(
    ocr_text: str,
    cues: list[tuple[int, str]],
    *,
    sized_words: list[tuple[str, int]] | None = None,
) -> tuple[int, str]:
    """글자판독 텍스트의 단어가 나타나는 대본 (번호, 문장)."""
    hint = best_cue_word_hint(ocr_text, cues, sized_words=sized_words)
    if hint is None:
        return -1, ""
    map_id, text, _score = hint
    return map_id, text.strip().replace("\n", " ")


def _already_srt_named(path: Path) -> int | None:
    return parse_srt_number_from_filename(path.name)


def filename_matches_script_number(row: MatchPreview) -> bool:
    """이미지 파일명 ``SRT_NNN`` 과 행의 대본번호가 같으면 True."""
    if row.srt_number < 0:
        return False
    stem = _already_srt_named(row.source) if row.source.is_file() else None
    return stem is not None and stem == row.srt_number


def _sync_row_match_display(row: MatchPreview, cues: list[tuple[int, str]]) -> None:
    row.match_reason = format_ocr_mapping_display(row.ocr_preview, cues)
    row.matched = filename_matches_script_number(row)


def apply_ocr_to_row(
    row: MatchPreview,
    cues: list[tuple[int, str]],
    *,
    skip_already_named: bool = True,
    min_score: int = 6,
    used_numbers: set[int] | None = None,
    prefer_slot: int | None = None,
) -> None:
    """단일 PNG 행에 OCR·매칭 결과를 반영 (``row`` in-place 갱신)."""
    src = row.source
    if not src.is_file():
        return

    if src.stem.lower() in _SKIP_STEMS:
        row.srt_number = -1
        row.target_name = "—"
        row.matched = False
        row.ocr_preview = ""
        row.status = "썸네일(제외)"
        row.can_rename = False
        row.match_reason = ""
        return

    used = used_numbers if used_numbers is not None else set()

    try:
        ocr_text, sized_list = analyze_image_text(src)
        sized_tuples = sized_words_match_tuples(sized_list)
    except Exception as e:
        row.matched = False
        row.ocr_preview = ""
        row.status = f"OCR 실패: {e}"
        row.can_rename = False
        row.match_reason = ""
        return

    ocr_prev = format_ocr_display(sized_list, ocr_text)
    row.ocr_preview = ocr_prev
    word_id, word_cue = _ocr_word_location(ocr_text, cues, sized_words=sized_tuples)
    row.word_srt_number = word_id
    row.word_cue_text = word_cue

    cue_map = {int(mid): txt for mid, txt in cues}
    slot = prefer_slot if prefer_slot is not None and prefer_slot >= 0 else row.srt_number

    if slot >= 0 and slot in cue_map:
        cue_text = cue_map[slot]
        cue_one = cue_text.strip().replace("\n", " ")
        row.srt_number = slot
        row.cue_text = cue_one
        in_cue, matched_words = ocr_words_in_cue_text(
            ocr_text, cue_text, sized_words=sized_tuples
        )
        score = score_text_match_sized(sized_tuples, cue_text)
        existing_n = _already_srt_named(src)
        target_name = srt_png_name(slot)
        if not (row.target_name or "").strip() or row.target_name == "—":
            row.target_name = target_name

        if in_cue:
            row.score = score
            _sync_row_match_display(row, cues)
            dst = src.parent / target_name
            can_rename = True
            status = "대본 일치"
            if skip_already_named and existing_n is not None:
                if (
                    existing_n == slot
                    and is_clean_srt_png_name(src.name)
                    and dst.resolve() == src.resolve()
                ):
                    can_rename = False
                    status = "이미 올바른 이름"
                elif existing_n == slot and is_clean_srt_png_name(src.name):
                    can_rename = False
                    status = "이미 SRT 형식(변경 불필요)"
            if slot in used:
                can_rename = False
                status = f"SRT_{slot:03d} 번호 중복"
            elif dst.exists() and dst.resolve() != src.resolve():
                can_rename = False
                status = f"대상 파일 존재: {target_name}"
            row.can_rename = can_rename
            row.status = status
        else:
            row.score = 0
            row.can_rename = False
            row.status = "OCR·대본내용 불일치"
            _sync_row_match_display(row, cues)
        return

    hit = best_cue_match(
        ocr_text, cues, min_score=min_score, sized_words=sized_tuples
    )
    has_ocr_cue = ocr_words_have_cue(ocr_text, cues, sized_words=sized_tuples)

    if hit is None:
        row.srt_number = -1
        row.target_name = "—"
        row.score = 0
        row.matched = False
        row.can_rename = False
        row.match_reason = ""
        if word_id >= 0:
            row.status = "OCR·대본 불일치" if not has_ocr_cue else "대본과 불일치"
        elif not ocr_prev.strip():
            row.status = "OCR 단어 없음"
        else:
            row.status = "OCR·대본 불일치"
        return

    map_id, cue_text, score = hit
    in_cue, matched_words = ocr_words_in_cue_text(
        ocr_text, cue_text, sized_words=sized_tuples
    )
    if not in_cue:
        row.srt_number = -1
        row.target_name = "—"
        row.score = 0
        row.matched = False
        row.can_rename = False
        row.status = "OCR·대본내용 불일치"
        row.match_reason = ""
        return

    target_name = srt_png_name(map_id)
    cue_one = cue_text.strip().replace("\n", " ")
    dst = src.parent / target_name
    existing_n = _already_srt_named(src)

    row.srt_number = map_id
    row.target_name = target_name
    row.cue_text = cue_one
    row.score = score
    row.matched = True
    row.word_srt_number = word_id if word_id >= 0 else map_id
    row.word_cue_text = word_cue if word_cue else cue_one

    can_rename = True
    status = "대본 일치"
    if skip_already_named and existing_n is not None:
        if (
            existing_n == map_id
            and is_clean_srt_png_name(src.name)
            and dst.resolve() == src.resolve()
        ):
            can_rename = False
            status = "이미 올바른 이름"
        elif existing_n == map_id and is_clean_srt_png_name(src.name):
            can_rename = False
            status = "이미 SRT 형식(변경 불필요)"
    if map_id in used:
        can_rename = False
        status = f"SRT_{map_id:03d} 번호 중복"
    elif dst.exists() and dst.resolve() != src.resolve():
        can_rename = False
        status = f"대상 파일 존재: {target_name}"

    row.can_rename = can_rename
    row.status = status
    _sync_row_match_display(row, cues)


def scan_png_matches(
    srt_file: Path,
    png_dir: Path,
    *,
    recursive: bool = False,
    skip_already_named: bool = True,
    min_score: int = 6,
    on_progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[MatchPreview]:
    """폴더 내 모든 PNG 를 OCR·대본 매칭하여 목록으로 반환."""
    cues = parse_srt_cues(srt_file.resolve())
    if not cues:
        raise ValueError(f"SRT 에 자막이 없습니다: {srt_file}")

    sources = iter_png_files(png_dir, recursive=recursive)
    rows: list[MatchPreview] = []
    used_numbers: set[int] = set()

    total = len(sources)
    for i, src in enumerate(sources, start=1):
        if should_cancel and should_cancel():
            raise ScanCancelledError()
        if on_progress:
            on_progress(i, total, src.name)

        if src.stem.lower() in _SKIP_STEMS:
            rows.append(
                MatchPreview(
                    source=src,
                    srt_number=-1,
                    target_name="—",
                    cue_text="",
                    score=0,
                    matched=False,
                    status="썸네일(제외)",
                    can_rename=False,
                )
            )
            continue

        try:
            ocr_text, sized_list = analyze_image_text(src)
            sized_tuples = sized_words_match_tuples(sized_list)
        except Exception as e:
            rows.append(
                MatchPreview(
                    source=src,
                    srt_number=-1,
                    target_name="—",
                    cue_text="",
                    score=0,
                    matched=False,
                    ocr_preview="",
                    status=f"OCR 실패: {e}",
                    can_rename=False,
                )
            )
            continue

        hit = best_cue_match(
            ocr_text, cues, min_score=min_score, sized_words=sized_tuples
        )
        ocr_prev = format_ocr_display(sized_list, ocr_text)
        word_id, word_cue = _ocr_word_location(ocr_text, cues, sized_words=sized_tuples)
        has_ocr_cue = ocr_words_have_cue(
            ocr_text, cues, sized_words=sized_tuples
        )

        if hit is None:
            if word_id >= 0:
                rows.append(
                    MatchPreview(
                        source=src,
                        srt_number=-1,
                        target_name="—",
                        cue_text="",
                        score=0,
                        matched=False,
                        ocr_preview=ocr_prev,
                        word_srt_number=word_id,
                        word_cue_text=word_cue,
                        status="OCR·대본 불일치" if not has_ocr_cue else "대본과 불일치",
                        can_rename=False,
                    )
                )
            else:
                status_msg = "OCR·대본 불일치"
                if ocr_prev.strip() and not has_ocr_cue:
                    status_msg = "OCR·대본 불일치"
                elif not ocr_prev.strip():
                    status_msg = "OCR 단어 없음"
                rows.append(
                    MatchPreview(
                        source=src,
                        srt_number=-1,
                        target_name="—",
                        cue_text="",
                        score=0,
                        matched=False,
                        ocr_preview=ocr_prev,
                        status=status_msg,
                        can_rename=False,
                    )
                )
            continue

        map_id, cue_text, score = hit
        in_cue, matched_words = ocr_words_in_cue_text(
            ocr_text, cue_text, sized_words=sized_tuples
        )
        if not in_cue:
            rows.append(
                MatchPreview(
                    source=src,
                    srt_number=-1,
                    target_name="—",
                    cue_text="",
                    score=0,
                    matched=False,
                    ocr_preview=ocr_prev,
                    word_srt_number=word_id,
                    word_cue_text=word_cue,
                    status="OCR·대본내용 불일치",
                    can_rename=False,
                )
            )
            continue

        target_name = srt_png_name(map_id)
        cue_one = cue_text.strip().replace("\n", " ")
        dst = src.parent / target_name
        existing_n = _already_srt_named(src)

        can_rename = True
        status = "대본 일치"

        if skip_already_named and existing_n is not None:
            if existing_n == map_id and dst.resolve() == src.resolve():
                can_rename = False
                status = "이미 올바른 이름"
            elif existing_n == map_id:
                can_rename = False
                status = "이미 SRT 형식(변경 불필요)"

        if map_id in used_numbers:
            can_rename = False
            status = f"SRT_{map_id:03d} 번호 중복"
        elif dst.exists() and dst.resolve() != src.resolve():
            can_rename = False
            status = f"대상 파일 존재: {target_name}"
        else:
            used_numbers.add(map_id)

        rows.append(
            MatchPreview(
                source=src,
                srt_number=map_id,
                target_name=target_name,
                cue_text=cue_one,
                score=score,
                matched=True,
                ocr_preview=ocr_prev,
                word_srt_number=word_id if word_id >= 0 else map_id,
                word_cue_text=word_cue if word_cue else cue_one,
                status=status,
                can_rename=can_rename,
                match_reason=format_ocr_mapping_display(ocr_prev, cues),
            )
        )

    return rows


def _path_key(path: Path) -> Path:
    try:
        return path.resolve()
    except OSError:
        return path


def assign_srt_named_files_to_nearest_cue_rows(
    rows: list[MatchPreview],
    cue_map: dict[int, str],
    *,
    extra_paths: list[Path] | None = None,
) -> None:
    """``SRT_NNN`` PNG 를 대본 행에 연결. 번호가 없으면 가장 가까운 대본 행."""
    if not cue_map:
        return
    cue_ids = sorted(int(k) for k in cue_map)

    def row_for(slot: int) -> MatchPreview | None:
        for r in rows:
            if r.srt_number == slot:
                return r
        return None

    files: list[tuple[int, Path]] = []
    seen: set[Path] = set()
    path_sources: list[Path] = []
    if extra_paths:
        path_sources.extend(extra_paths)
    for row in rows:
        if row.source.is_file():
            path_sources.append(row.source)
    for path in path_sources:
        if not path.is_file():
            continue
        stem_n = _already_srt_named(path)
        if stem_n is None:
            continue
        key = _path_key(path)
        if key in seen:
            continue
        seen.add(key)
        files.append((stem_n, path))

    files.sort(key=lambda t: (0 if t[0] in cue_map else 1, t[0]))

    for stem_n, path in files:
        if stem_n not in cue_map:
            continue
        slot = stem_n
        target = row_for(slot)
        if target is None:
            continue
        if target.source.is_file():
            on_slot = _already_srt_named(target.source)
            if on_slot == slot:
                continue
            if on_slot is not None and on_slot in cue_map:
                continue
        target.source = path
        target.cue_text = cue_map[slot].strip().replace("\n", " ")
        if stem_n != slot:
            target.status = f"근접 매핑(SRT_{stem_n:03d}→{slot}번)"
        elif target.status == "이미지 없음":
            target.status = "조회 대기"


def prune_redundant_orphan_rows(rows: list[MatchPreview], cue_map: dict[int, str]) -> None:
    """대본 행에 붙은 파일과 중복되는 미배정 행 제거."""
    if not cue_map:
        return
    on_cue: set[Path] = set()
    for row in rows:
        if row.srt_number not in cue_map or not row.source.is_file():
            continue
        on_cue.add(_path_key(row.source))
    kept: list[MatchPreview] = []
    for row in rows:
        if row.srt_number in cue_map:
            kept.append(row)
            continue
        if row.source.is_file() and _path_key(row.source) in on_cue:
            continue
        kept.append(row)
    rows[:] = kept


def remap_row_srt_from_filename(
    row: MatchPreview,
    cue_map: dict[int, str],
) -> None:
    """파일명 ``SRT_NNN`` 에서 대본 번호·대본내용 동기화 (SRT에 없는 번호는 유지)."""
    if not cue_map or not row.source.is_file():
        return
    stem_n = _already_srt_named(row.source)
    if stem_n is None:
        return
    row.srt_number = stem_n
    if stem_n in cue_map:
        row.cue_text = cue_map[stem_n].strip().replace("\n", " ")
    else:
        row.cue_text = f"(대본 {stem_n}번 — SRT 미등록)"
    if (row.target_name or "") in ("", "—"):
        row.target_name = srt_png_name(row.srt_number)


def remap_all_rows_from_filenames(
    rows: list[MatchPreview],
    cue_map: dict[int, str],
) -> None:
    assign_srt_named_files_to_nearest_cue_rows(rows, cue_map)
    prune_redundant_orphan_rows(rows, cue_map)
    for row in rows:
        remap_row_srt_from_filename(row, cue_map)


def _empty_cue_row(png_dir: Path, map_id: int, cue_text: str) -> MatchPreview:
    target_name = srt_png_name(map_id)
    return MatchPreview(
        source=png_dir / target_name,
        srt_number=map_id,
        target_name=target_name,
        cue_text=cue_text.strip().replace("\n", " "),
        score=0,
        matched=False,
        ocr_preview="",
        status="이미지 없음",
        can_rename=False,
        match_reason="",
    )


def ensure_all_cue_rows(
    rows: list[MatchPreview],
    cue_map: dict[int, str],
    png_dir: Path,
) -> None:
    """SRT 대본 번호별 행이 누락되지 않도록 이미지 없음 행을 보충."""
    if not cue_map:
        return
    png_dir_r = png_dir.resolve()
    present = {r.srt_number for r in rows if r.srt_number in cue_map}
    for mid in sorted(cue_map):
        if mid in present:
            continue
        rows.append(_empty_cue_row(png_dir_r, mid, cue_map[mid]))


def build_srt_centric_skeleton(
    srt_file: Path,
    png_dir: Path,
    *,
    recursive: bool = False,
) -> list[MatchPreview]:
    """OCR 없이 SRT·파일명만으로 목록 구성 (빠른 초기 표시)."""
    cues = sorted(parse_srt_cues(srt_file.resolve()), key=lambda c: int(c[0]))
    if not cues:
        raise ValueError(f"SRT 에 자막이 없습니다: {srt_file}")

    png_dir_r = png_dir.resolve()
    files = iter_png_files(png_dir, recursive=recursive)
    by_name: dict[str, Path] = {}
    by_srt_num: dict[int, Path] = {}
    for p in files:
        by_name[p.name.lower()] = p
        stem_n = _already_srt_named(p)
        if stem_n is not None and stem_n not in by_srt_num:
            by_srt_num[stem_n] = p

    used: set[Path] = set()
    result: list[MatchPreview] = []

    def _mark_used(p: Path) -> None:
        try:
            used.add(p.resolve())
        except OSError:
            used.add(p)

    for map_id, text in cues:
        mid = int(map_id)
        target = srt_png_name(mid)
        cue_one = text.strip().replace("\n", " ")
        src = by_name.get(target.lower())
        if src is None:
            src = by_srt_num.get(mid)
        if src is not None and src.is_file():
            _mark_used(src)
            result.append(
                MatchPreview(
                    source=src,
                    srt_number=mid,
                    target_name=target,
                    cue_text=cue_one,
                    score=0,
                    matched=False,
                    ocr_preview="",
                    status="조회 대기",
                    can_rename=False,
                )
            )
        else:
            result.append(_empty_cue_row(png_dir_r, mid, text))

    cue_map = {int(mid): txt for mid, txt in cues}
    assign_srt_named_files_to_nearest_cue_rows(
        result, cue_map, extra_paths=list(by_srt_num.values())
    )
    prune_redundant_orphan_rows(result, cue_map)
    used = {_path_key(r.source) for r in result if r.source.is_file()}

    for p in files:
        key = _path_key(p)
        if key in used:
            continue
        if p.stem.lower() in _SKIP_STEMS:
            result.append(
                MatchPreview(
                    source=p,
                    srt_number=-1,
                    target_name="—",
                    cue_text="",
                    score=0,
                    matched=False,
                    status="썸네일(제외)",
                    can_rename=False,
                )
            )
            continue
        stem_n = _already_srt_named(p)
        if stem_n is not None and stem_n in cue_map:
            cue_one = cue_map[stem_n].strip().replace("\n", " ")
            status = "조회 대기"
        elif stem_n is not None:
            cue_one = f"(대본 {stem_n}번 — SRT 미등록)"
            status = "SRT 미등록 번호"
        else:
            cue_one = ""
            status = "미배정·조회 대기"
        result.append(
            MatchPreview(
                source=p,
                srt_number=stem_n if stem_n is not None else -1,
                target_name=srt_png_name(stem_n) if stem_n is not None else "—",
                cue_text=cue_one,
                score=0,
                matched=False,
                ocr_preview="",
                status=status,
                can_rename=False,
            )
        )

    return result


def scan_srt_centric_matches(
    srt_file: Path,
    png_dir: Path,
    *,
    recursive: bool = False,
    skip_already_named: bool = True,
    min_score: int = 6,
    on_progress: Callable[[int, int, str], None] | None = None,
    should_cancel: Callable[[], bool] | None = None,
) -> list[MatchPreview]:
    """SRT 대본 번호마다 한 행(이미지 없으면 빈 행) + 미배정 PNG."""
    cues = sorted(parse_srt_cues(srt_file.resolve()), key=lambda c: int(c[0]))
    if not cues:
        raise ValueError(f"SRT 에 자막이 없습니다: {srt_file}")

    cue_map = {int(mid): txt for mid, txt in cues}
    png_dir_r = png_dir.resolve()
    png_rows = scan_png_matches(
        srt_file,
        png_dir,
        recursive=recursive,
        skip_already_named=skip_already_named,
        min_score=min_score,
        on_progress=on_progress,
        should_cancel=should_cancel,
    )

    by_num: dict[int, MatchPreview] = {}
    used_sources: set[Path] = set()

    def _take(row: MatchPreview, slot: int) -> None:
        cue_one = cue_map.get(slot, row.cue_text or "").strip().replace("\n", " ")
        row.srt_number = slot
        if cue_one:
            row.cue_text = cue_one
        in_cue, matched_words = ocr_words_in_cue_text(
            row.ocr_preview, cue_one
        )
        if in_cue:
            if row.status in ("", "OCR·대본내용 불일치", "대본과 불일치"):
                row.status = "대본 일치"
        else:
            row.can_rename = False
            row.status = "OCR·대본내용 불일치"
        _sync_row_match_display(row, cues)
        by_num[slot] = row
        try:
            used_sources.add(row.source.resolve())
        except OSError:
            used_sources.add(row.source)

    for row in png_rows:
        stem_n = _already_srt_named(row.source)
        if stem_n is not None and stem_n in cue_map and stem_n not in by_num:
            _take(row, stem_n)

    for row in png_rows:
        key = _path_key(row.source)
        if key in used_sources:
            continue
        n = row.srt_number
        if n >= 0 and n in cue_map and n not in by_num:
            _take(row, n)

    cue_ids = sorted(cue_map.keys())
    for row in png_rows:
        key = _path_key(row.source)
        if key in used_sources:
            continue
        stem_n = _already_srt_named(row.source)
        if stem_n is None:
            continue
        if stem_n not in cue_map:
            continue
        slot = stem_n
        if slot in by_num:
            continue
        _take(row, slot)

    result: list[MatchPreview] = []
    for map_id, text in cues:
        mid = int(map_id)
        if mid in by_num:
            result.append(by_num[mid])
        else:
            result.append(_empty_cue_row(png_dir_r, mid, text))

    for row in png_rows:
        try:
            key = row.source.resolve()
        except OSError:
            key = row.source
        if key not in used_sources:
            result.append(row)

    return result


def find_srt_filename_normalizations(
    png_dir: Path,
    *,
    recursive: bool = False,
) -> list[tuple[Path, str]]:
    """``SRT_XXX_접미사.png`` → ``SRT_XXX.png`` 로 바꿀 (원본, 대상파일명) 목록."""
    pairs: list[tuple[Path, str]] = []
    for src in iter_png_files(png_dir, recursive=recursive):
        if src.stem.lower() in _SKIP_STEMS:
            continue
        clean = normalized_srt_png_name(src.name)
        if clean and clean != src.name:
            pairs.append((src, clean))
    return pairs


def apply_srt_filename_normalizations(
    pairs: list[tuple[Path, str]],
    *,
    dry_run: bool = False,
    on_progress: Callable[[int, int, RenameResult | RenameSkip], None] | None = None,
) -> tuple[list[RenameResult], list[RenameSkip]]:
    """접미사가 붙은 SRT 파일명을 일괄 정규화."""
    results: list[RenameResult] = []
    skipped: list[RenameSkip] = []

    work: list[tuple[Path, Path]] = []
    used_targets: set[str] = set()
    for src, target_name in pairs:
        if not src.is_file():
            skipped.append(RenameSkip(src, "파일 없음"))
            continue
        dst = src.parent / target_name
        try:
            if dst.resolve() == src.resolve():
                skipped.append(RenameSkip(src, "이미 정규 파일명"))
                continue
        except OSError:
            pass
        if target_name in used_targets:
            skipped.append(RenameSkip(src, f"같은 대상 파일명 중복: {target_name}"))
            continue
        if dst.exists():
            skipped.append(RenameSkip(src, f"대상 파일 존재: {target_name}"))
            continue
        used_targets.add(target_name)
        work.append((src, dst))

    total = len(work)
    for i, (src, dst) in enumerate(work, start=1):
        n = parse_srt_number_from_filename(src.name)
        if dry_run:
            r = RenameResult(
                source=src,
                target=dst,
                srt_number=n if n is not None else -1,
                score=0,
                ocr_preview="",
                cue_preview="",
            )
            results.append(r)
            if on_progress:
                on_progress(i, total, r)
            continue

        tmp = src.parent / f"__normalizing_{src.stem}__.png"
        if tmp.exists():
            tmp.unlink()
        src.rename(tmp)
        tmp.rename(dst)
        r = RenameResult(
            source=src,
            target=dst,
            srt_number=n if n is not None else -1,
            score=0,
            ocr_preview="",
            cue_preview="",
        )
        results.append(r)
        if on_progress:
            on_progress(i, total, r)

    return results, skipped


def apply_match_renames(
    items: list[MatchPreview],
    *,
    dry_run: bool = False,
    manual: bool = False,
    on_progress: Callable[[int, int, RenameResult | RenameSkip], None] | None = None,
) -> tuple[list[RenameResult], list[RenameSkip]]:
    """``MatchPreview`` 목록 중 선택된 항목만 이름 변경.

    ``manual=True`` 이면 사용자가 지정한 변경파일명 기준으로 저장(OCR ``can_rename`` 무시).
    """
    results: list[RenameResult] = []
    skipped: list[RenameSkip] = []

    work: list[MatchPreview] = []
    used: set[int] = set()
    for row in items:
        src = row.source
        if not src.is_file():
            skipped.append(RenameSkip(src, row.status or "변경 불가"))
            continue
        if not manual and not row.can_rename:
            skipped.append(RenameSkip(src, row.status or "변경 불가"))
            continue
        tgt = (row.target_name or "").strip()
        if not tgt or tgt == "—":
            skipped.append(RenameSkip(src, "변경파일명 없음"))
            continue
        dst = src.parent / tgt
        try:
            if dst.resolve() == src.resolve():
                skipped.append(RenameSkip(src, "이미 해당 파일명"))
                continue
        except OSError:
            pass
        if dst.exists():
            skipped.append(RenameSkip(src, f"대상 파일 존재: {tgt}"))
            continue
        if row.srt_number >= 0 and row.srt_number in used:
            skipped.append(
                RenameSkip(src, f"SRT_{row.srt_number:03d} 선택 목록에서 중복")
            )
            continue
        if row.srt_number >= 0:
            used.add(row.srt_number)
        work.append(row)

    total = len(work)
    for i, row in enumerate(work, start=1):
        src = row.source
        dst = src.parent / row.target_name
        cue_prev = row.cue_text[:60]

        if dry_run:
            r = RenameResult(
                source=src,
                target=dst,
                srt_number=row.srt_number,
                score=row.score,
                ocr_preview=row.ocr_preview,
                cue_preview=cue_prev,
            )
            results.append(r)
            if on_progress:
                on_progress(i, total, r)
            continue

        tmp = src.parent / f"__renaming_{src.stem}__.png"
        if tmp.exists():
            tmp.unlink()
        src.rename(tmp)
        tmp.rename(dst)
        r = RenameResult(
            source=src,
            target=dst,
            srt_number=row.srt_number,
            score=row.score,
            ocr_preview=row.ocr_preview,
            cue_preview=cue_prev,
        )
        results.append(r)
        if on_progress:
            on_progress(i, total, r)

    return results, skipped


def rename_pngs_by_srt(
    srt_file: Path,
    png_dir: Path,
    *,
    recursive: bool = False,
    dry_run: bool = False,
    skip_already_named: bool = True,
    min_score: int = 6,
    on_progress: Callable[[int, int, RenameResult | RenameSkip], None] | None = None,
) -> tuple[list[RenameResult], list[RenameSkip]]:
    """전체 매칭 후 변경 가능 항목만 일괄 변경 (CLI 호환)."""

    def scan_prog(i: int, total: int, name: str) -> None:
        if on_progress:
            on_progress(i, total, RenameSkip(Path(name), "스캔 중"))

    rows = scan_png_matches(
        srt_file,
        png_dir,
        recursive=recursive,
        skip_already_named=skip_already_named,
        min_score=min_score,
        on_progress=scan_prog,
    )
    to_rename = [r for r in rows if r.can_rename]
    results, apply_skips = apply_match_renames(
        to_rename, dry_run=dry_run, on_progress=on_progress
    )
    return results, apply_skips
