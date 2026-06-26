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
  echo Python을 찾을 수 없습니다.
  exit /b 1
)

echo [7_utube] PyInstaller 빌드 — 사용 Python: "!PYEXE!"
"!PYEXE!" -c "import sys; assert sys.version_info>=(3,10)" 2>nul
if errorlevel 1 (
  echo Python 3.10 이상이 필요합니다.
  exit /b 1
)

"!PYEXE!" -m pip install -q -r "!PROOT!\requirements.txt" -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행...
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0utube_gui.spec"
if errorlevel 1 exit /b 1

echo.
echo 완료: "!PROOT!\dist\7_utube_gui.exe"
exit /b 0
