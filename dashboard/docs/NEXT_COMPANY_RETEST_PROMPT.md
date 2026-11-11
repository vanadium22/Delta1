# 下一对话：新DDB端点、更新页与盘前日期

2026-11-11。先完整读本页，再核验根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC与Git/远端/worktree/diff。当前基线d4c2b9b，最终发布号看Git。

## 可复制接续提示词

```text
请继续Delta1公司看板，工作区P:/project/swhy/Delta1/company-apps-worktree，统一codex/company-apps。本轮用户确认DDB新地址192.168.198.77:8904、账号密码不变，并要求修复更新页填写框挤压及盘前11-06日期疑问。

本机原DDB配置已经是新地址，但忽略配置不随git pull传播。新版App把非秘密端点和原凭据引用分离，默认使用发布的新地址，显式history_ddb_host/history_ddb_port优先；VPN路由验证和数据库会话使用同端点，原账号/密码/TLS文件不重写。更新页可只保存地址，表单分组滚动/输入框40像素，原账号编辑保留。

11月11日盘前最近完成交易日是11-10。价格日取卡片实际源时，DDB目标取交易日历，最新分红表取Y盘B1；分红11-06不能用来判断价格或DDB断开。新版两个页面和Overview报告区分三日期及维护阶段。若实际价格仍11-06，按同次目标/生效地址/tcp或session或认证/SDK/查询阶段和源时核验，不用旧成功状态推断本次。

本机09:36有界只读检查：新地址3秒TCP超时，未登录/未查询11-10，未操作VPN。不能把本机超时当公司失败或源端无11-10。388项本地回归通过，12项新增含端点/凭据/盘前目标/布局/日期；公司新端点和布局验收仍等现场。最近公司ZIP仍为b5746c7的9JSON包，同次6.153秒安全关闭，16档OI金额用11-09日线复算通过。

收到新反馈先核验HEAD/完整性/同次运行；看data_gaps.ddb.connection与maintenance（区分matches_current_target）、app_reports.history_update和实际价格源时。默认Overview离线；公司命令只维护APP_COMPANY_TEST。实施、必要测试和精确提交推送授权继续有效。

保留原数据/配置/凭据/Excel、四受保护旧提示词、七份唯一SHA归档/MANIFEST、APP_RELEASE.backtest原对象/序列化、其他模块/worktree。逐日D/连续20与60/简单年化、T<5、排当前日、等值半权、历史缺D暂0仅派生/当前D不补0、数字不加“估”及32/A02暂停保持。实时VPN手动，不强杀/删锁、不重映射Y，不reset/clean/全量stage/强推。
```

本轮证据仅local_artifacts/validation/company_20261111_ddb_layout；原DDB凭据文件及8454个原件的大小/SHA保留。Y源仍Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026、业务日B1。当前D11-06、428历史D零占位、2只股票/214分类缺失继续如实列明，不冒称新源已补齐。
