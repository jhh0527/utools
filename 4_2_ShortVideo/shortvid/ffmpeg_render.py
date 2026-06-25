"""장면별 MP4 렌더 + concat → final.mp4."""

from __future__ import annotations

import os
from pathlib import Path

from shortvid.assets import audio_duration_ffprobe
from shortvid.subprocess_util import subprocess_run_no_window
from shortvid.media_paths import ffmpeg_executable
from shortvid.motion import build_image_motion_vf, scene_effective_motion
from shortvid.schema import ProjectDoc, Scene
from shortvid.subtitles import (
    COMPOSE_SUBTITLE_FONT_FILE,
    COMPOSE_SUBTITLE_FORCE_STYLE,
    stage_compose_font_for_work,
)


def resolve_ffmpeg_exe() -> str:
    ff = ffmpeg_executable()
    if not ff:
        raise RuntimeError(
            "ffmpeg 를 찾을 수 없습니다. wisdom/tools/ffmpeg/bin 에 두거나 PATH를 설정하세요.\n"
            "https://ffmpeg.org/download.html"
        )
    return ff


def _escape_ffmpeg_force_style(style: str) -> str:
    """FFmpeg 필터 옵션 구분자(쉼표)와 충돌하지 않도록 ASS force_style 이스케이프."""
    return style.replace("\\", r"\\").replace(",", r"\,").replace("'", r"\'")


def _fontsdir_filter_opt(ffmpeg_cwd: Path | None) -> str:
    """``fontsdir`` — Windows 절대 경로(C:)는 필터 ``:`` 구분자와 충돌하므로 cwd 기준 상대 경로만."""
    if ffmpeg_cwd is None:
        return ""
    cwd = ffmpeg_cwd.resolve()
    for fonts_dir in (cwd / ".compose_work" / "fonts", cwd / "fonts"):
        if (fonts_dir / COMPOSE_SUBTITLE_FONT_FILE).is_file():
            try:
                rel = fonts_dir.relative_to(cwd).as_posix()
            except ValueError:
                continue
            return f":fontsdir={rel}"
    return ""


def _subtitle_path_filter_arg(
    srt: Path,
    *,
    ffmpeg_cwd: Path | None = None,
    play_res: tuple[int, int] = (1920, 1080),
) -> str:
    """subtitles 필터용 ``filename=…:charenc=UTF-8:force_style=…`` 문자열.

    FFmpeg 8.x 는 ``subtitles='C:/…'`` 처럼 드라이브 글자 앞뒤가 잘려 ``original_size`` 등으로
    잘못 해석하는 경우가 있어, (1) ffmpeg cwd 와 같은 디렉터리면 **파일명만**,
    (2) 그 외 Windows 절대 경로는 ``filename=C\\:/path`` (movie 필터와 동일한 ``\\:`` 이스케이프),
    (3) 그 외는 ``filename=`` + POSIX 경로 를 씁니다.

    ``force_style`` 안의 쉼표는 ``\\,`` 로 이스케이프하지 않으면 ``FontSize`` 등이 잘려
    libass 기본 크기만 적용됩니다(스타일 변경이 영상에 반영되지 않음).
    """
    s_abs = srt.resolve()
    pw, ph = play_res
    fs = _escape_ffmpeg_force_style(COMPOSE_SUBTITLE_FORCE_STYLE)
    fonts_opt = _fontsdir_filter_opt(ffmpeg_cwd)
    ch = f"charenc=UTF-8:original_size={pw}x{ph}:force_style='{fs}'{fonts_opt}"

    def _with_filename(path_for_filter: str) -> str:
        # path_for_filter 안에 작은따옴표·콤마 등이 있으면 추가 이스케이프 필요할 수 있음
        if "'" in path_for_filter or ":" in path_for_filter or "," in path_for_filter or " " in path_for_filter:
            esc = path_for_filter.replace("\\", r"\\").replace(":", r"\:").replace("'", r"\'")
            return f"subtitles=filename='{esc}':{ch}"
        return f"subtitles=filename={path_for_filter}:{ch}"

    if ffmpeg_cwd is not None:
        cwd_r = ffmpeg_cwd.resolve()
        try:
            if s_abs.parent == cwd_r or os.path.samefile(s_abs.parent, cwd_r):
                return _with_filename(s_abs.name)
        except (FileNotFoundError, OSError):
            pass
        try:
            rel = s_abs.relative_to(cwd_r).as_posix()
            return _with_filename(rel)
        except ValueError:
            pass

    p = s_abs.as_posix().replace("\\", "/")
    if len(p) >= 2 and p[1] == ":" and p[0].isalpha():
        # Windows 드라이브: C:/x → C\:/x (필터 문자열에 백슬래시 하나)
        esc = f"{p[0]}\\:{p[2:]}"
        return f"subtitles=filename={esc}:{ch}"
    return _with_filename(p)


def render_one_scene(
    scene: Scene,
    root: Path,
    doc: ProjectDoc,
    *,
    burn_subtitles: bool = True,
) -> Path:
    img, mp3, srt = scene.resolved_paths(root)
    out_dir = root / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    scene_mp4 = out_dir / f"{scene.id}.mp4"

    if not img.is_file():
        raise FileNotFoundError(f"이미지 없음: {img}")
    if not mp3.is_file():
        raise FileNotFoundError(f"오디오 없음: {mp3}")

    duration = audio_duration_ffprobe(mp3)

    from shortvid.subtitles import write_scene_srt

    if burn_subtitles and scene.narration.strip():
        if not srt.is_file():
            write_scene_srt(srt, scene.narration, duration)
        sub_vf = "," + _subtitle_path_filter_arg(
            srt,
            ffmpeg_cwd=root,
            play_res=(doc.settings.width, doc.settings.height),
        )
    else:
        sub_vf = ""

    w, h = doc.settings.width, doc.settings.height
    fps = doc.settings.fps
    eff = scene_effective_motion(scene.image_effect, doc.settings.default_image_effect)
    vf_base = build_image_motion_vf(w, h, fps, duration, eff)
    vf = vf_base + sub_vf

    ffmpeg = resolve_ffmpeg_exe()
    cmd = [
        ffmpeg,
        "-y",
        "-loop",
        "1",
        "-i",
        str(img.resolve()),
        "-i",
        str(mp3.resolve()),
        "-vf",
        vf,
        "-c:v",
        doc.settings.video_codec,
        "-preset",
        "medium",
        "-crf",
        "20",
        "-tune",
        "stillimage",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        doc.settings.audio_codec,
        "-b:a",
        "192k",
        "-shortest",
        "-r",
        str(fps),
        "-movflags",
        "+faststart",
        str(scene_mp4.resolve()),
    ]

    env = dict(os.environ)
    env.setdefault("FONTCONFIG_PATH", "")
    pr = subprocess_run_no_window(cmd, cwd=str(root), capture_output=True, text=True, encoding="utf-8", errors="replace")
    if pr.returncode != 0:
        raise RuntimeError(f"ffmpeg 장면 실패 [{scene.id}]:\n{pr.stderr}\n{pr.stdout}")
    return scene_mp4


def concat_scenes(scene_mp4s: list[Path], final_out: Path, *, youtube_faststart: bool) -> None:
    if not scene_mp4s:
        raise ValueError("연결할 scene mp4 없음")

    ffmpeg = resolve_ffmpeg_exe()
    if len(scene_mp4s) == 1:
        one = scene_mp4s[0].resolve()
        if youtube_faststart:
            cmd = [ffmpeg, "-y", "-i", str(one), "-movflags", "+faststart", "-c", "copy", str(final_out.resolve())]
            r = subprocess_run_no_window(cmd, cwd=str(final_out.parent), capture_output=True, text=True)
            if r.returncode != 0:
                raise RuntimeError(f"ffmpeg faststart 실패:\n{r.stderr}")
        else:
            import shutil as sh

            sh.copy(one, final_out)
        return

    list_path = final_out.parent / "_concat_list.txt"
    lines = []
    for p in scene_mp4s:
        ap = p.resolve().as_posix().replace("'", "'\\''")
        lines.append(f"file '{ap}'")

    list_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    temp_out = final_out.parent / "_final_nomove.mp4"
    cmd1 = [
        ffmpeg,
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-c",
        "copy",
        str(temp_out.resolve()),
    ]
    r1 = subprocess_run_no_window(cmd1, cwd=str(final_out.parent), capture_output=True, text=True)
    if r1.returncode != 0:
        try:
            list_path.unlink()
        except OSError:
            pass
        raise RuntimeError(f"ffmpeg concat 실패:\n{r1.stderr}")

    try:
        if youtube_faststart:
            cmd2 = [
                ffmpeg,
                "-y",
                "-i",
                str(temp_out),
                "-movflags",
                "+faststart",
                "-c",
                "copy",
                str(final_out.resolve()),
            ]
            r2 = subprocess_run_no_window(cmd2, cwd=str(final_out.parent), capture_output=True, text=True)
            if r2.returncode != 0:
                raise RuntimeError(f"ffmpeg faststart 최종 패스 실패:\n{r2.stderr}")
        else:
            import shutil as sh

            if final_out.exists():
                final_out.unlink()
            sh.move(str(temp_out), str(final_out))
    finally:
        if temp_out.exists():
            try:
                temp_out.unlink()
            except OSError:
                pass
        try:
            list_path.unlink()
        except OSError:
            pass


def render_project(
    doc: ProjectDoc,
    root: Path,
    *,
    burn_subtitles: bool = True,
) -> Path:
    """모든 장면 렌더 후 output/final.mp4."""
    clips: list[Path] = []
    for sc in doc.scenes:
        clips.append(render_one_scene(sc, root, doc, burn_subtitles=burn_subtitles))
    final_mp4 = root / "output" / "final.mp4"
    concat_scenes(clips, final_mp4, youtube_faststart=doc.settings.youtube_faststart)
    return final_mp4
