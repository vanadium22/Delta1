# 公司部署入口

已将部署步骤合并为可逐项执行的文档，避免多份说明互相冲突。

- [公司部署与每日双 VPN 操作清单](COMPANY_CHECKLIST.md)：环境、保留 Wind 的数据包安装、DDB 账号、先补历史再实时。
- [Git 分支抓取与推送](GIT_WORKFLOW.md)：远程或离线代码包、后续更新、提交范围与发布状态。
- [当前成果和验收证据](PROJECT_HANDOFF.md)：数据范围、计算口径、最新验证及待诊断问题。
- [历史维护技术说明](HISTORY_MAINTENANCE.md)：校验、发布、重试、锁及独立任务。

当前普通入口 `start.cmd` 会启动实时；两套 VPN 互斥且需要先补历史时使用 `start.cmd --no-realtime`。启动选择向导是下一轮任务。
