# 看板文档索引

当前运行版本b7d5d55，438项本地运行回归通过，HTTP/DDB新公司结果待回传。11月11日随后只做[指标页分析与模拟示意](INDICATOR_PAGE_PROPOSAL.md)，正式新页尚未接入；四项统计统一t_z、虚线横跨t_w、跨期分母S已确认。[下一对话提示词](NEXT_COMPANY_RETEST_PROMPT.md)包含现场检查与新页要求，不覆盖四份受保护旧提示词。

2026-11-11，基线596839d。HTTP缺显式交易日时，仅在连续交易时段用两次已归档行情交叉核验：同实际代码/稳定昨收、真实市场字段变化、源时钟随接收时间推进且新鲜；通过后按交易日历补准确前一日close，并明确标注corroborated_live_session/日期推定，不能声称交易所认证日期。盘前/午休/盘后、静止或陈旧快照、冲突日期及换日/换时段证据不放行。 用户最新要求DDB不暂停，继续原自动数据VPN/历史补齐；已手动连接且新地址192.168.198.77:8904可达时复用现有隧道，不重复登录。实时VPN仍手动，原DDB/VPN配置、账户密码和原文件不改。 438项独立完整回归通过，103.831秒（含加载），无跳过、ResourceWarning作为错误；原420项重跑，新增18项连续会话证据、日期边界、缓存重算与DDB隧道复用验证。 公司596839d包已证HTTP20个标的全因source_trade_date_missing补入0，DDB停route/waiting_vpn/login，11-10四指数+16期货收盘缺失。本轮新会话推定方案与用户修复后的DDB连接仍待新公司包，不以本地模拟代替源端验收。

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
