# -*- coding: utf-8 -*-
"""단락 TTS 변환 · 텀 포함 병합 · 구간 재합성 · 대사 매칭."""

from __future__ import annotations

import json
import re
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from script_voice.elevenlabs_client import (
    api_text_has_speech,
    append_silence_mp3,
    concat_mp3_files_binary_from_paths,
    concat_mp3_files_ffmpeg,
    fade_out_trailing_mp3,
    mute_trailing_spike_mp3,
    prepare_tts_for_api,
    silence_sec_from_prepared,
    synthesize_mp3,
    trim_trailing_silence_mp3,
    write_silence_mp3,
)
from script_voice.dialogue import DialogueLine, load_dialogue_json
from script_voice.mob import apply_mob_mix, is_mob_speaker
from script_voice.parser import Paragraph, parse_numbered_paragraphs

# (상태 메시지, 진행률 0~100)
ProgressCb = Callable[[str, float], None]

_PART_MP3_RE = re.compile(r"^(\d+)\.mp3$", re.IGNORECASE)
# ``7`` / ``7~`` → 한 줄, ``1~5`` → 구간 (to 생략 시 from만)
_RANGE_RE = re.compile(
    r"^\s*(\d+)\s*(?:[~～〜\-–—ー]\s*(\d+)?)?\s*$",
)
# 긴 나레이션: 문장 단위로 나눠 합성 (말미 글리치·끝 문장 누락 완화)
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?。！？])\s+")
# 문장(클립) 사이 무음 기본 — GUI 병합 텀이 있으면 그 값을 우선
_CLAUSE_JOIN_SILENCE_SEC = 0.50

DEFAULT_GAP_SEC = 1.0
# 개별 클립 ffmpeg 후처리 패딩 비활성 — 재인코딩이 끝 음절을 깎음. 텀은 병합 gap 만 사용.
TRAILING_PAD_SEC = 0.0
LINES_INDEX_NAME = "lines.json"


def part_file_stem(num: int) -> str:
    """파트 파일 stem. 1~99 → ``01``…``99``, 100+ → ``100``… (최소 2자리)."""
    n = int(num)
    return f"{n:02d}" if n < 100 else str(n)


def paragraph_mp3_path(out_dir: Path, num: int) -> Path:
    return Path(out_dir) / f"{part_file_stem(num)}.mp3"


def line_sidecar_path(out_dir: Path, num: int) -> Path:
    """``01.mp3`` 옆 ``01.txt`` — 파일명 ↔ 대사 매칭."""
    return Path(out_dir) / f"{part_file_stem(num)}.txt"


def lines_index_path(out_dir: Path) -> Path:
    return Path(out_dir) / LINES_INDEX_NAME


def parse_line_range(spec: str, *, total: int) -> tuple[int, int]:
    """``1~5`` / ``1-5`` / ``3`` / ``7~`` / ``1~1`` → (from, to) 1-based inclusive.

    - ``7`` 또는 ``7~`` (to 생략) → 해당 줄만 ``(7, 7)``
    - 빈 문자열이면 전체 ``(1, total)``.
    """
    raw = (spec or "").strip()
    if not raw:
        if total < 1:
            raise ValueError("대본 줄이 없습니다.")
        return 1, total
    m = _RANGE_RE.match(raw)
    if not m:
        raise ValueError(
            f"구간 형식 오류: '{spec}'\n"
            "예: 7 (한 줄) , 7~ (한 줄) , 1~5 (구간)"
        )
    a = int(m.group(1))
    to_raw = m.group(2)
    # to 없음 또는 빈 칸 → from만
    b = int(to_raw) if (to_raw is not None and str(to_raw).strip()) else a
    lo, hi = (a, b) if a <= b else (b, a)
    if lo < 1 or hi < 1:
        raise ValueError(f"구간은 1 이상이어야 합니다: {spec}")
    if total < 1:
        raise ValueError("대본 줄이 없습니다.")
    if lo > total:
        raise ValueError(f"구간 시작 {lo} 이 전체 {total}줄을 초과합니다.")
    hi = min(hi, total)
    return lo, hi


def discover_part_mp3s(out_dir: Path) -> list[Path]:
    """번호 파트 MP3 ``01.mp3``…``99.mp3``·``100.mp3``… 숫자순 (자릿수 제한 없음)."""
    root = Path(out_dir)
    if not root.is_dir():
        return []
    found: list[tuple[int, Path]] = []
    for p in root.iterdir():
        if not p.is_file():
            continue
        m = _PART_MP3_RE.match(p.name)
        if not m:
            continue
        found.append((int(m.group(1)), p))
    found.sort(key=lambda x: x[0])
    return [p for _, p in found]


def _write_line_sidecar(
    out_dir: Path,
    *,
    index: int,
    speaker: str,
    text: str,
) -> Path:
    """``NN.txt`` — 같은 번호 MP3의 화자·대사."""
    path = line_sidecar_path(out_dir, index)
    body = f"[{(speaker or '').strip() or 'unknown'}]\n{(text or '').strip()}\n"
    path.write_text(body, encoding="utf-8")
    return path


def write_lines_index(
    out_dir: Path,
    entries: list[dict],
    *,
    source: str = "",
) -> Path:
    """``lines.json`` — ``01.mp3`` ↔ speaker/text 전체 목록."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "source": source or "",
        "count": len(entries),
        "lines": entries,
    }
    dest = lines_index_path(out_dir)
    dest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return dest


def _line_entry(line: DialogueLine) -> dict:
    stem = part_file_stem(line.index)
    return {
        "index": line.index,
        "file": f"{stem}.mp3",
        "sidecar": f"{stem}.txt",
        "speaker": line.speaker,
        "text": line.text,
    }


def split_tts_clauses(text: str) -> list[str]:
    """문장 단위로 분할. 마침표가 2개 이상이면 길이와 관계없이 나눕니다.

    마지막 조각이 극단적으로 짧을 때만(8글자 미만) 앞 문장과 합칩니다.
    """
    s = (text or "").strip()
    if not s:
        return []
    parts = [p.strip() for p in _SENTENCE_SPLIT_RE.split(s) if p.strip()]
    if len(parts) < 2:
        return [s]
    last_plain = re.sub(r"\[[^\]]*\]", " ", parts[-1])
    last_plain = " ".join(last_plain.split())
    # 말줄임·조사만 남은 경우만 합침 — 짧은 완결 문장은 단독 합성
    if len(last_plain) < 8 and len(parts) >= 2:
        parts = parts[:-2] + [f"{parts[-2]} {parts[-1]}"]
    return parts


def _postprocess_clip(dest: Path, *, allow_mute: bool = True) -> None:
    trim_trailing_silence_mp3(dest)
    if allow_mute and mute_trailing_spike_mp3(dest):
        trim_trailing_silence_mp3(dest)
    fade_out_trailing_mp3(dest)


def _synthesize_to_file(
    *,
    api_key: str,
    voice_id: str,
    text: str,
    dest: Path,
    model_id: str,
    trailing_pad_sec: float,
    gap_sec: float | None = None,
) -> str:
    """한 줄 합성. 반환: ``ok`` | ``silence`` (구두점·말줄임만 등).

    문장 분할 시 클립 사이 쉼은 ``gap_sec``(병합 텀)를 사용합니다.
    ElevenLabs 문맥(previous/next)은 넘기지 않습니다.
    """
    mid = model_id or "eleven_multilingual_v2"
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        dest.unlink(missing_ok=True)
    except OSError:
        pass

    # 문장·구간 사이 호흡 = 병합 텀(초). 0이면 무음 클립 생략
    if gap_sec is not None:
        join_sec = max(0.0, min(3.0, float(gap_sec)))
    else:
        join_sec = _CLAUSE_JOIN_SILENCE_SEC

    plain = prepare_tts_for_api(text, model_id=mid)
    if not plain or not api_text_has_speech(plain):
        # [surprised] "……!" 처럼 태그·구두점만 → API 호출 없이 짧은 무음
        sil = silence_sec_from_prepared(plain, default_sec=0.45)
        write_silence_mp3(dest, sil)
        pad = max(0.0, float(trailing_pad_sec))
        if pad >= 0.05:
            append_silence_mp3(dest, pad)
        return "silence"

    clauses = split_tts_clauses(text)
    if len(clauses) == 1:
        audio = synthesize_mp3(
            api_key.strip(),
            voice_id.strip(),
            text,
            model_id=mid,
        )
        dest.write_bytes(audio)
        _postprocess_clip(dest)
        pad = max(0.0, float(trailing_pad_sec))
        if pad >= 0.05:
            append_silence_mp3(dest, pad)
        return "ok"

    # 문장별 합성 후 이어붙이기 — 한 번에 길게 보내 말미가 깨지는 경우 완화
    tmp_dir = Path(tempfile.mkdtemp(prefix="sv_clause_"))
    try:
        parts: list[Path] = []
        for ci, clause in enumerate(clauses):
            cplain = prepare_tts_for_api(
                clause, model_id=mid, add_trailing_pause=False
            )
            if not cplain or not api_text_has_speech(cplain):
                continue
            clip = tmp_dir / f"{ci:02d}.mp3"
            clip.write_bytes(
                synthesize_mp3(
                    api_key.strip(),
                    voice_id.strip(),
                    clause,
                    model_id=mid,
                    add_trailing_pause=False,
                )
            )
            # 중간 문장: 트림 금지 — 말미 음절이 호흡(줄바꿈) 직전에 잘림
            if ci == len(clauses) - 1:
                trim_trailing_silence_mp3(clip, keep_silence_sec=0.30)
            parts.append(clip)
            if ci < len(clauses) - 1 and join_sec >= 0.05:
                gap = tmp_dir / f"{ci:02d}_gap.mp3"
                write_silence_mp3(gap, join_sec)
                parts.append(gap)
        if not parts:
            sil = silence_sec_from_prepared(plain, default_sec=0.45)
            write_silence_mp3(dest, sil)
            return "silence"
        if len(parts) == 1:
            shutil.copy2(parts[0], dest)
        else:
            try:
                concat_mp3_files_ffmpeg(parts, dest)
            except Exception:
                concat_mp3_files_binary_from_paths(parts, dest)
        # 문장 경계 quiet 를 말미 글리치로 오인하지 않도록 mute 생략
        trim_trailing_silence_mp3(dest, keep_silence_sec=0.28)
        fade_out_trailing_mp3(dest)
        pad = max(0.0, float(trailing_pad_sec))
        if pad >= 0.05:
            append_silence_mp3(dest, pad)
        return "ok"
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def convert_script_to_mp3s(
    script: str,
    out_dir: Path,
    *,
    api_key: str,
    voice_id: str,
    model_id: str = "eleven_multilingual_v2",
    trailing_pad_sec: float = TRAILING_PAD_SEC,
    on_progress: ProgressCb | None = None,
) -> list[Path]:
    """대본 → ``01.mp3``, ``02.mp3``, … 반환은 생성된 경로 목록."""
    paras = parse_numbered_paragraphs(script)
    if not paras:
        raise ValueError("단락이 없습니다. [1], [2] … 형식으로 구분해 주세요.")
    if not (api_key or "").strip() or not (voice_id or "").strip():
        raise ValueError("ElevenLabs API 키와 Voice ID가 필요합니다.")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    index_entries: list[dict] = []
    total = len(paras)
    if on_progress:
        on_progress(f"변환 시작 — {total}단락", 0.0)
    for i, para in enumerate(paras, start=1):
        pct_start = (i - 1) / total * 100.0
        if on_progress:
            on_progress(f"변환 {i}/{total} ({pct_start:.0f}%) — {para.mp3_name}", pct_start)
        dest = paragraph_mp3_path(out_dir, para.num)
        _synthesize_to_file(
            api_key=api_key,
            voice_id=voice_id,
            text=para.text,
            dest=dest,
            model_id=model_id,
            trailing_pad_sec=trailing_pad_sec,
        )
        _write_line_sidecar(out_dir, index=para.num, speaker="narrator", text=para.text)
        index_entries.append(
            {
                "index": para.num,
                "file": f"{part_file_stem(para.num)}.mp3",
                "sidecar": f"{part_file_stem(para.num)}.txt",
                "speaker": "narrator",
                "text": para.text,
            }
        )
        saved.append(dest)
        pct_done = i / total * 100.0
        if on_progress:
            on_progress(f"변환 {i}/{total} ({pct_done:.0f}%) — {para.mp3_name}", pct_done)
    write_lines_index(out_dir, index_entries, source="[N] script")
    if on_progress:
        on_progress(f"변환 완료 — {len(saved)}개", 100.0)
    return saved


def _safe_mp3_stem(raw: str, *, fallback: str = "all") -> str:
    s = re.sub(r'[<>:"/\\|?*\s]+', "_", (raw or "").strip())
    s = s.strip("._")
    return s or fallback


def dialogue_merged_mp3_name(json_path: Path | str) -> str:
    """JSON ``chunk_id`` → ``A1.mp3``, 없으면 ``all.mp3``."""
    p = Path(json_path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "all.mp3"
    if not isinstance(data, dict):
        return "all.mp3"
    chunk = data.get("chunk_id")
    if isinstance(chunk, str) and chunk.strip():
        return f"{_safe_mp3_stem(chunk.strip())}.mp3"
    return "all.mp3"


def convert_dialogue_json_to_mp3s(
    json_path: Path | str,
    out_dir: Path,
    *,
    api_key: str,
    model_id: str = "eleven_multilingual_v2",
    gap_sec: float = DEFAULT_GAP_SEC,
    auto_merge: bool = True,
    range_spec: str = "",
    trailing_pad_sec: float = TRAILING_PAD_SEC,
    on_progress: ProgressCb | None = None,
) -> tuple[list[Path], Path | None]:
    """dialogue JSON → ``01.mp3``… (+ ``01.txt`` / ``lines.json``) 후 자동 병합(기본).

    ``range_spec`` 예: ``1~5``, ``1~1`` — 해당 줄만 재합성. 빈 값이면 전체.
    중간 ``NN.mp3`` 는 병합 후에도 산출 폴더에 유지합니다.
    반환: (이번에 합성한 파트 경로 목록, 병합 파일 경로 또는 None).
    """
    if not (api_key or "").strip():
        raise ValueError("ElevenLabs API 키가 필요합니다.")
    lines = load_dialogue_json(json_path)
    lo, hi = parse_line_range(range_spec, total=len(lines))
    targets = [ln for ln in lines if lo <= ln.index <= hi]
    if not targets:
        raise ValueError(f"합성할 줄이 없습니다: {range_spec or '(전체)'}")

    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    saved: list[Path] = []
    total = len(targets)
    # 합성 0~85%, 병합 85~100%
    synth_span = 85.0 if auto_merge else 100.0
    range_label = f"{lo}~{hi}" if (range_spec or "").strip() else f"1~{len(lines)}"
    if on_progress:
        on_progress(f"JSON 변환 시작 — {range_label} ({total}줄)", 0.0)
    for i, line in enumerate(targets, start=1):
        pct_start = (i - 1) / total * synth_span
        label = f"{line.mp3_name} ({line.speaker})"
        if on_progress:
            on_progress(f"변환 {i}/{total} ({pct_start:.0f}%) — {label}", pct_start)
        dest = paragraph_mp3_path(out_dir, line.index)
        mode = _synthesize_to_file(
            api_key=api_key,
            voice_id=line.voice_id,
            text=line.text,
            dest=dest,
            model_id=model_id,
            trailing_pad_sec=trailing_pad_sec,
            gap_sec=gap_sec,
        )
        if mode == "silence" and on_progress:
            preview = (line.text or "").replace("\n", " ").strip()
            if len(preview) > 48:
                preview = preview[:48] + "…"
            on_progress(
                f"[{line.index}] {line.speaker} | {preview}  "
                f"→ 무음 (낭독 글자 없음·구두점/말줄임만)",
                pct_start + 0.01,
            )
        if is_mob_speaker(line.speaker):
            if on_progress:
                on_progress(
                    f"군중 믹스 {i}/{total} — {label}",
                    pct_start + (i - 0.5) / total * synth_span * 0.5,
                )
            apply_mob_mix(dest, api_key=api_key, out_dir=out_dir)
        _write_line_sidecar(
            out_dir, index=line.index, speaker=line.speaker, text=line.text
        )
        saved.append(dest)
        pct_done = i / total * synth_span
        if on_progress:
            on_progress(f"변환 {i}/{total} ({pct_done:.0f}%) — {label}", pct_done)

    # 전체 대본 기준 인덱스 (구간 재합성이어도 전체 목록 유지)
    write_lines_index(
        out_dir,
        [_line_entry(ln) for ln in lines],
        source=str(Path(json_path)),
    )

    merged: Path | None = None
    if auto_merge:
        # 구간만 다시 써도 폴더의 전체 NN.mp3 를 병합
        all_name = dialogue_merged_mp3_name(json_path)

        def _merge_progress(msg: str, pct: float) -> None:
            if on_progress:
                on_progress(msg, 85.0 + max(0.0, min(100.0, pct)) * 0.15)

        merged = merge_part_mp3s(
            out_dir,
            gap_sec=gap_sec,
            all_name=all_name,
            on_progress=_merge_progress,
        )
        if on_progress:
            on_progress(
                f"JSON 완료 — {range_label} {len(saved)}줄 + 병합 → {merged.name}",
                100.0,
            )
    elif on_progress:
        on_progress(f"JSON 변환 완료 — {range_label} {len(saved)}개", 100.0)
    return saved, merged


def merge_part_mp3s(
    out_dir: Path,
    *,
    gap_sec: float = DEFAULT_GAP_SEC,
    all_name: str = "all.mp3",
    on_progress: ProgressCb | None = None,
) -> Path:
    """번호순 파트 MP3를 단락 사이 무음(텀)과 함께 병합 → ``all.mp3``.

    중간 ``NN.mp3`` 는 삭제하지 않고 유지합니다.
    """
    out_dir = Path(out_dir)
    parts = discover_part_mp3s(out_dir)
    if not parts:
        raise ValueError(f"병합할 NN.mp3 가 없습니다: {out_dir}")
    if on_progress:
        on_progress(f"병합 준비 — {len(parts)}개 + 텀 {gap_sec:.2f}s", 5.0)

    dest = out_dir / all_name
    gap = max(0.0, float(gap_sec))
    chain: list[Path] = []
    tmp_dir: Path | None = None
    silence: Path | None = None

    try:
        if gap > 0.001 and len(parts) > 1:
            tmp_dir = Path(tempfile.mkdtemp(prefix="stvo_gap_", dir=str(out_dir)))
            silence = tmp_dir / "gap.mp3"
            write_silence_mp3(silence, gap)
            for i, p in enumerate(parts):
                chain.append(p)
                if i < len(parts) - 1:
                    chain.append(silence)
        else:
            chain = list(parts)

        if on_progress:
            on_progress(f"병합 중 — {len(parts)}개", 40.0)
        try:
            concat_mp3_files_ffmpeg(chain, dest)
        except Exception as e:
            # 텀(무음) 끼운 바이너리 이어붙이기는 클릭·잡음이 나므로 금지
            if gap > 0.001 and len(parts) > 1:
                raise RuntimeError(
                    "ffmpeg 병합 실패 — 텀이 있을 때 바이너리 폴백은 "
                    "경계 잡음이 나서 사용하지 않습니다.\n"
                    f"원인: {e}"
                ) from e
            concat_mp3_files_binary_from_paths(chain, dest)
    finally:
        if silence is not None:
            try:
                silence.unlink(missing_ok=True)
            except OSError:
                pass
        if tmp_dir is not None:
            try:
                tmp_dir.rmdir()
            except OSError:
                pass

    if on_progress:
        on_progress(f"병합 완료 → {dest.name}", 100.0)
    return dest


__all__ = [
    "DEFAULT_GAP_SEC",
    "LINES_INDEX_NAME",
    "TRAILING_PAD_SEC",
    "Paragraph",
    "convert_dialogue_json_to_mp3s",
    "convert_script_to_mp3s",
    "dialogue_merged_mp3_name",
    "discover_part_mp3s",
    "line_sidecar_path",
    "lines_index_path",
    "merge_part_mp3s",
    "paragraph_mp3_path",
    "parse_line_range",
    "parse_numbered_paragraphs",
    "part_file_stem",
    "write_lines_index",
]
