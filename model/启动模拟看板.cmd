@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0paper-dashboard.ps1" start
if errorlevel 1 (pause & exit /b 1)
timeout /t 3 /nobreak >nul
start "" "http://127.0.0.1:8765"
