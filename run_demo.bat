@echo off
setlocal
set "DEMO_MODE=true"
set "WEB_PORT=8766"
set "DEMO_WRITE_DB=false"
call "%~dp0run_local.bat"
endlocal
