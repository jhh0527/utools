@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo [2_2_scriptToVoice] PyInstaller 빌드 시작...

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

"!PYEXE!" -m pip install -q -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1

set "DISTEXE=!PROOT!\dist\2_2_scriptToVoice_gui.exe"

echo 실행 중인 2_2_scriptToVoice_gui 종료...
taskkill /F /IM 2_2_scriptToVoice_gui.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul
if exist "!DISTEXE!" del /F /Q "!DISTEXE!" >nul 2>&1

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행...
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0script_voice_gui.spec"
if errorlevel 1 exit /b 1

if not exist "!DISTEXE!" (
  echo dist\2_2_scriptToVoice_gui.exe 를 찾을 수 없습니다.
  exit /b 1
)

powershell -NoProfile -Command "Unblock-File -LiteralPath '%DISTEXE%' -ErrorAction SilentlyContinue" >nul 2>&1

echo.
echo 완료:
echo   GUI  "!DISTEXE!"
echo   ElevenLabs 설정은 2_1_ttsToVoice\dist\elsub_config*.json 을 사용합니다.
echo   MP3 병합 시 PATH에 ffmpeg 가 필요합니다.
exit /b 0
