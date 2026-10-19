# 原生界面维护入口

当前入口为项目根 `python -m dashboard.current` 或 `dashboard/start.cmd`，使用 ResearchWindow。

现行说明集中在 [项目交接](../PROJECT_HANDOFF.md)、[公司操作清单](../COMPANY_CHECKLIST.md) 和 [后续任务 Prompt](../NEXT_CHAT_PROMPT.md)。四页为行情总览、指标研究、数据管理 / 设置、数据维护。

主要代码：`app.py`（窗口）、`nonregression.py`（快照和固定合约研究）、`card_data.py`（概览与分位）、`continuous.py`（每日连续映射）、`collection.py`（实时）、`history_maintenance.py`（维护控制和页面）。

EDITIONS / STAGED_RELEASES / PUBLIC_RELEASE / BASIS_RESEARCH / MARKET_INDICATORS 保留为旧版构建器或计算研究参考；其历史命令、数据范围与界面不代表当前默认版本。新展示版、开发版及无图 Excel 尚待实现，暂不发布它们的前端改动。
