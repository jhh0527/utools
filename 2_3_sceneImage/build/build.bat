@echo off
setlocal
cd /d "%~dp0.."
set "ROOT=%CD%"
set "WISDOM=%ROOT%\.."
set "DIST=%ROOT%\dist"
set "WORK=%ROOT%\build\work"

for /f "delims=" %%P in ('where py 2^>nul') do set "PY=%%P" & goto :found
for /f "delims=" %%P in ('where python 2^>nul') do set "PY=%%P" & goto :found
echo Python not found
exit /b 1
:found
echo [2_3_sceneImage] PyInstaller build...
"%PY%" -m pip install -q pyinstaller playwright
if exist "%DIST%\2_3_sceneImage_gui.exe" del /f /q "%DIST%\2_3_sceneImage_gui.exe"
"%PY%" -m PyInstaller --noconfirm --distpath "%DIST%" --workpath "%WORK%" "%ROOT%\build\scene_image_gui.spec"
if errorlevel 1 exit /b 1
echo Done: "%DIST%\2_3_sceneImage_gui.exe"
