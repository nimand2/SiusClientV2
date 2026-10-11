@echo off
cd /d "%~dp0"
if exist "dist\SiusClientV2.exe" (
    start "" "dist\SiusClientV2.exe"
    exit /b
)
if exist ".venv\Scripts\pythonw.exe" (
    start "" ".venv\Scripts\pythonw.exe" "main.py"
    exit /b
)
echo Bitte zuerst die Python-Umgebung gemaess README.md einrichten.
pause
