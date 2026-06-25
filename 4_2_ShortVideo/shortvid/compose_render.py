"""SRT 타임라인 + 단일 MP3 + 이미지(srt_NN 파일명 ↔ SRT 표시 번호) → 구간별 MP4 후 연결."""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from pathlib import Path

from shortvid.assets import audio_duration_ffprobe, make_silent_mp3
from shortvid.compose_overrides import (
    InsertClipSpec,
    default_overrides_path,
    inserts_by_after_cue,
    is_compose_video_path,
    load_compose_overrides,
    per_cue_images_srt_mapping,
    resolved_motion_effects_per_cue,
)
from shortvid.ffmpeg_render import concat_scenes, resolve_ffmpeg_exe, _subtitle_path_filter_arg
from shortvid.subprocess_util import subprocess_run_no_window
from shortvid.motion import (
    _same_compose_image_path,
    build_image_motion_frozen_vf,
    build_image_motion_vf,
    compose_motion_span_phase_per_cue,
    effects_for_compose_cues,
    normalize_effect,
)
from shortvid.repo_paths import default_srt_image_output_dir
from shortvid.schema import RenderSettings, resolve_outro_text
from shortvid.srt_image_effects import (
    find_srt_image_effects_json,
    load_cue_effects_from_srt_image_json,
)
from shortvid.srt_parse import load_srt_cues_ms
from shortvid.subtitles import write_single_cue_srt


_MEDIA_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".mp4"}

ComposeProgressCb = Callable[[int, int, str], None]


def natural_sort_key(path: Path) -> list[str | int]:
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", path.name)]


def _compose_static_image_input_framerate(duration_sec: float) -> str:
    """정지 이미지+zoompan 클립당 입력 프레임 수를 ~1로 유지하기 위한 프레임레이트.

    ``-loop 1`` + 높은 ``-framerate`` 이면 zoompan 이 입력 프레임마다 사이클을 재시작하여
    장시간 재생 시 모션이 리셋·떨림처럼 보입니다. ``1/duration`` Hz 로 두면 한 클립당 입력이
    거의 한 장이라 한 사이클로 부드럽게 이어집니다.
    """
    dur = max(float(duration_sec), 1e-6)
    rate = 1.0 / dur
    s = f"{rate:.12f}".rstrip("0").rstrip(".")
    return s if s else "1"


def clamp_cues_ms_to_audio(
    cues: list[tuple[int, int, int, str]],
    audio_duration_sec: float,
) -> tuple[list[tuple[int, int, int, str]], str]:
    """SRT 타임라인을 MP3 길이에 맞춥니다.

    - SRT가 MP3보다 길면: 큐 종료를 MP3 끝으로 자름 (영상만 길어지는 현상 방지).
    - SRT가 MP3보다 짧으면: **마지막 큐** 종료를 MP3 끝까지 연장 (끝 음성 1초대 잘림 방지).
    """
    audio_ms = max(0, int(round(float(audio_duration_sec) * 1000.0)))
    warns: list[str] = []
    if cues:
        last_end = max(c[2] for c in cues)
        if last_end > audio_ms + 80:
            warns.append(
                f"SRT 끝({last_end / 60000:.2f}분)이 MP3({audio_ms / 60000:.2f}분)보다 깁니다. "
                "MP3 길이로 자막 구간을 잘랐습니다."
            )
    out: list[tuple[int, int, int, str]] = []
    for mid, t0, t1, txt in cues:
        if audio_ms <= 0:
            break
        if t0 >= audio_ms:
            continue
        end = min(int(t1), audio_ms)
        if end <= int(t0):
            continue
        out.append((mid, int(t0), end, txt))

    if out and audio_ms > 0:
        mid, t0, t1, txt = out[-1]
        gap_ms = audio_ms - int(t1)
        if gap_ms > 80:
            warns.append(
                f"마지막 SRT({t1 / 1000:.2f}s)보다 MP3({audio_ms / 1000:.2f}s)가 "
                f"{gap_ms / 1000:.2f}s 깁니다. 마지막 큐를 MP3 끝까지 연장했습니다."
            )
            out[-1] = (mid, int(t0), audio_ms, txt)

    return out, " ".join(warns)


def list_compose_images(images_dir: Path) -> list[Path]:
    if not images_dir.is_dir():
        return []
    files = [p for p in images_dir.iterdir() if p.is_file() and p.suffix.lower() in _MEDIA_EXT]
    return sorted(files, key=natural_sort_key)


def default_compose_audio(assets: Path) -> Path | None:
    part = [p for p in assets.glob("part*.mp3") if p.is_file()]
    if part:
        return sorted(part, key=natural_sort_key)[0]
    mp3s = [p for p in assets.glob("*.mp3") if p.is_file()]
    return sorted(mp3s, key=natural_sort_key)[0] if mp3s else None


def default_compose_srt(assets: Path, audio: Path | None) -> Path | None:
    if audio is not None:
        cand = assets / f"{audio.stem}.srt"
        if cand.is_file():
            return cand
    part = [p for p in assets.glob("part*.srt") if p.is_file()]
    if part:
        return sorted(part, key=natural_sort_key)[0]
    srts = [p for p in assets.glob("*.srt") if p.is_file()]
    return sorted(srts, key=natural_sort_key)[0] if srts else None


def _compose_video_vf(
    w: int,
    h: int,
    fps: int,
    duration_sec: float,
    effect: str,
    srt: Path | None,
    *,
    burn_subtitles: bool,
    subtitle_cwd: Path | None = None,
    play_res: tuple[int, int] | None = None,
    motion_span_sec: float | None = None,
    motion_phase_sec: float | None = None,
) -> str:
    base = build_image_motion_vf(
        w,
        h,
        fps,
        duration_sec,
        effect,
        motion_span_sec=motion_span_sec,
        motion_phase_sec=motion_phase_sec,
    )
    if burn_subtitles and srt is not None:
        pr = play_res if play_res is not None else (w, h)
        return base + "," + _subtitle_path_filter_arg(srt, ffmpeg_cwd=subtitle_cwd, play_res=pr)
    return base


def render_compose_black_clip(
    *,
    audio: Path,
    start_sec: float,
    end_sec: float,
    cue_text: str,
    out_mp4: Path,
    settings: RenderSettings,
    burn_subtitles: bool,
    work_srt: Path,
) -> None:
    """이미지 삭제(검은 화면) 구간 — 원본 MP3 구간만 유지."""
    dur = max(0.06, float(end_sec) - float(start_sec))
    st = max(0.0, float(start_sec))
    w, h, fps = settings.width, settings.height, settings.fps
    af = f"atrim=start={st:.6f}:duration={dur:.6f},asetpts=PTS-STARTPTS"

    if burn_subtitles and (cue_text or "").strip():
        write_single_cue_srt(work_srt, cue_text, dur)
        vf = f"format=yuv420p,{_subtitle_path_filter_arg(work_srt, ffmpeg_cwd=out_mp4.parent, play_res=(w, h))}"
    else:
        vf = "format=yuv420p"

    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={w}x{h}:r={fps}:d={dur}",
        "-i",
        str(audio.resolve()),
        "-vf",
        vf,
        "-af",
        af,
        "-c:v",
        settings.video_codec,
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-c:a",
        settings.audio_codec,
        "-b:a",
        "192k",
        "-shortest",
        "-r",
        str(fps),
        "-vsync",
        "cfr",
        "-movflags",
        "+faststart",
        str(out_mp4.resolve()),
    ]
    env = dict(os.environ)
    env.setdefault("FONTCONFIG_PATH", "")
    pr = subprocess_run_no_window(
        cmd,
        cwd=str(out_mp4.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg 검은 클립 실패:\n{pr.stderr}\n{pr.stdout}")


def render_compose_insert_clip(
    *,
    image: Path,
    duration_sec: float,
    subtitle_text: str,
    out_mp4: Path,
    settings: RenderSettings,
    burn_subtitles: bool,
    work_srt: Path,
    effect: str,
    motion_span_sec: float | None = None,
    motion_phase_sec: float | None = None,
) -> None:
    """삽입 구간 — 무음 + 정지 이미지(선택 자막)."""
    dur = max(0.06, float(duration_sec))
    eff = normalize_effect(effect)

    if burn_subtitles and (subtitle_text or "").strip():
        write_single_cue_srt(work_srt, subtitle_text, dur)
        vf = _compose_video_vf(
            settings.width,
            settings.height,
            settings.fps,
            dur,
            eff,
            work_srt,
            burn_subtitles=True,
            subtitle_cwd=out_mp4.parent,
            motion_span_sec=motion_span_sec,
            motion_phase_sec=motion_phase_sec,
        )
    else:
        vf = _compose_video_vf(
            settings.width,
            settings.height,
            settings.fps,
            dur,
            eff,
            None,
            burn_subtitles=False,
            motion_span_sec=motion_span_sec,
            motion_phase_sec=motion_phase_sec,
        )

    input_fps = _compose_static_image_input_framerate(dur) if eff != "none" else str(settings.fps)

    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        input_fps,
        "-loop",
        "1",
        "-i",
        str(image.resolve()),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf",
        vf,
        "-t",
        str(dur),
        "-c:v",
        settings.video_codec,
        "-preset",
        "medium",
        "-crf",
        "20",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(settings.fps),
        "-keyint_min",
        str(settings.fps),
        "-sc_threshold",
        "0",
        "-c:a",
        settings.audio_codec,
        "-b:a",
        "192k",
        "-r",
        str(settings.fps),
        "-vsync",
        "cfr",
        "-movflags",
        "+faststart",
        str(out_mp4.resolve()),
    ]
    env = dict(os.environ)
    env.setdefault("FONTCONFIG_PATH", "")
    pr = subprocess_run_no_window(
        cmd,
        cwd=str(out_mp4.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg 삽입 클립 실패:\n{pr.stderr}\n{pr.stdout}")


def _last_compose_media(resolved_imgs: list[Path | None]) -> Path | None:
    """엔딩 홀드용: 마지막으로 쓰인 이미지·영상."""
    for p in reversed(resolved_imgs):
        if p is not None and p.is_file():
            return p
    return None


def _outro_motion_freeze_state(
    cues: list[tuple[int, int, int, str]],
    motion_per_cue: list[str],
    span_phase_per_cue: list[tuple[float | None, float | None]],
    resolved_imgs: list[Path | None],
    outro_image: Path | None,
) -> tuple[str, float | None, float | None]:
    """엔딩 고정 화면: 본편 마지막 시점의 줌/팬 상태(효과·span·phase)."""
    n = len(cues)
    if (
        n == 0
        or len(motion_per_cue) != n
        or len(span_phase_per_cue) != n
        or len(resolved_imgs) != n
    ):
        return "none", None, None

    run_end_i = n - 1
    if outro_image is not None:
        for i in range(n - 1, -1, -1):
            img = resolved_imgs[i]
            if img is not None and _same_compose_image_path(img, outro_image):
                run_end_i = i
                break

    eff = motion_per_cue[run_end_i]
    if normalize_effect(eff) == "none":
        return eff, None, None

    _mid, t0, t1, _txt = cues[run_end_i]
    last_cue_sec = max(1e-6, (int(t1) - int(t0)) / 1000.0)

    mspan, mphase = span_phase_per_cue[run_end_i]
    if mspan is not None and mphase is not None:
        phase_at_end = float(mphase) + last_cue_sec
        return eff, float(mspan), phase_at_end

    # 검은 큐·영상 등으로 span 이 없어도, 같은 이미지 연속 구간 길이로 위상 계산
    img = resolved_imgs[run_end_i]
    if img is None:
        return eff, None, None

    run_start_i = run_end_i
    for i in range(run_end_i - 1, -1, -1):
        if resolved_imgs[i] is not None and _same_compose_image_path(resolved_imgs[i], img):
            run_start_i = i
        elif resolved_imgs[i] is not None:
            break

    t0_run = cues[run_start_i][1] / 1000.0
    t1_run = cues[run_end_i][2] / 1000.0
    span = max(1e-6, float(t1_run - t0_run))
    phase_at_end = max(0.0, float(t0) / 1000.0 - t0_run) + last_cue_sec
    phase_at_end = min(phase_at_end, span)
    return eff, span, phase_at_end


def render_compose_outro_hold_clip(
    *,
    image: Path | None,
    duration_sec: float,
    subtitle_text: str,
    out_mp4: Path,
    settings: RenderSettings,
    burn_subtitles: bool,
    work_srt: Path,
    effect: str = "none",
    motion_span_sec: float | None = None,
    motion_phase_sec: float | None = None,
) -> None:
    """본편 종료 후: 마지막 효과 화면 고정 + 감사 자막(무음)."""
    dur = max(0.06, float(duration_sec))
    if image is not None and image.is_file():
        if is_compose_video_path(image):
            w, h, fps = settings.width, settings.height, settings.fps
            scale_cover = _compose_scale_cover_vf(w, h)
            if burn_subtitles and (subtitle_text or "").strip():
                write_single_cue_srt(work_srt, subtitle_text, dur)
                sub = _subtitle_path_filter_arg(work_srt, ffmpeg_cwd=out_mp4.parent, play_res=(w, h))
                vchain = f"{scale_cover},{sub},trim=duration={dur:.6f},setpts=PTS-STARTPTS"
            else:
                vchain = f"{scale_cover},trim=duration={dur:.6f},setpts=PTS-STARTPTS"
            fc = f"[0:v]fps={fps},{vchain}[v]"
            ffmpeg = resolve_ffmpeg_exe()
            cmd = [
                ffmpeg,
                "-y",
                "-stream_loop",
                "-1",
                "-i",
                str(image.resolve()),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-filter_complex",
                fc,
                "-map",
                "[v]",
                "-map",
                "1:a",
                "-t",
                str(dur),
                "-c:v",
                settings.video_codec,
                "-preset",
                "veryfast",
                "-crf",
                "22",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(fps),
                "-keyint_min",
                str(fps),
                "-sc_threshold",
                "0",
                "-c:a",
                settings.audio_codec,
                "-b:a",
                "192k",
                "-r",
                str(fps),
                "-vsync",
                "cfr",
                "-movflags",
                "+faststart",
                str(out_mp4.resolve()),
            ]
            env = dict(os.environ)
            env.setdefault("FONTCONFIG_PATH", "")
            pr = subprocess_run_no_window(
                cmd,
                cwd=str(out_mp4.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            if pr.returncode != 0:
                raise RuntimeError(f"ffmpeg 엔딩 영상 클립 실패:\n{pr.stderr}\n{pr.stdout}")
            return

        eff_norm = normalize_effect(effect)
        freeze_ok = (
            eff_norm != "none"
            and motion_span_sec is not None
            and motion_phase_sec is not None
            and float(motion_span_sec) > 1e-6
        )
        if freeze_ok:
            w, h, fps = settings.width, settings.height, settings.fps
            if burn_subtitles and (subtitle_text or "").strip():
                write_single_cue_srt(work_srt, subtitle_text, dur)
                vf = build_image_motion_frozen_vf(
                    w,
                    h,
                    fps,
                    dur,
                    effect,
                    motion_span_sec=float(motion_span_sec),
                    freeze_phase_sec=float(motion_phase_sec),
                )
                vf += "," + _subtitle_path_filter_arg(
                    work_srt, ffmpeg_cwd=out_mp4.parent, play_res=(w, h)
                )
            else:
                vf = build_image_motion_frozen_vf(
                    w,
                    h,
                    fps,
                    dur,
                    effect,
                    motion_span_sec=float(motion_span_sec),
                    freeze_phase_sec=float(motion_phase_sec),
                )
            input_fps = _compose_static_image_input_framerate(dur)
            ffmpeg = resolve_ffmpeg_exe()
            cmd = [
                ffmpeg,
                "-y",
                "-framerate",
                input_fps,
                "-loop",
                "1",
                "-i",
                str(image.resolve()),
                "-f",
                "lavfi",
                "-i",
                "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-vf",
                vf,
                "-t",
                str(dur),
                "-c:v",
                settings.video_codec,
                "-preset",
                "medium",
                "-crf",
                "20",
                "-tune",
                "stillimage",
                "-pix_fmt",
                "yuv420p",
                "-g",
                str(fps),
                "-keyint_min",
                str(fps),
                "-sc_threshold",
                "0",
                "-c:a",
                settings.audio_codec,
                "-b:a",
                "192k",
                "-r",
                str(fps),
                "-vsync",
                "cfr",
                "-movflags",
                "+faststart",
                str(out_mp4.resolve()),
            ]
            env = dict(os.environ)
            env.setdefault("FONTCONFIG_PATH", "")
            pr = subprocess_run_no_window(
                cmd,
                cwd=str(out_mp4.parent),
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=env,
            )
            if pr.returncode != 0:
                raise RuntimeError(f"ffmpeg 엔딩(고정 화면) 클립 실패:\n{pr.stderr}\n{pr.stdout}")
            return

        render_compose_insert_clip(
            image=image,
            duration_sec=dur,
            subtitle_text=subtitle_text,
            out_mp4=out_mp4,
            settings=settings,
            burn_subtitles=burn_subtitles,
            work_srt=work_srt,
            effect="none",
        )
        return

    w, h, fps = settings.width, settings.height, settings.fps
    if burn_subtitles and (subtitle_text or "").strip():
        write_single_cue_srt(work_srt, subtitle_text, dur)
        vf = f"format=yuv420p,{_subtitle_path_filter_arg(work_srt, ffmpeg_cwd=out_mp4.parent, play_res=(w, h))}"
    else:
        vf = "format=yuv420p"

    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c=black:s={w}x{h}:r={fps}:d={dur}",
        "-f",
        "lavfi",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-vf",
        vf,
        "-c:v",
        settings.video_codec,
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-c:a",
        settings.audio_codec,
        "-b:a",
        "192k",
        "-shortest",
        "-r",
        str(fps),
        "-vsync",
        "cfr",
        "-movflags",
        "+faststart",
        str(out_mp4.resolve()),
    ]
    env = dict(os.environ)
    env.setdefault("FONTCONFIG_PATH", "")
    pr = subprocess_run_no_window(
        cmd,
        cwd=str(out_mp4.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg 엔딩(검은 화면) 클립 실패:\n{pr.stderr}\n{pr.stdout}")


def _compose_scale_cover_vf(w: int, h: int) -> str:
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase:flags=lanczos,"
        f"crop={w}:{h},setsar=1,format=yuv420p"
    )


def render_compose_video_clip(
    *,
    video: Path,
    audio: Path,
    start_sec: float,
    end_sec: float,
    cue_text: str,
    out_mp4: Path,
    settings: RenderSettings,
    burn_subtitles: bool,
    work_srt: Path,
) -> None:
    """MP4 B-roll — Ken Burns 없음, 영상 내장 오디오는 사용하지 않음 (MP3만).

    짧은 MP4가 SRT 구간보다 먼저 끝나지 않도록 루프·trim 으로 영상 길이를 오디오 구간과 맞춥니다.
    """
    dur = max(0.06, float(end_sec) - float(start_sec))
    st = max(0.0, float(start_sec))
    w, h, fps = settings.width, settings.height, settings.fps

    scale_cover = _compose_scale_cover_vf(w, h)
    if burn_subtitles:
        write_single_cue_srt(work_srt, cue_text, dur)
        sub = _subtitle_path_filter_arg(work_srt, ffmpeg_cwd=out_mp4.parent, play_res=(w, h))
        vchain = f"{scale_cover},{sub},trim=duration={dur:.6f},setpts=PTS-STARTPTS"
    else:
        vchain = f"{scale_cover},trim=duration={dur:.6f},setpts=PTS-STARTPTS"

    fc = (
        f"[0:v]fps={fps},{vchain}[v];"
        f"[1:a]atrim=start={st:.6f}:duration={dur:.6f},asetpts=PTS-STARTPTS[a]"
    )

    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-stream_loop",
        "-1",
        "-i",
        str(video.resolve()),
        "-i",
        str(audio.resolve()),
        "-filter_complex",
        fc,
        "-map",
        "[v]",
        "-map",
        "[a]",
        "-t",
        str(dur),
        "-c:v",
        settings.video_codec,
        "-preset",
        "veryfast",
        "-crf",
        "22",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(fps),
        "-keyint_min",
        str(fps),
        "-sc_threshold",
        "0",
        "-c:a",
        settings.audio_codec,
        "-b:a",
        "192k",
        "-r",
        str(fps),
        "-vsync",
        "cfr",
        "-movflags",
        "+faststart",
        str(out_mp4.resolve()),
    ]
    env = dict(os.environ)
    env.setdefault("FONTCONFIG_PATH", "")
    pr = subprocess_run_no_window(
        cmd,
        cwd=str(out_mp4.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg 영상 클립 실패:\n{pr.stderr}\n{pr.stdout}")


def render_compose_clip(
    *,
    image: Path,
    audio: Path,
    start_sec: float,
    end_sec: float,
    cue_text: str,
    out_mp4: Path,
    settings: RenderSettings,
    burn_subtitles: bool,
    work_srt: Path,
    effect: str = "none",
    motion_span_sec: float | None = None,
    motion_phase_sec: float | None = None,
) -> None:
    if is_compose_video_path(image):
        render_compose_video_clip(
            video=image,
            audio=audio,
            start_sec=start_sec,
            end_sec=end_sec,
            cue_text=cue_text,
            out_mp4=out_mp4,
            settings=settings,
            burn_subtitles=burn_subtitles,
            work_srt=work_srt,
        )
        return
    dur = max(0.06, float(end_sec) - float(start_sec))
    st = max(0.0, float(start_sec))
    eff_norm = normalize_effect(effect)
    input_fps = _compose_static_image_input_framerate(dur) if eff_norm != "none" else str(settings.fps)
    # atrim end= 는 경계에서 샘플이 빠질 수 있어 start + -t 로 길이만 맞춤
    af = f"atrim=start={st:.6f}:duration={dur:.6f},asetpts=PTS-STARTPTS"

    if burn_subtitles:
        write_single_cue_srt(work_srt, cue_text, dur)
        vf = _compose_video_vf(
            settings.width,
            settings.height,
            settings.fps,
            dur,
            effect,
            work_srt,
            burn_subtitles=True,
            subtitle_cwd=out_mp4.parent,
            motion_span_sec=motion_span_sec,
            motion_phase_sec=motion_phase_sec,
        )
    else:
        vf = _compose_video_vf(
            settings.width,
            settings.height,
            settings.fps,
            dur,
            effect,
            None,
            burn_subtitles=False,
            motion_span_sec=motion_span_sec,
            motion_phase_sec=motion_phase_sec,
        )

    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-framerate",
        input_fps,
        "-loop",
        "1",
        "-i",
        str(image.resolve()),
        "-i",
        str(audio.resolve()),
        "-vf",
        vf,
        "-af",
        af,
        "-t",
        str(dur),
        "-c:v",
        settings.video_codec,
        "-preset",
        "medium",
        "-crf",
        "20",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-g",
        str(settings.fps),
        "-keyint_min",
        str(settings.fps),
        "-sc_threshold",
        "0",
        "-c:a",
        settings.audio_codec,
        "-b:a",
        "192k",
        "-r",
        str(settings.fps),
        "-vsync",
        "cfr",
        "-movflags",
        "+faststart",
        str(out_mp4.resolve()),
    ]
    env = dict(os.environ)
    env.setdefault("FONTCONFIG_PATH", "")
    pr = subprocess_run_no_window(
        cmd,
        cwd=str(out_mp4.parent),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg compose 클립 실패:\n{pr.stderr}\n{pr.stdout}")


def render_compose_from_assets(
    *,
    audio_mp3: Path | None,
    srt_path: Path,
    images_dir: Path,
    out_mp4: Path,
    settings: RenderSettings | None = None,
    burn_subtitles: bool = True,
    default_effect: str = "none",
    effects_file: Path | None = None,
    assets_root: Path | None = None,
    overrides_path: Path | None = None,
    override_cue_images: dict[int, Path | None] | None = None,
    override_inserts: list[InsertClipSpec] | None = None,
    override_cue_effects: dict[int, str] | None = None,
    override_image_effects: dict[str, str] | None = None,
    progress: ComposeProgressCb | None = None,
    use_audio: bool = True,
) -> Path:
    """part01.srt 큐별 이미지 합성. 이미지는 ``images/SRT_NNN.*`` 번호(초) ≤ 구간 시작 시각(초) 중 최대로 매칭하고,
    해당 파일이 없으면 직전 구간 이미지를 유지합니다. JSON·GUI의 cue_images로 교체·검정 가능.
    ``compose_overrides.json`` 의 ``cue_effects``·``image_effects``(또는 override)로 효과를 지정할 수 있습니다.
    같은 정지 이미지가 연속된 SRT 큐에 걸쳐 있으면 줌/팬 효과는 그 연속 구간 전체에 대해 한 번만 재생되며,
    각 클립은 그 타임라인의 일부만 잘라 씁니다(큐마다 효과가 처음부터 반복되지 않음).
    우선순위: (직전 큐와 같은 이미지면 효과 유지) → 큐별 ``cue_effects`` → ``image_effects`` → ``compose_effects.txt``/기본값."""
    if not srt_path.is_file():
        raise FileNotFoundError(f"SRT 없음: {srt_path}")

    cues = load_srt_cues_ms(srt_path)
    if not cues:
        raise ValueError(f"SRT에 큐가 없습니다: {srt_path}")

    root = (assets_root or images_dir.parent).resolve()
    work = out_mp4.parent / ".compose_work"
    work.mkdir(parents=True, exist_ok=True)
    from shortvid.subtitles import stage_compose_font_for_work

    stage_compose_font_for_work(work)

    clamp_warn = ""
    master_audio: Path
    if use_audio:
        if audio_mp3 is None or not audio_mp3.is_file():
            raise FileNotFoundError(
                "음성 사용이 켜져 있으나 MP3를 찾을 수 없습니다. 파일을 지정하거나 「음성 사용」을 끄세요."
            )
        master_audio = audio_mp3.resolve()
        audio_sec = audio_duration_ffprobe(master_audio)
        cues, clamp_warn = clamp_cues_ms_to_audio(cues, audio_sec)
        if not cues:
            raise ValueError(
                "MP3 재생 길이를 넘는 자막만 있거나 자른 뒤 유효한 큐가 없습니다. 오디오와 SRT 타임코드를 확인하세요."
            )
    else:
        last_ms = max(c[2] for c in cues)
        silent = work / "_silent_timeline.mp3"
        make_silent_mp3(silent, last_ms / 1000.0 + 1.0)
        master_audio = silent

    def _resolve_overrides_file(explicit: Path | None) -> Path | None:
        if explicit is not None:
            p = explicit.resolve()
            if not p.is_file():
                raise FileNotFoundError(f"overrides 파일 없음: {p}")
            return p
        cand = default_overrides_path(root)
        return cand if cand.is_file() else None

    ov_file = _resolve_overrides_file(overrides_path)
    if override_cue_images is not None and override_inserts is not None:
        overrides = dict(override_cue_images)
        inserts = list(override_inserts)
        _, _, cue_fx_disk, img_fx_disk = load_compose_overrides(ov_file, root)
    elif override_cue_images is not None or override_inserts is not None:
        raise ValueError("override_cue_images 와 override_inserts 는 둘 다 지정하거나 둘 다 생략하세요.")
    else:
        overrides, inserts, cue_fx_disk, img_fx_disk = load_compose_overrides(ov_file, root)

    json_fx: dict[int, str] = {}
    json_path = find_srt_image_effects_json(images_dir, root, default_srt_image_output_dir())
    if json_path:
        try:
            json_fx = load_cue_effects_from_srt_image_json(json_path)
        except (OSError, ValueError):
            json_fx = {}

    cue_fx_merged = {**json_fx, **dict(cue_fx_disk)}
    if override_cue_effects:
        cue_fx_merged.update(override_cue_effects)

    img_fx_merged = dict(img_fx_disk)
    if override_image_effects:
        img_fx_merged.update(override_image_effects)

    ins_by = inserts_by_after_cue(inserts)

    for idx, p in overrides.items():
        if p is not None and not p.is_file():
            raise FileNotFoundError(f"cue_images[{idx}] 파일 없음: {p}")
    for ins in inserts:
        if not ins.image.is_file():
            raise FileNotFoundError(f"삽입 이미지 없음: {ins.image}")

    n_cues = len(cues)
    map_ids = [c[0] for c in cues]
    cue_starts = [c[1] for c in cues]
    resolved_imgs = per_cue_images_srt_mapping(
        map_ids, images_dir, overrides, cue_start_ms=cue_starts
    )

    stg = settings or RenderSettings()

    eff_list_cue = effects_for_compose_cues(
        n_cues,
        effects_file=effects_file,
        images_dir=images_dir,
        default_effect=default_effect,
    )
    motion_per_cue = resolved_motion_effects_per_cue(
        map_ids, resolved_imgs, cue_fx_merged, img_fx_merged, eff_list_cue
    )
    span_phase_per_cue = compose_motion_span_phase_per_cue(cues, resolved_imgs)

    clip_seq = 0
    clips: list[Path] = []

    outro_text_resolved = resolve_outro_text(stg.outro_text)
    outro_on = bool(stg.outro_enabled) and float(stg.outro_duration_sec) > 0
    total_steps = len(ins_by.get(0, []))
    for ci in range(1, n_cues + 1):
        total_steps += 1 + len(ins_by.get(ci, []))
    if outro_on:
        total_steps += 1
    total_steps += 1  # concat

    done = 0

    def prog(msg: str) -> None:
        if progress:
            progress(done, total_steps, msg)

    prog(clamp_warn if clamp_warn else "합성 준비…")

    def _next_paths() -> tuple[Path, Path]:
        nonlocal clip_seq
        clip_seq += 1
        return work / f"compose_{clip_seq:04d}.mp4", work / f"compose_{clip_seq:04d}.srt"

    try:
        for ins in ins_by.get(0, []):
            mp, sr = _next_paths()
            render_compose_insert_clip(
                image=ins.image,
                duration_sec=ins.duration_sec,
                subtitle_text=ins.subtitle,
                out_mp4=mp,
                settings=stg,
                burn_subtitles=burn_subtitles,
                work_srt=sr,
                effect=ins.effect,
            )
            clips.append(mp)
            done += 1
            prog(f"삽입 클립 완료 ({done}/{total_steps})")

        for cue_i in range(1, n_cues + 1):
            _map_id, t0, t1, text = cues[cue_i - 1]
            st_s = t0 / 1000.0
            en_s = t1 / 1000.0
            mp, sr = _next_paths()
            img_e = resolved_imgs[cue_i - 1]
            eff = motion_per_cue[cue_i - 1]
            mspan, mphase = span_phase_per_cue[cue_i - 1]
            if img_e is None:
                render_compose_black_clip(
                    audio=master_audio,
                    start_sec=st_s,
                    end_sec=en_s,
                    cue_text=text,
                    out_mp4=mp,
                    settings=stg,
                    burn_subtitles=burn_subtitles,
                    work_srt=sr,
                )
            else:
                render_compose_clip(
                    image=img_e,
                    audio=master_audio,
                    start_sec=st_s,
                    end_sec=en_s,
                    cue_text=text,
                    out_mp4=mp,
                    settings=stg,
                    burn_subtitles=burn_subtitles,
                    work_srt=sr,
                    effect=eff,
                    motion_span_sec=mspan,
                    motion_phase_sec=mphase,
                )
            clips.append(mp)
            done += 1
            prog(f"SRT 큐 {cue_i}/{n_cues} 완료 ({done}/{total_steps})")

            for ins in ins_by.get(cue_i, []):
                mp2, sr2 = _next_paths()
                render_compose_insert_clip(
                    image=ins.image,
                    duration_sec=ins.duration_sec,
                    subtitle_text=ins.subtitle,
                    out_mp4=mp2,
                    settings=stg,
                    burn_subtitles=burn_subtitles,
                    work_srt=sr2,
                    effect=ins.effect,
                )
                clips.append(mp2)
                done += 1
                prog(f"삽입 클립 완료 ({done}/{total_steps})")

        if outro_on:
            mp_outro, sr_outro = _next_paths()
            outro_img = _last_compose_media(resolved_imgs)
            outro_eff, outro_span, freeze_phase = _outro_motion_freeze_state(
                cues,
                motion_per_cue,
                span_phase_per_cue,
                resolved_imgs,
                outro_img,
            )
            render_compose_outro_hold_clip(
                image=outro_img,
                duration_sec=float(stg.outro_duration_sec),
                subtitle_text=outro_text_resolved,
                out_mp4=mp_outro,
                settings=stg,
                burn_subtitles=burn_subtitles,
                work_srt=sr_outro,
                effect=outro_eff,
                motion_span_sec=outro_span,
                motion_phase_sec=freeze_phase,
            )
            clips.append(mp_outro)
            done += 1
            prog(f"엔딩({stg.outro_duration_sec:.1f}초) 완료 ({done}/{total_steps})")

        out_mp4.parent.mkdir(parents=True, exist_ok=True)
        prog(f"세그먼트 연결 중… ({done}/{total_steps})")
        concat_scenes(clips, out_mp4, youtube_faststart=stg.youtube_faststart)
        done += 1
    finally:
        for p in work.glob("compose_*.mp4"):
            try:
                p.unlink()
            except OSError:
                pass
        for p in work.glob("compose_*.srt"):
            try:
                p.unlink()
            except OSError:
                pass

    return out_mp4
