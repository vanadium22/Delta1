@echo off
if "%~1"=="" (
  call "%~dp0start_numeric_excel.cmd" -Once -ReadOnlyCache
) else (
  if "%~2"=="" (call "%~dp0start_numeric_excel.cmd" -Once -Snapshot "%~1") else (call "%~dp0start_numeric_excel.cmd" -Once -Snapshot "%~1" -Output "%~2")
)
