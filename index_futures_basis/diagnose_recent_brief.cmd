@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 (
  pause
  exit /b 1
)
pushd "%~dp0.."
"%BASIS_PYTHON%" -X utf8 -m index_futures_basis.recent_brief.diagnostics %*
set "BASIS_BRIEF_EXIT=%errorlevel%"
popd
if "%~1"=="" pause
exit /b %BASIS_BRIEF_EXIT%
