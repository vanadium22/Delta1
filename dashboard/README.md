# 数字 Excel 看板

公司按 [首次检查及更新步骤](COMPANY_SETUP.md) 操作，统一分支 `codex/company-apps`。已有公司项目无需重新 clone、覆盖 data 或重装 Wind。

入口：`dashboard/start_numeric_excel.cmd`。自动更新同一个已打开的 Excel 工作簿；四张无图表工作表包含行情、分位/样本、研究指标及数据来源/时点。运行要求为 Windows 桌面 Microsoft Excel 和 Python 数字计算依赖，无需 VBA 或看板前端。

默认使用独立数字配置副本，先执行 `python -B -X utf8 -m dashboard.numeric_config` 离线检查，再使用 `-ReadOnlyCache` 验证已有数据。只存有原始 Wind 数据时，尚需标准化历史、合约参考表和分红输入；Git 不携带公司数据，也不会自动替换 Wind 库。

[刷新和指标规则](NUMERIC_EXCEL.md) · [Git 交付边界](GIT_WORKFLOW.md) · [交接](PROJECT_HANDOFF.md) · [数据格式](data_contract/README.md)

本分支暂不提供看板展示版/开发版前端。双 VPN 图形向导及前端在旧工作目录保留；数字版盘中实时使用公司 VPN，历史读取使用本地缓存，程序不自动切换 VPN。
