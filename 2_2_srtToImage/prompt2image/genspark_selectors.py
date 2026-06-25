# -*- coding: utf-8 -*-
"""Genspark ai_image 페이지 UI 셀렉터 (사이트 변경 시 여기만 수정)."""

from __future__ import annotations

# 프롬프트·지침 입력 (contenteditable / textarea) — 사이트 변경 시 추가
PROMPT_INPUTS = [
    "textarea[placeholder*='image' i]",
    "textarea[placeholder*='이미지' i]",
    "textarea[placeholder*='Describe' i]",
    "textarea[placeholder*='prompt' i]",
    "textarea[placeholder*='프롬프트' i]",
    "textarea[placeholder*='무엇' i]",
    "[contenteditable='true'][role='textbox']",
    "[contenteditable='true']:not([aria-hidden='true'])",
    "div.ProseMirror[contenteditable='true']",
    "textarea:visible",
    "[role='textbox']:visible",
    ".chat-input textarea",
    ".input-area textarea",
    "[class*='prompt'] textarea",
    "[class*='chat-input'] textarea",
    "[class*='composer'] textarea",
    "[data-testid*='prompt']",
]

# 로그인·가입 페이지 URL 패턴 (입력란 없음)
LOGIN_URL_HINTS = ("login", "signin", "sign-in", "signup", "sign-up", "auth")

# 생성·전송 버튼
GENERATE_BUTTONS = [
    "button:has-text('Generate')",
    "button:has-text('생성')",
    "button:has-text('Send')",
    "button:has-text('전송')",
    "button[type='submit']",
    "[aria-label*='Send' i]",
    "[aria-label*='생성' i]",
]

# 결과 이미지 (아이콘·로고 제외용 — 큰 이미지 우선)
RESULT_IMAGES = [
    "main img",
    "[class*='result'] img",
    "[class*='image'] img",
    "[class*='gallery'] img",
    "img[src*='http']",
]

# 확대(라이트박스) 뷰
LIGHTBOX = [
    "[class*='lightbox']",
    "[class*='modal']",
    "[class*='preview']",
    "[role='dialog']",
]

# 이미지 생성 모델 선택 (GPT Image 2)
IMAGE_MODEL = "GPT Image 2"

MODEL_PICKER_TRIGGERS = [
    "button:has-text('Nano Banana')",
    "button:has-text('Flux')",
    "button:has-text('Imagen')",
    "button:has-text('Seedream')",
    "button:has-text('GPT Image')",
    "[class*='model'] button:visible",
    "[class*='model-select']",
    "[data-testid*='model']",
    "button[aria-haspopup='listbox']:visible",
    "button[aria-haspopup='menu']:visible",
]

GPT_IMAGE_2_OPTIONS = [
    "GPT Image 2",
    "GPT Image 2.0",
    "GPT Image",
    "gpt-image-2",
]

GPT_IMAGE_2_SELECTED_HINTS = [
    "GPT Image 2",
    "GPT Image 2.0",
]

# 다운로드 버튼·링크
DOWNLOAD_BUTTONS = [
    "button:has-text('Download')",
    "button:has-text('다운로드')",
    "a:has-text('Download')",
    "a:has-text('다운로드')",
    "[aria-label*='Download' i]",
    "[aria-label*='다운로드' i]",
    "a[download]",
]
