@echo off
setlocal
pushd "%~dp0"
if errorlevel 1 exit /b 1

rem Company Python verified on 2026-10-22. No activation or PATH lookup.
set "NUMERIC_PYTHON=D:\conda\envs\swhy_delta1\python.exe"
if not exist "%NUMERIC_PYTHON%" goto python_missing

powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0dashboard\excel_numeric\live.ps1" -Python "%NUMERIC_PYTHON%" %*
set "NUMERIC_EXIT_CODE=%ERRORLEVEL%"
if not "%NUMERIC_EXIT_CODE%"=="0" pause
popd
exit /b %NUMERIC_EXIT_CODE%

:python_missing
echo Delta1: company Python was not found:
echo "%NUMERIC_PYTHON%"
echo Check the existing environment path before starting again.
popd
pause
exit /b 1
