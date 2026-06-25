@echo off
chcp 65001 >nul
cd /d "%~dp0"
REM 변환 대상 폴더를 인자로 넘길 수 있습니다. 예: run_gui.bat "D:\png_folder"
if "%~1"=="" (
  python "%~dp0run_png2jpg_gui.py"
) else (
  python "%~dp0run_png2jpg_gui.py" -i "%~1"
)
exit /b %ERRORLEVEL%
