@echo off
setlocal
cd /d "%~dp0.."
set "DELTA1_RELEASE_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe"
if defined SWHY_DELTA1_PYTHON set "DELTA1_RELEASE_PYTHON=%SWHY_DELTA1_PYTHON%"
if not exist "%DELTA1_RELEASE_PYTHON%" (
  echo Python not found: "%DELTA1_RELEASE_PYTHON%"
  pause
  exit /b 1
)
"%DELTA1_RELEASE_PYTHON%" -B -s -X utf8 dashboard/build_stage_releases.py %*
if errorlevel 1 (
  echo Release generation failed. See the error above.
  pause
  exit /b 1
)
echo Release generation completed. The output path is shown above.
pause
