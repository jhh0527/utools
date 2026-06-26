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

set "PYTHONPATH=!PROOT!"

taskkill /IM 8_fileExplorer_gui.exe /F 2>nul

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo PyInstaller 실행 ^(GUI: "!PROOT!\dist\8_fileExplorer_gui.exe"^)...
if exist "!PROOT!\dist\8_fileExplorer_gui.exe" (
  del /f /q "!PROOT!\dist\8_fileExplorer_gui.exe" 2>nul
  if exist "!PROOT!\dist\8_fileExplorer_gui.exe" (
    echo [경고] 기존 8_fileExplorer_gui.exe 를 지울 수 없습니다. 프로세스를 종료한 뒤 build.bat 을 다시 실행하세요.
    exit /b 1
  )
)
"!PYEXE!" -m PyInstaller --clean --noconfirm --distpath "!PROOT!\dist" --workpath "%~dp0work" "%~dp0file_explorer_gui.spec"
if errorlevel 1 exit /b 1

if exist "%~dp0work" rmdir /s /q "%~dp0work"
echo.
echo 완료:
echo   GUI  "!PROOT!\dist\8_fileExplorer_gui.exe"
echo   실행 "!PROOT!\run_file_explorer_gui.py"  또는 dist exe 더블클릭
exit /b 0
