"""SRT 대본·이미지 글자 매칭 → ``SRT_XXX.png`` 파일명 변환."""

from png_rename.rename import (
    MatchPreview,
    apply_match_renames,
    apply_ocr_to_row,
    build_srt_centric_skeleton,
    remap_all_rows_from_filenames,
    rename_pngs_by_srt,
    scan_png_matches,
    scan_srt_centric_matches,
)

__version__ = "0.3.38"
__all__ = [
    "MatchPreview",
    "apply_ocr_to_row",
    "build_srt_centric_skeleton",
    "remap_all_rows_from_filenames",
    "scan_png_matches",
    "scan_srt_centric_matches",
    "apply_match_renames",
    "rename_pngs_by_srt",
]
