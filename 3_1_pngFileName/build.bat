@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo [3_1_pngFileName] PyInstaller 빌드 시작...
call "%~dp0build\build_exe.bat"
exit /b %ERRORLEVEL%
