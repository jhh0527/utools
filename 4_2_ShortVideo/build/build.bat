@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo [4_2_ShortVideo] PyInstaller 빌드 시작...

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
  echo Python을 찾을 수 없습니다.
  exit /b 1
)

echo 사용 중인 Python: "!PYEXE!"
"!PYEXE!" -m pip install -q -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1

taskkill /IM 4_2_shortvideo_gui.exe /F 2>nul
if exist "!PROOT!\dist\4_2_shortvideo_gui.exe" del /f /q "!PROOT!\dist\4_2_shortvideo_gui.exe" 2>nul

set "PYTHONPATH=!PROOT!;!PROOT!\.."
if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행 ^(GUI: "!PROOT!\dist\4_2_shortvideo_gui.exe"^)...
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0shortvid_gui.spec"
if errorlevel 1 exit /b 1

echo.
echo 완료: "!PROOT!\dist\4_2_shortvideo_gui.exe"
exit /b 0
