# Delta1 公司蓝白展示版

日常建议打开[常用入口文件夹](常用入口/README.md)，只放“打开看板”和“公司复测”。原入口为 [start_presentation.vbs](start_presentation.vbs)，命令行兼容入口为 [start_presentation.cmd](start_presentation.cmd)，使用 `public` 主题。统一分支 `codex/company-apps`，公司原 Git 根目录执行一次 `git pull --ff-only`，再通过原入口重开。

2026-11-11追加：已按用户澄清修复期货分位“缺收盘”路径：收盘不再因缺OI丢弃，独立校验失败不挡其他日期；悬浮给具体缺项代码/日期，收盘和持仓待补分列。395项回归通过，真实源/公司新补齐仍待验收。前序改动：DDB新发布地址192.168.198.77:8904已用于App更新流程，复用原账号密码；数据更新页改为滚动分组、40像素输入框。概览与设置分别显示价格日、DDB目标和Y盘分红日；盘前11-06分红表不能用来判断DDB是否连通。388项回归通过；本机新地址直连超时、未查询11-10，公司更新后按APP_COMPANY_TEST核验。

## 现在从哪里看

| 事项 | 说明 |
|---|---|
| 公司测试、Wind 分阶段命令与回传文件 | [APP_COMPANY_TEST.md](APP_COMPANY_TEST.md) |
| 三类市场概览与数据口径 | [APP_MARKET_OVERVIEW.md](APP_MARKET_OVERVIEW.md) |
| 第六版 32 项研究及 A02 边界 | [APP_INDICATORS_V6.md](APP_INDICATORS_V6.md) |
| 当前源码交接与现场待确认项 | [PROJECT_HANDOFF.md](PROJECT_HANDOFF.md) |
| 实际验证与限制 | [APP_VALIDATION.md](APP_VALIDATION.md) |
| 发布文件清单 | [APP_RELEASE.json](APP_RELEASE.json) |
| 其他说明、冻结 Excel 与旧方案 | [文档分类索引](docs/README.md) |

## 页面与数据

市场概览包括指数、ETF、股指期货；其他研究页暂时停用，源码与32项定义保留。每品种四张期指卡（共16张）显示实际合约，各自按当前 00/01/02/03 连续月份档位的年化基差历史计算 20/60 交易日分位。当前和历史均用分红调整简单年化，缺D仅继承前一到期合约并标来源。当前日排除，已知 T<5 另列规则排除，真实缺价或映射不跳过。研究 A02 的具体合约口径独立保留。

最新价、行情源时间、接收时间、计算及页面应用时间分别保留。连续交易仍用 30 秒时效和 3 秒配对；午休、盘前盘后与已完成收盘参考分开。历史齐备不等于当前报价可用；缺 IOPV、净申赎或 PCF 来源时明确留空。

主HTTP每三秒、成分默认300只/15秒、仍约5分钟一轮独立，缺项下轮优先、低回包下一轮降100。概览自动Wind只用于低频成分、权重、行业、同指数ETF规模及日频净值/同日收盘，复用原 WindPy / 用户 site；个股昨收用HTTP yesterdayClosePrice，已有有效部分即可算行业篮子/贡献，保留覆盖和权重日；完整资料周度复核，缺项每日有界修复。行情分析另按用户所选标的/窗口显式请求Wind分钟/日线，不创建研究服务。App仅补概览所需日线，默认不补全部成分日线/锚点，不下载研究分钟历史；成分每批持久保存raw/SQLite及分类显示缓存，原Parquet保留。DDB先复用本地有效标准历史和独立收盘缓存，仍有概览价格或当前16合约最近完成日OI实际缺口才按原政策准备数据 VPN；实时 VPN 由用户手动连接。

## 更新与排查

默认 `diagnose_presentation.cmd -Overview` 只读已有资料和缓存，不启动采集、不连接 Wind/HTTP/DDB。只有显式 `-WindStage Connect`、`Indices`、`ETFs`、`Nav` 才执行对应低频只读测试。详细复制命令和正常看板的资料发布步骤见 [公司测试](APP_COMPANY_TEST.md)。

正常入口会在身份核验后安全关闭同数据范围的旧看板，等待采集、计算和写入结束再接管；超时只读，不强杀或删锁。设置、进度、暂停、重试和导出在窗口内。原数据、缓存、分红、配置、凭据和 Excel 保留，Excel 冻结功能维护。

七份旧说明及原十项规格见[唯一归档索引](../docs/archive/2026-10-29/README.md)。更早完整说明保存在[历史 README](../docs/archive/2026-10-27/DASHBOARD_README.md)。本目录的正式入口和配置路径未因整理迁移。
