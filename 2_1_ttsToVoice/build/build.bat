@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo [2_1_ttsToVoice] PyInstaller 빌드 시작...

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

set "DISTEXE=!PROOT!\dist\2_1_ttsToVoice_gui.exe"

echo 실행 중인 2_1_ttsToVoice_gui 종료 및 기존 exe 잠금 해제...
taskkill /F /IM 2_1_ttsToVoice_gui.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul
if exist "!DISTEXE!" (
  del /F /Q "!DISTEXE!" >nul 2>&1
)
if exist "!DISTEXE!" (
  move /Y "!DISTEXE!" "!DISTEXE!.old" >nul 2>&1
  del /F /Q "!DISTEXE!.old" >nul 2>&1
)
if exist "!DISTEXE!" (
  echo.
  echo dist\2_1_ttsToVoice_gui.exe 를 덮어쓸 수 없습니다.
  echo   - GUI 창·작업 관리자에서 2_1_ttsToVoice_gui 를 모두 종료한 뒤 build.bat 을 다시 실행하세요.
  exit /b 1
)

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행 ^(GUI: "!DISTEXE!"^)...
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0elsub_gui.spec"
if errorlevel 1 exit /b 1

if not exist "!DISTEXE!" (
  echo dist\2_1_ttsToVoice_gui.exe 를 찾을 수 없습니다.
  exit /b 1
)

powershell -NoProfile -Command "Unblock-File -LiteralPath '%DISTEXE%' -ErrorAction SilentlyContinue" >nul 2>&1

if exist "!PROOT!\elsub_config.json" (
  copy /Y "!PROOT!\elsub_config.json" "!PROOT!\dist\elsub_config.json" >nul
  echo  - 설정 복사: elsub_config.json -^> dist\
) else if exist "!PROOT!\elsub_config.json.bk" (
  copy /Y "!PROOT!\elsub_config.json.bk" "!PROOT!\dist\elsub_config.json" >nul
  echo  - 설정 복사: elsub_config.json.bk -^> dist\elsub_config.json
) else (
  echo  - 참고: dist\elsub_config.json 이 없으면 API 키 등을 dist 에 두세요.
)

echo.
echo 완료:
echo   GUI  "!DISTEXE!"
echo   MP3 병합(ffmpeg 재인코딩) 사용 시 PATH에 ffmpeg 가 있어야 합니다.
exit /b 0
