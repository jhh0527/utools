@echo off
setlocal
cd /d "%~dp0.."
echo [wisdom 허브] PyInstaller 빌드 시작...
taskkill /IM wisdom_hub_gui.exe /F 2>nul
python -m pip install -q pyinstaller 2>nul
python -m pip install -q -r "%~dp0..\1_1_textTo700Text\requirements-automation.txt" 2>nul
python -m pip install -q -r "%~dp0..\2_3_stt\requirements.txt" 2>nul
python -m playwright install chrome 2>nul
python -m PyInstaller --noconfirm --clean "%~dp0wisdom_hub_gui.spec"
if errorlevel 1 exit /b 1
echo.
echo 완료: "%cd%\dist\wisdom_hub_gui.exe"
endlocal
