# -*- coding: utf-8 -*-
"""``python -m png_rename`` CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from png_rename.paths import default_png_dir, default_srt_file
from png_rename.rename import apply_match_renames, rename_pngs_by_srt, scan_png_matches


def main() -> int:
    p = argparse.ArgumentParser(description="SRT 대본·PNG OCR 매칭 → SRT_XXX.png")
    p.add_argument("--srt", type=Path, default=default_srt_file(), help="대본 SRT")
    p.add_argument("--png-dir", type=Path, default=default_png_dir(), help="PNG 폴더")
    p.add_argument("-r", "--recursive", action="store_true", help="하위 폴더 포함")
    p.add_argument("-n", "--dry-run", action="store_true", help="이름 변경 없이 미리보기")
    p.add_argument("--list-only", action="store_true", help="목록만 출력(변경 안 함)")
    p.add_argument(
        "--no-skip-named",
        action="store_true",
        help="이미 SRT_XXX.png 인 파일도 이름 변경 대상에 포함",
    )
    args = p.parse_args()

    if args.list_only:
        rows = scan_png_matches(
            args.srt,
            args.png_dir,
            recursive=args.recursive,
            skip_already_named=not args.no_skip_named,
        )
        print(
            f"{'파일명':<18} {'OCR 식별 단어':<40} {'단어번호':>6} {'단어대본':<22} {'매칭':^4}"
        )
        print("-" * 110)
        for row in rows:
            ocr = (row.ocr_preview or "—")[:40]
            wno = row.word_srt_number if row.word_srt_number >= 0 else "—"
            wcue = (row.word_cue_text or "—")[:22]
            print(
                f"{row.source.name:<18} {ocr:<40} {wno!s:>6} {wcue:<22} "
                f"{row.match_label:^4}  [{row.status}]"
            )
        n_ok = sum(1 for r in rows if r.matched)
        print(f"\n전체 {len(rows)}개 · 일치 {n_ok} · 불일치 {len(rows) - n_ok}")
        return 0

    if args.dry_run:
        rows = scan_png_matches(
            args.srt,
            args.png_dir,
            recursive=args.recursive,
            skip_already_named=not args.no_skip_named,
        )
        results, skipped = apply_match_renames(
            [r for r in rows if r.can_rename], dry_run=True
        )
    else:
        results, skipped = rename_pngs_by_srt(
            args.srt,
            args.png_dir,
            recursive=args.recursive,
            dry_run=False,
            skip_already_named=not args.no_skip_named,
        )
    for r in results:
        print(f"OK  {r.source.name} -> {r.target.name}  (점수 {r.score})")
    for s in skipped:
        print(f"SKIP {s.source.name}: {s.reason}")
    print(f"\n변경 {len(results)}개, 건너뜀 {len(skipped)}개")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
