@echo off
chcp 65001 >nul
cd /d "%~dp0"
set "PYTHONUTF8=1"
if exist "..\.build_env\Scripts\python.exe" (
  "..\.build_env\Scripts\python.exe" web_app.py
) else (
  py -3 web_app.py
)
if errorlevel 1 pause
