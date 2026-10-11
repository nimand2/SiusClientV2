@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\pythonw.exe" (
    echo Die Python-Umgebung fehlt. Einrichtung siehe README.md.
    pause
    exit /b 1
)
start "" ".venv\Scripts\pythonw.exe" "main.py"
