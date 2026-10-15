@echo off
set "BASIS_PYTHON="
if defined BASIS_APP_PYTHON (
  set "BASIS_PYTHON=%BASIS_APP_PYTHON%"
  goto validate
)
if defined SWHY_DELTA1_PYTHON (
  set "BASIS_PYTHON=%SWHY_DELTA1_PYTHON%"
  goto validate
)
if exist "%~dp0python.local.txt" (
  set /p BASIS_PYTHON=<"%~dp0python.local.txt"
  goto validate
)
if exist "D:\conda\envs\swhy_delta1\python.exe" (
  set "BASIS_PYTHON=D:\conda\envs\swhy_delta1\python.exe"
  goto validate
)
if defined CONDA_PREFIX (
  for %%E in ("%CONDA_PREFIX%") do if /i "%%~nxE"=="swhy_delta1" set "BASIS_PYTHON=%%~fE\python.exe"
)
:validate
if not defined BASIS_PYTHON (
  echo Please set python.local.txt to your swhy_delta1 python.exe path.
  exit /b 1
)
if not exist "%BASIS_PYTHON%" (
  echo Python does not exist: "%BASIS_PYTHON%"
  exit /b 1
)
exit /b 0
