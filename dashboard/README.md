# 数字 Excel 看板

公司按 [首次检查及更新步骤](COMPANY_SETUP.md) 操作，统一分支 `codex/company-apps`。已有公司项目无需重新 clone、覆盖 data 或重装 Wind。

入口：`dashboard/start_numeric_excel.cmd`。自动更新同一个已打开的 Excel 工作簿；概览四卡、25项指标矩阵、原生分位图及来源与状态供日常阅读，原完整指标表隐藏保留。运行要求为 Windows 桌面 Microsoft Excel 和 Python 数字计算依赖，无需 VBA 或看板前端。

默认使用独立数字配置副本，先执行 `python -B -X utf8 -m dashboard.numeric_config` 离线检查，再使用 `-ReadOnlyCache` 验证已有数据。只存有原始 Wind 数据时，尚需标准化历史、合约参考表和分红输入；Git 不携带公司数据，也不会自动替换 Wind 库。

[刷新和指标规则](NUMERIC_EXCEL.md) · [Git 交付边界](GIT_WORKFLOW.md) · [交接](PROJECT_HANDOFF.md) · [数据格式](data_contract/README.md)

本分支暂不提供看板展示版/开发版前端。数字版已有历史选择/网络向导：DDB及其VPN分别用 `configure_numeric_history.cmd`、`configure_numeric_vpn.cmd` 在本机配置，补齐可复用现有连接或自动登录DDB VPN。历史进程退出后提示用户手动切回实时行情VPN，再验证打开；不自动登出或切回。前端App仍在旧工作目录保留。
