@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 goto failed
"%BASIS_PYTHON%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 goto failed
echo App dependencies installed. Your existing WindPy installation is unchanged.
pause
exit /b 0
:failed
echo Installation failed. Please preserve the error output.
pause
exit /b 1
