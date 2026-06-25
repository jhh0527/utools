"""CLI: init | parse | assets | render | all."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from scenevid.assets import ensure_layout, make_placeholder_png, make_silent_mp3
from scenevid.compose_render import (
    default_compose_audio,
    default_compose_srt,
    render_compose_from_assets,
)
from scenevid.ffmpeg_render import render_project
from scenevid.schema import DEFAULT_OUTRO_TEXT, RenderSettings, load_project, save_project
from scenevid.script_parse import script_md_to_doc
from scenevid.subtitles import write_scene_srt
from scenevid.assets import audio_duration_ffprobe
from scenevid.media_paths import prepend_local_ffmpeg_bin_to_os_path
from scenevid.repo_paths import (
    default_scenevid_compose_mp4,
    default_scenevid_compose_mp4_name,
)


SAMPLE_SCRIPT = """# 내 첫 장면 영상

## 오프닝

여기는 첫 장면 내레이션입니다. TTS용 문장으로 적습니다.

@image: 저녁 노을 산맥 실사풍 일러스트

@effect: zoom_in

---

## 두 번째 장면

본문 내용입니다. FFmpeg으로 이미지와 음성을 합칩니다.

@image: 도시 스카이라인 블루아워

@effect: pan_right

"""


def cmd_init(project: Path) -> int:
    project.mkdir(parents=True, exist_ok=True)
    ensure_layout(project)
    sp = project / "script.md"
    if not sp.exists():
        sp.write_text(SAMPLE_SCRIPT, encoding="utf-8")
    print(f"폴더 준비: {project}")
    print(f"예시 스크립트: {sp}")
    print(
        "다음(한 줄 예): python -m scenevid all -p .  "
        "| 단계별: parse → assets(TTS·이미지·자막) → render "
        "| 자막만: subtitles -p . "
        "| 산출물만: compose -a <폴더> (part01.mp3 + part01.srt + images/srt_NN.png)"
    )
    return 0


def cmd_parse(project: Path) -> int:
    script = project / "script.md"
    if not script.is_file():
        print(f"없음: {script}", file=sys.stderr)
        return 1
    doc = script_md_to_doc(script)
    outp = project / "scene.json"
    save_project(doc, outp)
    print(f"작성됨 {outp} (장면 {len(doc.scenes)}개)")
    return 0


def cmd_subtitles(project: Path, *, guess_seconds: float) -> int:
    """scene.json + 장면별 MP3(ffprobe 재생 시간)으로 subtitles/*.srt 갱신."""
    jc = project / "scene.json"
    if not jc.is_file():
        print(f"먼저 parse 하세요: {jc}", file=sys.stderr)
        return 1
    doc = load_project(jc)
    if not doc.scenes:
        print("scene.json에 장면이 없습니다.", file=sys.stderr)
        return 1
    ensure_layout(project)

    wrote = 0
    skipped_no_audio = 0
    skipped_no_text = 0

    for sc in doc.scenes:
        img, mp3, srt = sc.resolved_paths(project)
        text = str(sc.narration or "").strip()
        if not text:
            print(f"[건너뜀] {sc.id}: narration 비어 있음", file=sys.stderr)
            skipped_no_text += 1
            continue
        if mp3.is_file():
            try:
                dur = audio_duration_ffprobe(mp3)
            except Exception as e:
                print(f"[오류] {sc.id} ffprobe: {e}", file=sys.stderr)
                return 1
        elif guess_seconds > 0:
            dur = guess_seconds
        else:
            print(f"[건너뜀] {sc.id}: MP3 없음 ({mp3})", file=sys.stderr)
            skipped_no_audio += 1
            continue
        write_scene_srt(srt, sc.narration, dur)
        print(f"SRT: {srt.name} ({dur:.2f}s)")
        wrote += 1

    print(f"\n장면당 자막 완료: {wrote}개 (대본 공백 {skipped_no_text}, MP3 없음 {skipped_no_audio})")
    if wrote == 0 and skipped_no_audio and guess_seconds <= 0:
        print("힌트: MP3가 없으면 --guess-seconds 5 같은 값으로 타임코드 생성이 가능합니다.", file=sys.stderr)
    return 0 if wrote > 0 else 1


def cmd_assets(
    project: Path,
    *,
    placeholder: bool,
    dummy_audio_sec: float,
) -> int:
    jc = project / "scene.json"
    if not jc.is_file():
        print(f"먼저 parse 하세요: {jc}", file=sys.stderr)
        return 1
    doc = load_project(jc)
    ensure_layout(project)

    for sc in doc.scenes:
        img, mp3, srt = sc.resolved_paths(project)
        if not img.is_file():
            if placeholder:
                title = sc.title or sc.id
                try:
                    make_placeholder_png(img, doc.settings.width, doc.settings.height, title=title)
                    print(f"플레이스홀더: {img}")
                except RuntimeError as e:
                    print(str(e), file=sys.stderr)
                    return 1
            else:
                print(f"[경고] 이미지 없음 ( --placeholder 또는 수동 저장 ): {img}", file=sys.stderr)

        need_tts = not mp3.is_file()
        if need_tts and dummy_audio_sec > 0:
            try:
                make_silent_mp3(mp3, dummy_audio_sec)
                print(f"더미 오디오: {mp3} ({dummy_audio_sec}s)")
            except Exception as e:
                print(str(e), file=sys.stderr)
                return 1
        elif need_tts:
            print(
                f"[안내] 오디오 없음. 2_1_ttsToVoice 로 MP3 생성 후 audio/에 넣거나 "
                f"--dummy-audio-sec 로 테스트 → {mp3}",
                file=sys.stderr,
            )

        # 자막: 오디오가 있으면 scene.json narration + ffprobe 길이로 SRT
        if mp3.is_file():
            dur = audio_duration_ffprobe(mp3)
            write_scene_srt(srt, sc.narration, dur)
            print(f"자막: {srt.name}")

    print("assets 단계 완료 (이미지·TTS·subtitles 동기)")
    return 0


def cmd_compose(
    assets: Path,
    *,
    audio: Path | None,
    srt: Path | None,
    images_dir: Path | None,
    out: Path | None,
    no_sub: bool,
    width: int,
    height: int,
    default_effect: str,
    effects_file: Path | None,
    overrides_path: Path | None,
    outro_text: str | None = None,
) -> int:
    """3·4단계 산출물: MP3 + SRT + images/srt_NN.* → output."""
    root = assets.resolve()
    aud = (audio.resolve() if audio else default_compose_audio(root))
    if aud is None or not aud.is_file():
        print(f"오디오 MP3를 찾을 수 없습니다. --audio 또는 {root}/*.mp3", file=sys.stderr)
        return 1
    sr = (srt.resolve() if srt else default_compose_srt(root, aud))
    if sr is None or not sr.is_file():
        print(f"SRT를 찾을 수 없습니다. --srt 또는 {root}/{aud.stem}.srt", file=sys.stderr)
        return 1
    img_dir = (images_dir.resolve() if images_dir else root / "images")
    if not img_dir.is_dir():
        print(f"이미지 폴더 없음: {img_dir}", file=sys.stderr)
        return 1
    outp = (out.resolve() if out else default_scenevid_compose_mp4())
    outp.parent.mkdir(parents=True, exist_ok=True)
    st = RenderSettings(
        width=width,
        height=height,
        outro_text=(outro_text or "").strip(),
    )
    try:
        fp = render_compose_from_assets(
            audio_mp3=aud,
            srt_path=sr,
            images_dir=img_dir,
            out_mp4=outp,
            settings=st,
            burn_subtitles=not no_sub,
            default_effect=default_effect,
            effects_file=effects_file,
            assets_root=root,
            overrides_path=overrides_path,
        )
    except (OSError, ValueError, RuntimeError, FileNotFoundError) as e:
        print(str(e), file=sys.stderr)
        return 1
    print(f"합성 완료: {fp}")
    return 0


def cmd_render(project: Path, *, no_sub: bool) -> int:
    jc = project / "scene.json"
    if not jc.is_file():
        print(f"먼저 parse: {jc}", file=sys.stderr)
        return 1
    doc = load_project(jc)
    ensure_layout(project)
    if not doc.scenes:
        print("장면이 없습니다.", file=sys.stderr)
        return 1
    fp = render_project(doc, project, burn_subtitles=not no_sub)
    print(f"최종: {fp}")
    return 0


def cmd_all(
    project: Path,
    placeholder: bool,
    dummy_audio_sec: float,
    no_sub: bool,
) -> int:
    c = cmd_parse(project)
    if c:
        return c
    c = cmd_assets(
        project,
        placeholder=placeholder,
        dummy_audio_sec=dummy_audio_sec,
    )
    if c:
        return c
    return cmd_render(project, no_sub=no_sub)


def _proj(a: argparse.Namespace) -> Path:
    return getattr(a, "project", Path(".")).resolve()


def main(argv: list[str] | None = None) -> int:
    prepend_local_ffmpeg_bin_to_os_path()
    p = argparse.ArgumentParser(
        prog="scenevid",
        description=(
            "파이프라인: script.md → scene.json → (TTS mp3, 이미지 png, 자막 srt) "
            "→ FFmpeg 합성 → output/final.mp4. "
            "산출물만 합칠 때는 compose (MP3+SRT+images/srt_NN); 기본 MP4 출력은 wisdom/4_1_video/output/yyyymmdd.mp4. 자막만 갱신: subtitles."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_proj(sp: argparse.ArgumentParser) -> None:
        sp.add_argument(
            "--project",
            "-p",
            type=Path,
            default=Path("."),
            help="프로젝트 폴더 (scene.json, audio/, …)",
        )

    ip = sub.add_parser("init", help="폴더 구조 + script.md 예시")
    add_proj(ip)
    ip.set_defaults(_fn=lambda a: cmd_init(_proj(a)))

    pp = sub.add_parser("parse", help="script.md → scene.json")
    add_proj(pp)
    pp.set_defaults(_fn=lambda a: cmd_parse(_proj(a)))

    sp_sub = sub.add_parser(
        "subtitles",
        help="scene.json 장면별 narration + MP3 길이로 subtitles/*.srt 만 생성·갱신",
    )
    add_proj(sp_sub)
    sp_sub.add_argument(
        "--guess-seconds",
        type=float,
        default=0.0,
        help="MP3가 없을 때 장면마다 이 초로 간주해 타임코드 생성(예: 테스트용)",
    )
    sp_sub.set_defaults(_fn=lambda a: cmd_subtitles(_proj(a), guess_seconds=a.guess_seconds))

    ap = sub.add_parser(
        "assets",
        help="이미지·(선택) TTS·자막(srt)=scene+narration+audio 길이",
    )
    add_proj(ap)
    ap.add_argument("--placeholder", action="store_true", help="없으면 Pillow로 PNG 생성")
    ap.add_argument(
        "--dummy-audio-sec",
        type=float,
        default=0.0,
        help="TTS 없이 테스트할 때 무음 mp3 초 (예 2). 음성은 2_1_ttsToVoice 산출물 사용",
    )
    ap.set_defaults(
        _fn=lambda a: cmd_assets(
            _proj(a),
            placeholder=a.placeholder,
            dummy_audio_sec=a.dummy_audio_sec,
        )
    )

    rp = sub.add_parser("render", help="scene.json 기준 FFmpeg 합성")
    add_proj(rp)
    rp.add_argument("--no-sub", action="store_true", help="자막 번인 생략")
    rp.set_defaults(_fn=lambda a: cmd_render(_proj(a), no_sub=a.no_sub))

    cp = sub.add_parser(
        "compose",
        help="한 개 MP3 + SRT + images/SRT_NNN(초≤구간시작초 중 최대, 0초→SRT_000, 없으면 직전 이미지 유지) → 동영상",
    )
    cp.add_argument(
        "--assets",
        "-a",
        type=Path,
        default=Path("."),
        help="산출물이 있는 폴더 (기본: part01.mp3, part01.srt, images/)",
    )
    cp.add_argument("--audio", type=Path, default=None, help="MP3 경로 (미지정 시 part*.mp3 등 자동)")
    cp.add_argument("--srt", type=Path, default=None, help="SRT 경로 (미지정 시 오디오와 같은 stem 또는 part*.srt)")
    cp.add_argument("--images", type=Path, default=None, help="이미지 폴더 (기본: <assets>/images)")
    cp.add_argument(
        "--out",
        "-o",
        type=Path,
        default=None,
        help=f"출력 MP4 (기본: wisdom/4_1_video/output/{default_scenevid_compose_mp4_name()})",
    )
    cp.add_argument(
        "--outro-text",
        type=str,
        default=None,
        help="엔딩 자막 (비우면 자막 없음)"
        if not DEFAULT_OUTRO_TEXT.strip()
        else f"엔딩 자막 (비우면 「{DEFAULT_OUTRO_TEXT}」)",
    )
    cp.add_argument("--no-sub", action="store_true", help="자막 번인 생략")
    cp.add_argument("--width", type=int, default=1920)
    cp.add_argument("--height", type=int, default=1080)
    cp.add_argument(
        "--default-effect",
        type=str,
        default="none",
        help="모든 큐에 동일 적용 (none|pan_left|pan_right|pan_up|pan_down|zoom_in|zoom_out)",
    )
    cp.add_argument(
        "--effects-file",
        type=Path,
        default=None,
        help="한 줄에 큐 순서대로 효과. 미지정이면 <images>/compose_effects.txt 있으면 사용",
    )
    cp.add_argument(
        "--overrides",
        type=Path,
        default=None,
        help="compose_overrides.json 경로. 미지정이면 <assets>/compose_overrides.json 있으면 사용",
    )
    cp.set_defaults(
        _fn=lambda a: cmd_compose(
            Path(a.assets).resolve(),
            audio=a.audio,
            srt=a.srt,
            images_dir=a.images,
            out=a.out,
            no_sub=a.no_sub,
            width=a.width,
            height=a.height,
            default_effect=a.default_effect,
            effects_file=a.effects_file,
            overrides_path=a.overrides,
            outro_text=a.outro_text,
        )
    )

    alp = sub.add_parser(
        "all",
        help="parse + assets(대본·scene.json 반영:TTS·이미지 옵션·자막) + render FFmpeg",
    )
    add_proj(alp)
    alp.add_argument("--placeholder", action="store_true")
    alp.add_argument("--dummy-audio-sec", type=float, default=0.0)
    alp.add_argument("--no-sub", action="store_true")
    alp.set_defaults(
        _fn=lambda a: cmd_all(
            _proj(a),
            placeholder=a.placeholder,
            dummy_audio_sec=a.dummy_audio_sec,
            no_sub=a.no_sub,
        )
    )

    ns = p.parse_args(argv)
    return int(ns._fn(ns))  # type: ignore[arg-type]


if __name__ == "__main__":
    raise SystemExit(main())
