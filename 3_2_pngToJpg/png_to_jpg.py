#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PNG → 유튜브·영상 파이프라인용 JPEG (SRT_XXX.jpg).

- 파일명의 숫자(srt_00, SRT_000, image_023, 22 등) → ``SRT_000.jpg`` … ``SRT_NNN.jpg`` (번호=시작초)
- 최대 1920×1080 (비율 유지, 업스케일 없음)
- JPEG progressive·optimize (기본 품질 88)
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from png2jpg.converter import convert_images
from png2jpg.paths import PROJECT_DIRNAME, default_input_dir, default_output_dir


def run_cli(
    input_dir: Path,
    output_dir: Path,
    *,
    recursive: bool,
    include_jpg: bool,
    quality: int,
) -> int:
    try:
        results, skipped = convert_images(
            input_dir,
            output_dir,
            recursive=recursive,
            include_jpg=include_jpg,
            quality=quality,
        )
    except (OSError, ValueError) as e:
        print(f"오류: {e}", file=sys.stderr)
        return 1

    for r in results:
        note = f"\t{r.match_note}" if r.match_note else ""
        print(
            f"{r.output.name}\t← {r.source.name}\t"
            f"{r.bytes_before // 1024}KB → {r.bytes_after // 1024}KB\t"
            f"{r.size_px[0]}×{r.size_px[1]}{note}"
        )
    for s in skipped:
        print(f"건너뜀: {s.source.name}\t{s.reason}", file=sys.stderr)

    total_saved = sum(r.saved_bytes for r in results)
    print(
        f"\n완료: {len(results)}개 저장, 건너뜀 {len(skipped)}개, "
        f"절약 약 {total_saved // 1024} KB → {output_dir.resolve()}",
        file=sys.stderr,
    )
    return 0 if results or not skipped else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="PNG 를 SRT_XXX.jpg 로 변환 (유튜브·4_1_video 파이프라인 최적화).",
    )
    parser.add_argument(
        "input",
        nargs="?",
        type=Path,
        default=None,
        help=f"입력 폴더 (기본: {default_input_dir()})",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help=f"출력 폴더 (기본: {PROJECT_DIRNAME}/output)",
    )
    parser.add_argument("-r", "--recursive", action="store_true", help="하위 폴더 PNG 포함")
    parser.add_argument(
        "--include-jpg",
        action="store_true",
        help="JPG 도 SRT_XXX.jpg 로 재인코딩·이름 정리",
    )
    parser.add_argument("-q", "--quality", type=int, default=88, help="JPEG 품질 60–95 (기본 88)")
    parser.add_argument("-g", "--gui", action="store_true", help="GUI 실행")
    args = parser.parse_args()

    if args.gui or args.input is None:
        from png2jpg.gui_app import main as gui_main

        gui_main()
        return 0

    inp = args.input.resolve()
    out = (args.output or default_output_dir()).resolve()
    q = max(60, min(95, args.quality))
    return run_cli(
        inp,
        out,
        recursive=args.recursive,
        include_jpg=args.include_jpg,
        quality=q,
    )


if __name__ == "__main__":
    raise SystemExit(main())
