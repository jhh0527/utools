"""EasyOCR + cv2.inpaint() 로 지정 영역 내 글자 제거."""

from __future__ import annotations

from typing import Sequence

import numpy as np
from PIL import Image

_OCR_READER = None
_OCR_LANGS: tuple[str, ...] = ("ko", "en")


def _normalize_region(region: dict[str, int] | tuple[int, int, int, int], w: int, h: int) -> tuple[int, int, int, int]:
    if isinstance(region, dict):
        x1 = int(region.get("x1", 0))
        y1 = int(region.get("y1", 0))
        x2 = int(region.get("x2", 0))
        y2 = int(region.get("y2", 0))
    else:
        x1, y1, x2, y2 = (int(v) for v in region)
    xa, xb = sorted((max(0, min(w, x1)), max(0, min(w, x2))))
    ya, yb = sorted((max(0, min(h, y1)), max(0, min(h, y2))))
    if xb <= xa:
        xb = min(w, xa + 1)
    if yb <= ya:
        yb = min(h, ya + 1)
    return xa, ya, xb, yb


def _get_easyocr_reader():
    global _OCR_READER
    if _OCR_READER is None:
        import easyocr

        _OCR_READER = easyocr.Reader(list(_OCR_LANGS), gpu=False, verbose=False)
    return _OCR_READER


def _pil_rgb_to_bgr(arr: np.ndarray) -> np.ndarray:
    import cv2

    return cv2.cvtColor(arr, cv2.COLOR_RGB2BGR)


def _bgr_to_pil_rgb(bgr: np.ndarray) -> Image.Image:
    import cv2

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    return Image.fromarray(rgb)


def build_text_mask_in_regions(
    bgr: np.ndarray,
    regions: Sequence[dict[str, int] | tuple[int, int, int, int]],
    *,
    min_confidence: float = 0.25,
    fallback_full_region: bool = True,
) -> np.ndarray:
    """지정 영역에서 EasyOCR로 텍스트 마스크 생성. 미검출 시 영역 전체를 마스크로."""
    import cv2

    h, w = bgr.shape[:2]
    mask = np.zeros((h, w), dtype=np.uint8)
    if not regions:
        return mask

    reader = _get_easyocr_reader()
    for region in regions:
        x1, y1, x2, y2 = _normalize_region(region, w, h)
        crop = bgr[y1:y2, x1:x2]
        found = False
        try:
            hits = reader.readtext(crop)
        except Exception:
            hits = []
        for bbox, _text, conf in hits:
            try:
                c = float(conf)
            except (TypeError, ValueError):
                c = 0.0
            if c < min_confidence:
                continue
            pts = np.array(bbox, dtype=np.int32)
            pts[:, 0] += x1
            pts[:, 1] += y1
            cv2.fillPoly(mask, [pts], 255)
            found = True
        if not found and fallback_full_region:
            cv2.rectangle(mask, (x1, y1), (x2 - 1, y2 - 1), 255, thickness=-1)

    if mask.any():
        kernel = np.ones((3, 3), np.uint8)
        mask = cv2.dilate(mask, kernel, iterations=2)
    return mask


def inpaint_text_regions(
    img: Image.Image,
    regions: Sequence[dict[str, int] | tuple[int, int, int, int]],
    *,
    inpaint_radius: int = 5,
    min_confidence: float = 0.25,
) -> Image.Image:
    """PIL RGB 이미지에서 regions 내 글자를 EasyOCR 마스크 + inpaint 로 제거."""
    if not regions:
        return img.copy()

    import cv2

    rgb = np.array(img.convert("RGB"))
    bgr = _pil_rgb_to_bgr(rgb)
    mask = build_text_mask_in_regions(
        bgr,
        regions,
        min_confidence=min_confidence,
        fallback_full_region=True,
    )
    if not mask.any():
        return img.copy()
    radius = max(1, int(inpaint_radius))
    cleaned = cv2.inpaint(bgr, mask, radius, cv2.INPAINT_TELEA)
    return _bgr_to_pil_rgb(cleaned)
