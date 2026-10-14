@echo off
set "D1_PYTHON="
if defined D1_LENDING_PYTHON (
  set "D1_PYTHON=%D1_LENDING_PYTHON%"
  goto validate
)
if defined SWHY_DELTA1_PYTHON (
  set "D1_PYTHON=%SWHY_DELTA1_PYTHON%"
  goto validate
)
if exist "%~dp0python.local.txt" (
  set /p D1_PYTHON=<"%~dp0python.local.txt"
  goto validate
)
if exist "D:\conda\envs\swhy_delta1\python.exe" (
  set "D1_PYTHON=D:\conda\envs\swhy_delta1\python.exe"
  goto validate
)
if defined CONDA_PREFIX (
  for %%E in ("%CONDA_PREFIX%") do if /i "%%~nxE"=="swhy_delta1" set "D1_PYTHON=%%~fE\python.exe"
)
if defined D1_PYTHON goto validate
if exist "%USERPROFILE%\.conda\environments.txt" (
  for /f "usebackq delims=" %%E in ("%USERPROFILE%\.conda\environments.txt") do (
    for %%N in ("%%E") do if /i "%%~nxN"=="swhy_delta1" if exist "%%E\python.exe" set "D1_PYTHON=%%E\python.exe"
  )
)
:validate
if not defined D1_PYTHON (
  echo swhy_delta1 was not found. Create it using environment.yml first.
  echo Company default: D:\conda\envs\swhy_delta1
  echo Or set SWHY_DELTA1_PYTHON to its python.exe.
  exit /b 1
)
if not exist "%D1_PYTHON%" (
  echo Python does not exist: "%D1_PYTHON%"
  exit /b 1
)
exit /b 0
