# -*- coding: utf-8 -*-
"""발음(TTS) vs Whisper(STT) 자동 판정."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from stt.text_diff import DiffStats, diff_stats


class Verdict(str, Enum):
    GOOD = "good"
    SCRIPT_FORMAT = "script_format"
    WHISPER_HALLUCINATION = "whisper_hallucination"
    WHISPER_MODEL = "whisper_model"
    PRONUNCIATION = "pronunciation"
    MIXED = "mixed"
    NO_TTS = "no_tts"


@dataclass(frozen=True)
class Diagnosis:
    verdict: Verdict
    title: str
    message: str
    orig_stats: DiffStats
    tts_stats: DiffStats | None
    whisper_model: str

    @property
    def orig_match(self) -> float:
        return self.orig_stats.match_ratio

    @property
    def tts_match(self) -> float | None:
        return None if self.tts_stats is None else self.tts_stats.match_ratio


def diagnose(
    *,
    original: str,
    transcribed: str,
    tts: str | None,
    whisper_model: str,
) -> Diagnosis:
    """원본·TTS·STT 비교로 발음 문제 vs Whisper 문제를 판정합니다."""
    orig_stats = diff_stats(original, transcribed)
    tts_text = (tts or "").strip()
    tts_stats = diff_stats(tts_text, transcribed) if tts_text else None
    model = (whisper_model or "base").strip().lower()
    weak_models = {"tiny", "base", "small"}

    if not tts_stats:
        if orig_stats.match_ratio >= 85:
            return Diagnosis(
                Verdict.GOOD,
                "양호",
                "원본 대비 일치율이 높습니다. (TTS 대본 없음 — part.json·tts txt 있으면 정밀 판정 가능)",
                orig_stats,
                None,
                model,
            )
        if model in weak_models and orig_stats.match_ratio < 80:
            return Diagnosis(
                Verdict.WHISPER_MODEL,
                "Whisper 모델 의심",
                f"원본 일치 {orig_stats.match_ratio}% — TTS 대본이 없어 발음 판정은 어렵습니다. "
                f"모델을 large-v3·언어 ja로 올려 재확인하세요.",
                orig_stats,
                None,
                model,
            )
        return Diagnosis(
            Verdict.NO_TTS,
            "TTS 대본 없음",
            "part01.json 또는 tts/*.txt(원본/TTS 형식)가 없어 발음 vs Whisper 구분이 제한됩니다.",
            orig_stats,
            None,
            model,
        )

    om = orig_stats.match_ratio
    tm = tts_stats.match_ratio
    gap = tm - om
    tts_len = max(len(tts_text), 1)
    hallucination = (
        tts_stats.extra_chars >= max(8, int(tts_len * 0.02))
        and tts_stats.extra_chars > orig_stats.extra_chars
    )

    if tm >= 92 and om >= 85:
        return Diagnosis(
            Verdict.GOOD,
            "양호",
            f"TTS 일치 {tm}% · 원본 일치 {om}% — 발음·Whisper 모두 정상 범위입니다.",
            orig_stats,
            tts_stats,
            model,
        )

    if tm >= 88 and gap >= 6:
        return Diagnosis(
            Verdict.SCRIPT_FORMAT,
            "原稿 표기 차이 (발음·Whisper 정상)",
            f"TTS 일치 {tm}% vs 원본 {om}% (차이 {gap:.1f}%p) — "
            "음성은 TTS대로 읽혔고, 차이는 原稿 표기·Whisper 출력 형식 때문입니다.",
            orig_stats,
            tts_stats,
            model,
        )

    if hallucination and tm >= 75:
        return Diagnosis(
            Verdict.WHISPER_HALLUCINATION,
            "Whisper 환각",
            f"TTS 일치 {tm}%이나 STT에 원본·TTS에 없는 구절이 추가됐습니다 "
            f"(추가 {tts_stats.extra_chars}자). Whisper 재실행 또는 large-v3 권장.",
            orig_stats,
            tts_stats,
            model,
        )

    if tm < 82:
        if model in weak_models and tm >= 70:
            return Diagnosis(
                Verdict.WHISPER_MODEL,
                "Whisper 모델 한계",
                f"TTS 일치 {tm}% — base/small에서는 흔합니다. "
                "large-v3·ja로 재실행 후에도 TTS 일치가 82% 미만이면 발음(TTS·MP3)을 점검하세요.",
                orig_stats,
                tts_stats,
                model,
            )
        return Diagnosis(
            Verdict.PRONUNCIATION,
            "발음(TTS) 문제 의심",
            f"TTS 일치 {tm}% — MP3가 TTS 텍스트와 다르게 읽힌 가능성이 큽니다. "
            "TTS 재생성·MP3 재합성·TTS 엔진 설정을 확인하세요.",
            orig_stats,
            tts_stats,
            model,
        )

    if model in weak_models and tm < 88:
        return Diagnosis(
            Verdict.WHISPER_MODEL,
            "Whisper 모델 업그레이드 권장",
            f"TTS 일치 {tm}% · 원본 {om}% — large-v3·ja로 올리면 Whisper 오인식이 줄어듭니다.",
            orig_stats,
            tts_stats,
            model,
        )

    return Diagnosis(
        Verdict.MIXED,
        "복합 (재확인 권장)",
        f"TTS 일치 {tm}% · 원본 {om}% — large-v3 재실행 후에도 TTS 일치 82% 미만이면 발음을 점검하세요.",
        orig_stats,
        tts_stats,
        model,
    )


def format_diagnosis_line(d: Diagnosis) -> str:
    if d.tts_stats is None:
        return f"판정: {d.title} — {d.message}"
    return (
        f"판정: {d.title} | TTS {d.tts_match}% · 원본 {d.orig_match}% — {d.message}"
    )
