@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
cd /d "%~dp0"

echo [2_4_srtEdit] PyInstaller 빌드 시작...
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

"!PYEXE!" -m pip install -q -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1

set "DISTEXE=!PROOT!\dist\2_4_srtEdit_gui.exe"
taskkill /F /IM 2_4_srtEdit_gui.exe >nul 2>&1
ping -n 2 127.0.0.1 >nul
if exist "!DISTEXE!" del /F /Q "!DISTEXE!" >nul 2>&1
if exist "%~dp0work" rmdir /s /q "%~dp0work"

"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0srt_edit_gui.spec"
if errorlevel 1 exit /b 1

if not exist "!DISTEXE!" (
  echo dist\2_4_srtEdit_gui.exe 를 찾을 수 없습니다.
  exit /b 1
)
powershell -NoProfile -Command "Unblock-File -LiteralPath '%DISTEXE%' -ErrorAction SilentlyContinue" >nul 2>&1
echo 완료: "!DISTEXE!"
exit /b 0
