@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo [2_3_stt] PyInstaller 빌드 시작...

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
  echo Python을 찾을 수 없습니다.
  exit /b 1
)

echo 사용 중인 Python: "!PYEXE!"
"!PYEXE!" --version
if errorlevel 1 exit /b 1

echo 빌드 도구·의존성 설치...
"!PYEXE!" -m pip install -q -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1
"!PYEXE!" -m pip install -q -r "!PROOT!\requirements.txt"
if errorlevel 1 exit /b 1

set "PYTHONPATH=!PROOT!"

taskkill /IM 2_3_stt_gui.exe /F 2>nul

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행 ^(GUI: "!PROOT!\dist\2_3_stt_gui.exe"^)...
if exist "!PROOT!\dist\2_3_stt_gui.exe" (
  del /f /q "!PROOT!\dist\2_3_stt_gui.exe" 2>nul
)
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0stt_gui.spec"
if errorlevel 1 exit /b 1

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo.
echo 완료:
echo   GUI  "!PROOT!\dist\2_3_stt_gui.exe"
echo   Whisper STT 사용 시 faster-whisper 모델이 필요합니다 ^(처음 실행 시 자동 다운로드^).
exit /b 0
