다운로드 받은 폰트는 wisdom\fonts\ 위치하며, 폴더에 있는 폰트만 selectbox로 선택할수 있도록 한다.

## 글자 지우기 (EasyOCR + inpaint)

- **지우기 영역 지정** 모드에서 미리보기 위를 드래그해 사각형을 그린다.
- 지정 영역 안에서 EasyOCR이 글자를 찾고, `cv2.inpaint()` 로 배경을 복원한다.
- OCR이 글자를 못 찾으면 해당 사각형 전체를 지운다.
- **미리보기**·**저장** 시 지우기가 적용된 뒤 텍스트 레이어가 그려진다.
- 지우기 영역은 설정 JSON 프리셋에 함께 저장된다.

의존성: `opencv-python`, `easyocr`, `numpy` (`6_thumbnail/requirements.txt`)
