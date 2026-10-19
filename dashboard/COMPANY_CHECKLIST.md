# 公司数字版检查清单

逐步命令和分支恢复方法以 [COMPANY_SETUP.md](COMPANY_SETUP.md) 为准。

- 确认仓库根目录、当前分支 `codex/company-apps`、工作区无待处理修改；数据和配置未被跟踪。
- 快进拉取统一分支，保留既有 Wind 数据、环境和根 localsetting。
- 检查桌面 Microsoft Excel；复用 Python 或另建被忽略的数字专用环境，避免升级 Wind 环境。
- 执行 `python -B -X utf8 -m dashboard.numeric_config`，确认标准化历史与合约参考存在；数字配置只在独立副本中调整。
- 先 `dashboard/start_numeric_excel.cmd -ReadOnlyCache` 检查四张表的合约、时间、指标及缺失说明。
- 盘中登录公司实时 VPN 后正常启动；盘前09:29前/盘后15:01起/休市只看历史或有效保存观测。最终关闭该 Excel 后停止本次服务。
- 原始 Wind 库不能直接当看板标准化历史；缺少兼容数据时按 COMPANY_SETUP.md 显式处理，不能覆盖旧库。
- 日常只 pull；有代码修改才按明确文件名暂存、审查和提交。实际 Excel/数据/凭据不上传。
