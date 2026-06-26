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

echo [9_mdFile] PyInstaller 빌드 — 사용 Python: "!PYEXE!"

"!PYEXE!" -m pip install -q -r "%~dp0requirements-build.txt"
if errorlevel 1 exit /b 1

set "PYTHONPATH=!PROOT!"

taskkill /IM 9_mdFile_gui.exe /F 2>nul

if exist "%~dp0work" rmdir /s /q "%~dp0work"
if exist "!PROOT!\dist\9_mdFile_gui.exe" (
  del /f /q "!PROOT!\dist\9_mdFile_gui.exe" 2>nul
)
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0md_file_gui.spec"
if errorlevel 1 exit /b 1

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo.
echo 완료: "!PROOT!\dist\9_mdFile_gui.exe"
exit /b 0
