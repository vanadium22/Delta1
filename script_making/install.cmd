@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 goto failed
"%REPORT_PYTHON%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
echo Desktop App dependencies are ready. Run start.cmd.
exit /b 0
:failed
pause
exit /b 1
