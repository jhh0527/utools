@echo off
chcp 65001 >nul
echo [3_1_pngFileName] Tesseract OCR + 한국어(kor) 설치
echo.

where winget >nul 2>&1
if errorlevel 1 (
  echo winget 이 없습니다. 아래에서 수동 설치하세요.
  echo https://github.com/UB-Mannheim/tesseract/wiki
  pause
  exit /b 1
)

winget install --id UB-Mannheim.TesseractOCR -e --accept-package-agreements --accept-source-agreements
if errorlevel 1 exit /b 1

set "TESS=C:\Program Files\Tesseract-OCR\tessdata\kor.traineddata"
if exist "%TESS%" (
  echo 한국어 kor 데이터가 이미 있습니다.
  goto :done
)

echo 한국어 kor.traineddata 다운로드...
powershell -NoProfile -Command ^
  "Invoke-WebRequest -Uri 'https://github.com/tesseract-ocr/tessdata/raw/main/kor.traineddata' -OutFile '%TESS%' -UseBasicParsing"
if errorlevel 1 (
  echo kor 다운로드 실패. 관리자 권한으로 다시 실행하세요.
  exit /b 1
)

:done
"C:\Program Files\Tesseract-OCR\tesseract.exe" --list-langs
echo.
echo 설치 완료. 3_1_pngFileName 을 다시 실행하세요.
pause
