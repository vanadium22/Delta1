@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 goto failed
cd /d "%~dp0.."
"%BASIS_PYTHON%" -X utf8 -c "import PySide6, pandas, numpy, matplotlib, docx, openpyxl" >nul 2>&1
if errorlevel 1 (
  echo Missing App dependencies. Run index_futures_basis\install.cmd first.
  goto failed
)
set "BASIS_PYTHONW=%BASIS_PYTHON:~0,-4%w.exe"
if exist "%BASIS_PYTHONW%" (
  start "" "%BASIS_PYTHONW%" -X utf8 -m index_futures_basis %*
) else (
  "%BASIS_PYTHON%" -X utf8 -m index_futures_basis %*
)
exit /b 0
:failed
pause
exit /b 1
