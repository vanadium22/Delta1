@echo off
set "REPORT_PYTHON="
if defined REPORT_APP_PYTHON (
  set "REPORT_PYTHON=%REPORT_APP_PYTHON%"
  goto validate
)
if defined SWHY_DELTA1_PYTHON (
  set "REPORT_PYTHON=%SWHY_DELTA1_PYTHON%"
  goto validate
)
if exist "%~dp0python.local.txt" (
  set /p REPORT_PYTHON=<"%~dp0python.local.txt"
  goto validate
)
if exist "D:\conda\envs\swhy_delta1\python.exe" (
  set "REPORT_PYTHON=D:\conda\envs\swhy_delta1\python.exe"
  goto validate
)
if defined CONDA_PREFIX (
  for %%E in ("%CONDA_PREFIX%") do if /i "%%~nxE"=="swhy_delta1" set "REPORT_PYTHON=%%~fE\python.exe"
)
if defined REPORT_PYTHON goto validate
if exist "%USERPROFILE%\.conda\environments.txt" (
  for /f "usebackq delims=" %%E in ("%USERPROFILE%\.conda\environments.txt") do (
    for %%N in ("%%E") do if /i "%%~nxN"=="swhy_delta1" if exist "%%E\python.exe" set "REPORT_PYTHON=%%E\python.exe"
  )
)
if defined REPORT_PYTHON goto validate
for /f "delims=" %%P in ('where python 2^>nul') do if not defined REPORT_PYTHON set "REPORT_PYTHON=%%P"
:validate
if not defined REPORT_PYTHON (
  echo Please set python.local.txt to the full path of your python.exe.
  exit /b 1
)
if not exist "%REPORT_PYTHON%" (
  echo Python does not exist: "%REPORT_PYTHON%"
  exit /b 1
)
exit /b 0
