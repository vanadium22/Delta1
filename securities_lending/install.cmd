@echo off
setlocal
cd /d "%~dp0"
if defined D1_LENDING_PYTHON (
  set "D1_BOOTSTRAP=%D1_LENDING_PYTHON%"
) else (
  set "D1_BOOTSTRAP=python"
)
"%D1_BOOTSTRAP%" -m venv --system-site-packages .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
echo Installation complete. Run start.cmd or start_demo.cmd.
pause
exit /b 0
:failed
echo Installation failed. Check Python 3.10+ and your package index connection.
pause
exit /b 1
