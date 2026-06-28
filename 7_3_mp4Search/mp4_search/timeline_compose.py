# -*- coding: utf-8 -*-
"""MP4 폴더 자산 — SRT 번호(시작 초) 타임라인 합성."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from mp4_search.naming import ALL_MP4_NAME, scan_srt_assets, timeline_asset_number, parse_srt_asset_number


@dataclass(frozen=True)
class TimelineComposeJob:
    """한 타임라인 구간 합성 작업."""

    srt_id: int
    mark_sec: float
    video: Path | None
    image: Path | None
    duration_sec: float
    video_from: int
    image_from: int | None
    video_start_sec: float = 0.0
    image_effect: str = "fixed"
    is_gap: bool = False
    is_hold: bool = False


def merge_asset_maps(
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    *,
    extra_mp4: dict[int, Path] | None = None,
    extra_png: dict[int, Path] | None = None,
) -> tuple[dict[int, Path], dict[int, Path]]:
    """폴더 스캔 + GUI 자산 병합 — 키는 **파일명** ``SRT_NNN`` 번호만 사용."""
    mp4 = dict(mp4_map)
    png = dict(png_map)

    def _merge(extra: dict[int, Path] | None, dest: dict[int, Path]) -> None:
        if not extra:
            return
        for _k, p in extra.items():
            p = Path(p)
            if not p.is_file():
                continue
            num = parse_srt_asset_number(p.name)
            if num is not None:
                dest[int(num)] = p

    _merge(extra_mp4, mp4)
    _merge(extra_png, png)
    return mp4, png


def pick_asset_at_timeline(asset_map: dict[int, Path], timeline_sec: int) -> tuple[int, Path] | None:
    """파일 번호 ≤ ``timeline_sec`` 인 자산 중 **가장 큰** 번호 (4_1_video 이미지 매칭과 동일)."""
    if not asset_map:
        return None
    t = max(0, int(timeline_sec))
    leq = [n for n in asset_map if n <= t]
    if not leq:
        return None
    key = max(leq)
    return key, asset_map[key]


def asset_timeline_mark(asset_key: int, asset_start_times: dict[int, float] | None) -> float:
    """``SRT_NNN`` 파일 번호 → SRT 타임스탬프 시작(초). 없으면 번호(정수) 그대로."""
    if asset_start_times and asset_key in asset_start_times:
        return max(0.0, float(asset_start_times[asset_key]))
    return float(asset_key)


def build_asset_start_times_from_srt(srt_path: Path) -> dict[int, float]:
    """SRT 파일 → ``SRT_NNN`` 번호별 가장 이른 시작(초)."""
    from mp4_search.srt_parse import parse_srt_cues_timed

    starts: dict[int, float] = {}
    srt_path = Path(srt_path)
    if not srt_path.is_file():
        return starts
    for _sid, _text, st_ms, _en_ms in parse_srt_cues_timed(srt_path):
        t = st_ms / 1000.0
        key = timeline_asset_number(t)
        if key not in starts or t < starts[key]:
            starts[key] = t
    return starts


def folder_asset_display_owners(
    asset_map: dict[int, Path],
    cues: list[tuple[int, str, int, int]],
    asset_start_times: dict[int, float] | None = None,
) -> dict[int, int]:
    """폴더 ``SRT_NNN`` 자산 → 그리드에 표시할 SRT map_id (타임라인 전환 첫 줄).

    파일 번호 N의 시작 시각은 ``asset_start_times[N]`` (없으면 N초)이며,
    그 시각 이후 첫 자막 줄에 MP4/PNG 파일명을 표시한다.
    """
    owners: dict[int, int] = {}
    sorted_cues = sorted(cues, key=lambda c: c[2])
    for fk in sorted(asset_map.keys()):
        mark = asset_timeline_mark(fk, asset_start_times)
        for sid, _text, st_ms, _en_ms in sorted_cues:
            if st_ms / 1000.0 >= mark - 0.001:
                owners[fk] = sid
                break
    return owners


def folder_asset_for_cue_row(
    srt_id: int,
    asset_sec: int,
    asset_map: dict[int, Path],
    owners: dict[int, int],
    *,
    owns_asset: bool,
) -> Path | None:
    """한 SRT 줄에 표시할 폴더 자산 (정확 번호 우선, 없으면 전환 줄 매칭)."""
    if not owns_asset:
        return None
    exact = asset_map.get(asset_sec)
    if exact is not None:
        return exact
    for fk, owner_sid in owners.items():
        if owner_sid == srt_id:
            return asset_map[fk]
    return None


def missing_timeline_mp4_slots(
    mp4_map: dict[int, Path],
    asset_start_times: dict[int, float] | None,
    *,
    expected_slots: set[int] | frozenset[int] | None = None,
) -> list[int]:
    """MP4가 없는데 사용자가 지정한 슬롯 (합성 전 경고용).

    ``expected_slots`` 가 없으면 경고하지 않는다.
    자막만 있고 MP4·다운로드 지정이 없는 초(예: 26·28·30)는 누락으로 보지 않는다.
    """
    _ = asset_start_times
    if not expected_slots:
        return []
    missing: list[int] = []
    for k in sorted(int(x) for x in expected_slots):
        if k not in mp4_map:
            missing.append(k)
    return missing


def timeline_mark_asset_keys(
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    asset_start_times: dict[int, float] | None,
) -> set[int]:
    """합성 타임라인 마크 — MP4 파일 번호만 (PNG·SRT 줄 번호는 제외)."""
    _ = png_map
    _ = asset_start_times
    return set(mp4_map.keys())


def lookup_mark_schedule(schedule: dict[float, int], mark_sec: float) -> int | None:
    """``mark_sec`` 에 해당하는 자산 번호 (부동소수 오차 허용)."""
    if not schedule:
        return None
    if mark_sec in schedule:
        return schedule[mark_sec]
    for t, key in schedule.items():
        if abs(float(t) - float(mark_sec)) < 0.001:
            return key
    return None


def asset_mark_schedule(
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    asset_start_times: dict[int, float] | None,
) -> dict[float, int]:
    """타임라인 시작 시각 → 자산 파일 번호."""
    schedule: dict[float, int] = {}
    for k in sorted(timeline_mark_asset_keys(mp4_map, png_map, asset_start_times)):
        schedule[asset_timeline_mark(k, asset_start_times)] = int(k)
    return schedule


def next_timeline_mark_after(
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    after_sec: float,
    *,
    asset_start_times: dict[int, float] | None = None,
) -> float | None:
    """``after_sec`` 보다 큰 다음 MP4·PNG 시작 시각(초)."""
    marks = [
        asset_timeline_mark(k, asset_start_times)
        for k in timeline_mark_asset_keys(mp4_map, png_map, asset_start_times)
    ]
    later = [m for m in marks if m > float(after_sec) + 0.001]
    return min(later) if later else None


def timeline_total_sec(
    segments: list[tuple[float, float]],
    *,
    cue_end_times: list[float] | None = None,
) -> float:
    """SRT 구간 기준 타임라인 끝(초)."""
    ends: list[float] = []
    if segments:
        ends.append(max(float(s) + max(0.0, float(dur)) for s, dur in segments))
    if cue_end_times:
        ends.extend(float(t) for t in cue_end_times if t > 0)
    return max(ends) if ends else 0.0


def timeline_end_sec(
    segments: list[tuple[float, float]],
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    *,
    cue_end_times: list[float] | None = None,
    audio_sec: float | None = None,
    asset_start_times: dict[int, float] | None = None,
) -> float:
    """합성 타임라인 전체 길이(초)."""
    seg_end = timeline_total_sec(segments, cue_end_times=cue_end_times)
    keys = sorted(timeline_mark_asset_keys(mp4_map, png_map, asset_start_times))
    if seg_end <= 0 and not keys:
        if audio_sec and audio_sec > 0:
            return float(audio_sec)
        return 0.0
    end = seg_end
    if keys:
        asset_mark = max(keys)
        last_t = asset_timeline_mark(asset_mark, asset_start_times)
        nxt = next_timeline_mark_after(
            mp4_map,
            png_map,
            last_t,
            asset_start_times=asset_start_times,
        )
        if nxt:
            end = max(end, nxt)
        else:
            end = max(end, last_t + 3.0)
        end = max(end, last_t + 1.0)
    if audio_sec and audio_sec > 0:
        end = max(end, float(audio_sec))
    return end


def clip_duration_until_next_asset(
    asset_key: int,
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    *,
    total_end: float | None = None,
    asset_start_times: dict[int, float] | None = None,
) -> float | None:
    """적용 종료초 미지정 시 — 다음 영상/이미지 시작까지 길이(초)."""
    start_t = asset_timeline_mark(asset_key, asset_start_times)
    nxt = next_timeline_mark_after(
        mp4_map,
        png_map,
        start_t,
        asset_start_times=asset_start_times,
    )
    if nxt is not None:
        return max(0.1, float(nxt - start_t))
    if total_end is not None and total_end > start_t:
        return max(0.1, float(total_end - start_t))
    return None


def pick_image_for_segment(
    mp4_map: dict[int, Path],
    png_map: dict[int, Path],
    mark_sec: float,
    vid_key: int,
) -> tuple[int, Path] | None:
    """PNG 오버레이 — ``mark_sec`` 시점에 해당 MP4 구간 위에 표시할 PNG."""
    hit_i = pick_asset_at_timeline(png_map, int(mark_sec))
    if not hit_i:
        return None
    img_key, image = hit_i
    v_at_img = pick_asset_at_timeline(mp4_map, img_key)
    if not v_at_img or v_at_img[0] != vid_key:
        return None
    return img_key, image


def png_overlay_mark_times(
    png_map: dict[int, Path],
    asset_start_times: dict[int, float] | None,
) -> set[float]:
    """PNG 시작 시각 — MP4와 번호가 달라도 구간 분할용."""
    return {asset_timeline_mark(k, asset_start_times) for k in png_map}


def list_timeline_compose_jobs(
    folder: Path,
    segments: list[tuple[float, float]],
    *,
    cue_end_times: list[float] | None = None,
    audio_sec: float | None = None,
    extra_mp4: dict[int, Path] | None = None,
    extra_png: dict[int, Path] | None = None,
    png_effects: dict[int, str] | None = None,
    asset_start_times: dict[int, float] | None = None,
) -> list[TimelineComposeJob]:
    """타임라인 자산 변경 지점마다 하나의 클립 — 다음 MP4·PNG 전까지 유지.

    - ``SRT_NNN`` 번호 = 파일명, 시작 시각 = SRT 타임스탬프(``asset_start_times``)
    - 구간 길이 = 다음 자산 시작(또는 SRT 끝) − 시작
    """
    mp4_map, png_map = merge_asset_maps(
        *scan_srt_assets(folder),
        extra_mp4=extra_mp4,
        extra_png=extra_png,
    )
    if not mp4_map:
        return []

    total_end = timeline_end_sec(
        segments,
        mp4_map,
        png_map,
        cue_end_times=cue_end_times,
        audio_sec=audio_sec,
        asset_start_times=asset_start_times,
    )
    mark_schedule = asset_mark_schedule(mp4_map, png_map, asset_start_times)
    if mark_schedule:
        total_end = max(total_end, max(mark_schedule.keys()) + 1.0)
    if total_end <= 0.05:
        return []

    marks = sorted(
        {
            0.0,
            float(total_end),
            *mark_schedule.keys(),
            *png_overlay_mark_times(png_map, asset_start_times),
        }
    )
    jobs: list[TimelineComposeJob] = []
    prev_vid_key: int | None = None
    prev_vid_offset = 0.0
    last_video: Path | None = None
    last_vid_key: int | None = None

    for i, start in enumerate(marks[:-1]):
        end = min(marks[i + 1], total_end)
        duration = end - start
        if duration <= 0.05:
            continue
        switch_key = lookup_mark_schedule(mark_schedule, start)
        start_i = switch_key if switch_key is not None else int(start)

        if switch_key is not None and switch_key in mp4_map:
            vid_key, video = switch_key, mp4_map[switch_key]
            video_start = 0.0
        elif switch_key is not None:
            if last_video and last_video.is_file():
                jobs.append(
                    TimelineComposeJob(
                        srt_id=start_i,
                        mark_sec=start,
                        video=last_video,
                        image=None,
                        duration_sec=duration,
                        video_from=last_vid_key or 0,
                        image_from=None,
                        is_hold=True,
                    )
                )
            else:
                jobs.append(
                    TimelineComposeJob(
                        srt_id=start_i,
                        mark_sec=start,
                        video=None,
                        image=None,
                        duration_sec=duration,
                        video_from=0,
                        image_from=None,
                        is_gap=True,
                    )
                )
            continue
        else:
            hit_v = pick_asset_at_timeline(mp4_map, start_i)
            if not hit_v:
                if last_video and last_video.is_file():
                    jobs.append(
                        TimelineComposeJob(
                            srt_id=start_i,
                            mark_sec=start,
                            video=last_video,
                            image=None,
                            duration_sec=duration,
                            video_from=last_vid_key or 0,
                            image_from=None,
                            is_hold=True,
                        )
                    )
                else:
                    jobs.append(
                        TimelineComposeJob(
                            srt_id=start_i,
                            mark_sec=start,
                            video=None,
                            image=None,
                            duration_sec=duration,
                            video_from=0,
                            image_from=None,
                            is_gap=True,
                        )
                    )
                continue
            vid_key, video = hit_v
            if vid_key == prev_vid_key:
                video_start = prev_vid_offset
            else:
                video_start = 0.0

        hit_i = pick_image_for_segment(mp4_map, png_map, start, vid_key)
        image = hit_i[1] if hit_i else None
        img_key = hit_i[0] if hit_i else None
        img_effect = "fixed"
        if img_key is not None and png_effects:
            img_effect = png_effects.get(int(img_key), "fixed")

        jobs.append(
            TimelineComposeJob(
                srt_id=start_i,
                mark_sec=start,
                video=video,
                image=image,
                duration_sec=duration,
                video_from=vid_key,
                image_from=img_key,
                video_start_sec=video_start,
                image_effect=img_effect,
            )
        )
        prev_vid_key = vid_key
        prev_vid_offset = video_start + duration
        last_video = video
        last_vid_key = vid_key
    return jobs


def format_jobs_timeline_summary(
    jobs: list[TimelineComposeJob],
    *,
    max_lines: int = 8,
) -> str:
    """합성 구간 요약 — ``all.mp4`` 재생 시각 안내."""
    lines: list[str] = []
    pos = 0.0
    for j in jobs:
        end = pos + j.duration_sec
        if j.is_gap:
            label = "(빈 구간)"
        elif j.video:
            label = j.video.name + (" (정지)" if j.is_hold else "")
            if j.image:
                label += f" + {j.image.name}"
        else:
            label = "?"
        lines.append(f"  {pos:g}~{end:g}초 — {label}")
        pos = end
    if len(lines) > max_lines:
        extra = len(lines) - max_lines
        lines = lines[:max_lines]
        lines.append(f"  … 외 {extra}구간")
    return "\n".join(lines)


def format_timeline_compose_status(
    folder: Path,
    segments: list[tuple[float, float]] | None = None,
    *,
    cue_end_times: list[float] | None = None,
    audio_sec: float | None = None,
    extra_mp4: dict[int, Path] | None = None,
    extra_png: dict[int, Path] | None = None,
    asset_start_times: dict[int, float] | None = None,
) -> str:
    mp4_map, png_map = merge_asset_maps(
        *scan_srt_assets(folder),
        extra_mp4=extra_mp4,
        extra_png=extra_png,
    )
    lines = [f"폴더: {folder}", "", "SRT_NNN = 파일명 · 시작 = SRT 타임스탬프(초)."]
    lines.append("이미지는 해당 MP4 구간에서만 표시 (다음 MP4 시작 시 제거).")
    if not mp4_map and not png_map:
        lines.append("\nSRT_NNN.mp4 / SRT_NNN.png·jpg 파일이 없습니다.")
        return "\n".join(lines)
    missing = missing_timeline_mp4_slots(mp4_map, asset_start_times)
    if missing:
        names = ", ".join(f"SRT_{k:03d}.mp4" for k in missing[:6])
        extra = f" … 외 {len(missing) - 6}개" if len(missing) > 6 else ""
        lines.append(
            f"\n[주의] SRT 시작 슬롯인데 MP4 없음 — 이전 영상이 다음 파일까지 유지됩니다: {names}{extra}"
        )
    if mp4_map:
        lines.append(f"\n[MP4] {len(mp4_map)}개")
        for k in sorted(mp4_map)[:10]:
            st = asset_timeline_mark(k, asset_start_times)
            nxt = next_timeline_mark_after(
                mp4_map,
                png_map,
                st,
                asset_start_times=asset_start_times,
            )
            end_l = f"{nxt:g}초~" if nxt else "끝~"
            lines.append(f"  · {mp4_map[k].name}  (시작 {st:g}초 → {end_l})")
        if len(mp4_map) > 10:
            lines.append(f"  … 외 {len(mp4_map) - 10}개")
    if png_map:
        lines.append(f"\n[이미지] {len(png_map)}개")
        for k in sorted(png_map)[:10]:
            st = asset_timeline_mark(k, asset_start_times)
            lines.append(f"  · {png_map[k].name}  (시작 {st:g}초~)")
        if len(png_map) > 10:
            lines.append(f"  … 외 {len(png_map) - 10}개")
    if segments:
        jobs = list_timeline_compose_jobs(
            folder,
            segments,
            cue_end_times=cue_end_times,
            audio_sec=audio_sec,
            extra_mp4=extra_mp4,
            extra_png=extra_png,
            asset_start_times=asset_start_times,
        )
        total = timeline_end_sec(
            segments,
            mp4_map,
            png_map,
            cue_end_times=cue_end_times,
            audio_sec=audio_sec,
            asset_start_times=asset_start_times,
        )
        lines.append(f"\n[합성 구간] {len(jobs)}클립 · 타임라인 ~{total:g}초 → {ALL_MP4_NAME}")
        for job in jobs[:8]:
            at = f"{job.mark_sec:g}"
            if job.is_gap:
                lines.append(f"  · {job.duration_sec:g}초 @ {at}초 ← (빈 구간)")
                continue
            if job.is_hold:
                vid = job.video.name if job.video else "?"
                lines.append(f"  · {job.duration_sec:g}초 @ {at}초 ← {vid} (정지)")
                continue
            img = job.image.name if job.image else "(없음)"
            vid = job.video.name if job.video else "?"
            lines.append(
                f"  · {job.duration_sec:g}초 @ {at}초 ← {vid}"
                + (f" + {img}" if job.image else "")
            )
        if len(jobs) > 8:
            lines.append(f"  … 외 {len(jobs) - 8}클립")
    return "\n".join(lines)


def compose_asset_statuses(
    jobs: list[TimelineComposeJob],
    mp4_map: dict[int, Path],
    asset_start_times: dict[int, float] | None,
) -> dict[int, str]:
    """자산 번호별 합성 결과 — GUI 「합성」 컬럼용."""
    switch: set[int] = set()
    hold: set[int] = set()
    for j in jobs:
        if j.is_gap or not j.video:
            continue
        vf = int(j.video_from)
        if j.is_hold:
            hold.add(vf)
        else:
            switch.add(vf)

    statuses: dict[int, str] = {}
    keys: set[int] = set(mp4_map.keys())
    if asset_start_times:
        keys |= set(asset_start_times.keys())
    for k in sorted(keys):
        if k not in mp4_map:
            if asset_start_times and k in asset_start_times:
                statuses[k] = "누락"
            continue
        if k in switch:
            statuses[k] = "합성완료·연장" if k in hold else "합성완료"
        elif k in hold:
            statuses[k] = "연장만"
        else:
            statuses[k] = "미포함"
    return statuses


def format_compose_debug_log(
    *,
    mp4_dir: Path,
    srt_path: Path | None = None,
    mp3_path: Path | None = None,
    mp4_map: dict[int, Path] | None = None,
    png_map: dict[int, Path] | None = None,
    folder_mp4: dict[int, Path] | None = None,
    folder_png: dict[int, Path] | None = None,
    extra_mp4: dict[int, Path] | None = None,
    extra_png: dict[int, Path] | None = None,
    asset_start_times: dict[int, float] | None = None,
    jobs: list[TimelineComposeJob] | None = None,
    row_lines: list[str] | None = None,
    phase: str = "plan",
    result_path: Path | None = None,
    stopped: bool = False,
) -> str:
    """합성 디버그 로그 — GUI 로그 영역·사용자 제출용."""
    from datetime import datetime

    mp4_map = dict(mp4_map or {})
    png_map = dict(png_map or {})
    lines: list[str] = [
        f"=== 7_3 mp4Search 합성 로그 [{phase}] {datetime.now():%Y-%m-%d %H:%M:%S} ===",
        f"MP4 폴더: {mp4_dir}",
    ]
    if srt_path:
        lines.append(f"SRT: {srt_path}")
    if mp3_path:
        lines.append(f"MP3: {mp3_path}")
    if result_path:
        lines.append(f"결과: {result_path}" + (" (중지)" if stopped else ""))

    if folder_mp4 is not None:
        lines.append("")
        lines.append("[폴더 스캔 MP4]")
        for k in sorted(folder_mp4):
            lines.append(f"  {k:03d} → {folder_mp4[k].name}")
        if not folder_mp4:
            lines.append("  (없음)")

    if folder_png is not None:
        lines.append("")
        lines.append("[폴더 스캔 PNG]")
        for k in sorted(folder_png):
            lines.append(f"  {k:03d} → {folder_png[k].name}")
        if not folder_png:
            lines.append("  (없음)")

    if extra_mp4:
        lines.append("")
        lines.append("[GUI 행 MP4 (병합 전 extra)]")
        for k, p in sorted(extra_mp4.items(), key=lambda x: x[0]):
            num = parse_srt_asset_number(Path(p).name)
            lines.append(f"  키={k} 파일번호={num} → {Path(p).name}")

    if extra_png:
        lines.append("")
        lines.append("[GUI 행 PNG (병합 전 extra)]")
        for k, p in sorted(extra_png.items(), key=lambda x: x[0]):
            num = parse_srt_asset_number(Path(p).name)
            lines.append(f"  키={k} 파일번호={num} → {Path(p).name}")

    lines.append("")
    lines.append("[병합 MP4 맵 — 키=파일명 SRT_NNN 번호]")
    for k in sorted(mp4_map):
        st = asset_timeline_mark(k, asset_start_times)
        lines.append(f"  {k:03d} @ {st:g}초 → {mp4_map[k].name}")

    if png_map:
        lines.append("")
        lines.append("[병합 PNG 맵]")
        for k in sorted(png_map):
            st = asset_timeline_mark(k, asset_start_times)
            lines.append(f"  {k:03d} @ {st:g}초 → {png_map[k].name}")

    if asset_start_times:
        lines.append("")
        lines.append("[SRT 시작 시각 → 파일 번호]")
        for k in sorted(asset_start_times):
            mark = asset_timeline_mark(k, asset_start_times)
            fn = mp4_map.get(k)
            fn_s = fn.name if fn else "(파일 없음)"
            lines.append(f"  SRT_{k:03d} → {mark:g}초 · {fn_s}")

    schedule = asset_mark_schedule(mp4_map, png_map, asset_start_times)
    if schedule:
        lines.append("")
        lines.append("[타임라인 마크 (시작초 → 파일번호)]")
        for t in sorted(schedule):
            lines.append(f"  {t:g}초 → SRT_{schedule[t]:03d}")

    missing = missing_timeline_mp4_slots(mp4_map, asset_start_times)
    if missing:
        lines.append("")
        lines.append("[누락 슬롯 — 이전 MP4가 다음까지 연장]")
        for k in missing:
            st = asset_timeline_mark(k, asset_start_times)
            lines.append(f"  SRT_{k:03d} @ {st:g}초")

    if row_lines:
        lines.append("")
        lines.append("[목록 행 (SRT# · 시작초 · MP4)]")
        lines.extend(f"  {ln}" for ln in row_lines[:40])
        if len(row_lines) > 40:
            lines.append(f"  … 외 {len(row_lines) - 40}행")

    if jobs is not None:
        lines.append("")
        lines.append(f"[합성 클립 {len(jobs)}개]")
        pos = 0.0
        for i, j in enumerate(jobs, 1):
            end = pos + j.duration_sec
            if j.is_gap:
                kind = "빈구간"
            elif j.is_hold:
                kind = "연장"
            else:
                kind = "재생"
            vid = j.video.name if j.video else "-"
            img = f" + {j.image.name}" if j.image else ""
            lines.append(
                f"  #{i:02d} {pos:g}~{end:g}초 mark={j.mark_sec:g} "
                f"from={j.video_from:03d} [{kind}] {vid}{img}"
            )
            pos = end

        statuses = compose_asset_statuses(jobs, mp4_map, asset_start_times)
        if statuses:
            lines.append("")
            lines.append("[자산별 합성 상태]")
            for k in sorted(statuses):
                st = asset_timeline_mark(k, asset_start_times)
                lines.append(f"  SRT_{k:03d} @ {st:g}초 → {statuses[k]}")

        lines.append("")
        lines.append("[재생 시각 요약]")
        lines.append(format_jobs_timeline_summary(jobs, max_lines=20))

    return "\n".join(lines)
