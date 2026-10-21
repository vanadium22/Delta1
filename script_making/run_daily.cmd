@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 exit /b 1
cd /d "%~dp0.."
"%REPORT_PYTHON%" -X utf8 -m script_making.daily_job --root "%~dp0." %*
exit /b %errorlevel%
