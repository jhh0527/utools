# -*- coding: utf-8 -*-
"""wisdom 허브 탭 순서 (번호 체계)."""

from __future__ import annotations

# (탭 제목, 모듈 폴더명)
HUB_TABS: tuple[tuple[str, str], ...] = (
    ("1_1 대본700", "1_1_textTo700Text"),
    ("2_1 TTS", "2_1_ttsToVoice"),
    ("2_2 SRT이미지", "2_2_srtToImage"),
    ("2_3 STT", "2_3_stt"),
    ("2_4 이미지MP4", "2_4_imageToMp4"),
    ("3_1 PNG이름", "3_1_pngFileName"),
    ("3_2 PNG→JPG", "3_2_pngToJpg"),
    ("4_1 동영상", "4_1_video"),
    ("4_2 쇼츠", "4_2_ShortVideo"),
    ("6 썸네일", "6_thumbnail"),
    ("7_Utube", "7_utube"),
    ("7_2 mp4Edit", "7_2_mp4Edit"),
    ("7_3 mp4Search", "7_3_mp4Search"),
    ("9 MD파일", "9_mdFile"),
)
