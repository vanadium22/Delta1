@echo off
setlocal DisableDelayedExpansion
chcp 65001 >nul
title 三账户场内持仓与盈亏
set "account_pnl_pause=1"
if /i "%~1"=="--no-pause" set "account_pnl_pause=0"
pushd "%~dp0.." || exit /b 1
call "%~dp0..\index_futures_basis\resolve_python.cmd" >nul
if not errorlevel 1 goto company_python
if exist "P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe" (
    set "BASIS_PYTHON=P:\code_content\python_work_env\conda_env\swhy_delta1\python.exe"
    goto company_python
)
python -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto try_py
python -u -X utf8 -m account_daily_pnl %*
set "account_pnl_result=%errorlevel%"
goto finish

:company_python
"%BASIS_PYTHON%" -u -X utf8 -m account_daily_pnl %*
set "account_pnl_result=%errorlevel%"
goto finish

:try_py
py -3 -c "import sys; sys.exit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto no_python
py -3 -u -X utf8 -m account_daily_pnl %*
set "account_pnl_result=%errorlevel%"
goto finish

:no_python
echo 运行失败：请使用 Python 3.10 或更新版本。
set "account_pnl_result=1"

:finish
popd
if "%account_pnl_result%"=="2" (
    echo 部分数据待补。请查看上方说明和已生成的报表位置。
) else if not "%account_pnl_result%"=="0" echo 运行失败，退出码 %account_pnl_result%。请查看上方说明。
if "%account_pnl_pause%"=="1" (
    echo 按任意键关闭窗口。
    pause >nul
)
exit /b %account_pnl_result%
