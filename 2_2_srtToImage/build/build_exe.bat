@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

set "PROOT=%~dp0.."
for %%I in ("%PROOT%") do set "PROOT=%%~fI"

set "PYEXE="

where py >nul 2>&1
if not errorlevel 1 (
  for /f "delims=" %%I in ('py -3 -c "import sys; print(sys.executable)" 2^>nul') do set "PYEXE=%%I"
)

if not defined PYEXE (
  where python >nul 2>&1
  if not errorlevel 1 (
    for /f "delims=" %%I in ('where python') do (
      set "PYEXE=%%I"
      goto :have_python
    )
  )
)

:have_python
if not defined PYEXE (
  for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
    if exist "%%D\python.exe" (
      set "PYEXE=%%D\python.exe"
      goto :done_scan
    )
  )
)
:done_scan

if not defined PYEXE (
  echo Python을 찾을 수 없습니다. python.org 3.9+ 설치 또는 PATH의 python을 확인하세요.
  exit /b 1
)

echo 사용 중인 Python: "!PYEXE!"
"!PYEXE!" --version
if errorlevel 1 exit /b 1

"!PYEXE!" -c "import sys; assert sys.version_info>=(3,9)" 2>nul
if errorlevel 1 (
  echo Python 3.9 이상이 필요합니다.
  exit /b 1
)

echo 빌드 도구 설치...
"!PYEXE!" -m pip install -q -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1
echo Playwright ^(Genspark 자동 다운로드^)...
"!PYEXE!" -m pip install -q -r "%~dp0..\requirements-automation.txt"
if errorlevel 1 exit /b 1
"!PYEXE!" -m playwright install chrome 2>nul

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행 ^(CLI: "!PROOT!\dist\2_2_srtToImage.exe"^)...
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0prompt2image.spec"
if errorlevel 1 exit /b 1

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행 ^(GUI: "!PROOT!\dist\2_2_srtToImage_gui.exe"^)...
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0prompt2image_gui.spec"
if errorlevel 1 exit /b 1

echo.
echo 완료:
echo   CLI  "!PROOT!\dist\2_2_srtToImage.exe"
echo   GUI  "!PROOT!\dist\2_2_srtToImage_gui.exe"  ^(Genspark 브라우저·SRT_XXX.png·OCR 미리보기^)
exit /b 0
