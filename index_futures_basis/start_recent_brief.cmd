@echo off
setlocal
call "%~dp0resolve_python.cmd"
if errorlevel 1 exit /b 1
pushd "%~dp0.."
"%BASIS_PYTHON%" -X utf8 -m index_futures_basis.recent_brief %*
set "BASIS_BRIEF_EXIT=%errorlevel%"
popd
exit /b %BASIS_BRIEF_EXIT%
