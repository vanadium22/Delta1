@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
cd /d "%~dp0.."
"%D1_PYTHON%" -s -X utf8 -m securities_lending.diagnose %*
pause
