# 看板文档索引

2026-11-11，基线30937eb。本地日线优先，再用HTTP yesterdayClosePrice补源交易日的准确上一交易日，重新核验缺口后DDB仅补剩余历史收盘及最近完成日OI。HTTP必须带明确且一致的tradeDate/tradingDate/tradingDay、匹配实际securityId，并核验两日挂牌/到期和交易日历；只有时分秒或盘前旧快照不入日线。盘后昨收仍写前一交易日，不写当天；昨结算/当前价/当前OI不代替昨日数据。 420项独立回归通过，117.339秒（含加载），无跳过、ResourceWarning作为错误；原395项重跑，新增25项HTTP昨收、日期/合约/路由与页面缓存回归。 公司真实HTTP是否提供可认证交易日、11-10两腿收盘、全部四档20/60分位和新DDB端点仍待新安全反馈包；不把本地合成测试当公司已补齐。

| 分类 | 文件 |
|---|---|
| 日常打开/复测 | [常用入口](../常用入口/README.md)，原脚本和桌面入口仍可使用 |
| 当前交接与下一对话 | [PROJECT_HANDOFF](../PROJECT_HANDOFF.md)、[可复制新提示词](NEXT_COMPANY_RETEST_PROMPT.md) |
| 公司完整操作 | [一键复测CMD](../company_retest.cmd)、[APP_COMPANY_TEST](../APP_COMPANY_TEST.md)：更新、Y盘/指定文件分红、行业/ETF、开窗/关闭后Overview、安全JSON ZIP |
| 发布与本地验证 | [APP_RELEASE精确文件清单](../APP_RELEASE.json)、[APP_VALIDATION](../APP_VALIDATION.md)、[统一更新](../../COMPANY_SYNC.md) |
| 当前数据口径 | [市场概览](../APP_MARKET_OVERVIEW.md)、[数据能力/字段契约/行情分析](DATA_CAPABILITIES.md)、[本地字段模板](etf_fields.example.json) |
| 使用与开发规则 | [README](../README.md)、[打开方式](../打开方式.md)、[AGENTS](../AGENTS.md) |
| 十项已实施与原始规格 | [当前实施入口](NEXT_OVERVIEW_IMPLEMENTATION.md)、[原规格唯一归档](../../docs/archive/2026-10-29/OVERVIEW_IMPLEMENTATION_SPEC.md) |
| 连接及刷新诊断 | [连接](../CONNECTION_DIAGNOSIS.md)、[刷新](../REFRESH_DIAGNOSIS.md)、[短文件名](../SHORT_FILENAMES.md) |
| 保留的研究/实现契约 | [32项第六版](../APP_INDICATORS_V6.md)、[数据契约](../data_contract/README.md)、[盘中工作区](../INTRADAY_WORKSPACE.md)、[指标实现](../INDICATOR_IMPLEMENTATION.md)、[合约对指标](../PAIR_INDICATORS.md)；研究服务暂停 |
| 冻结Excel/旧部署/方案 | [旧公司部署](../COMPANY_SETUP.md)、[数字Excel](../NUMERIC_EXCEL.md)、[旧检查单](../COMPANY_CHECKLIST.md)、[Excel提案](../EXCEL_UX_PROPOSAL.md)、[界面方案](../UI_SIMPLIFICATION.md) |
| 历史说明与哈希索引 | [2026-10-29七份唯一归档](../../docs/archive/2026-10-29/README.md)、[MANIFEST](../../docs/archive/2026-10-29/MANIFEST.json)、[更早README](../../docs/archive/2026-10-27/DASHBOARD_README.md) |

AGENTS、PROJECT_HANDOFF、APP_RELEASE、APP_COMPANY_TEST等固定入口保留。归档的ROOT_AGENTS/DASHBOARD_AGENTS不是当前指令入口；旧UNC、旧固定分红情景和阶段限制不覆盖最新用户要求。不重复制作多套旧说明。项目总体目录见 [分类索引](../../docs/PROJECT_STRUCTURE.md)。

2026-11-11：DDB端点192.168.198.77:8904与原凭据分离、更新页分组滚动、价格日/DDB目标/Y盘分红日独立显示。388项本地回归通过，新端点源端11-10与公司布局仍待现场核验；详见当前交接/验证及公司操作。
