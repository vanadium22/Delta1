@echo off
setlocal
cd /d "%~dp0"
call "%~dp0resolve_python.cmd"
if errorlevel 1 goto failed
echo Installing App dependencies into "%D1_PYTHON%"
"%D1_PYTHON%" -s -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation complete. WindPy is optional and must be installed at the office.
echo Run start.cmd or start_demo.cmd to open the native App.
pause
exit /b 0
:failed
echo Installation failed. Check your swhy_delta1 environment and package index connection.
pause
exit /b 1
