# 接续回测框架与研究提示词

复用 `codex/company-apps` 工作区。先读根、dashboard、backtest 的 AGENTS，以及 PROJECT_HANDOFF、DATA_FORMAT、WORKFLOW；保留四份受保护提示词和其他模块/工作区。按精确文件清单测试、提交、推送，更新 APP_RELEASE 与 COMPANY_SYNC；本机验证与公司现场验收分开。

当前已实现数据标准化与独立阶段。不要再建立组合入口才能运行的因子框架，也不要把数据路径或 CTA 参数放进因子：

1. data 集中管理数据根、文件位置、数据版本、参考参数和分红假设。支持标准 Parquet 宽表、原注册分片和显式旧配置适配；不隐含发现 native。路径冲突、重复、已知混合来源直接报错。原价不填，缺分红不补零。
2. factor 按名称声明内部参数。年化基差/同档年化分位保留，另有连续 close 分位、F−S 分位、01−03 价差分位。分位原始输出 p∈[0,1]，历史窗口排除当前整日。
3. cta 接受保存的 FactorResult 和冻结映射/到期上下文，不读行情或重算因子。固定/Z、方向、显式 2p−1、四档择优/各合约独立、持有到期均独立配置；可以把同一因子用于 0.9/0.8。
4. backtest 管理资金、费用、精度、进程、d0、整数手数和指数数量。neutral_units 要求每品种等价手数权重和为零；期货手数×乘数＋指数数量=0。指数乘数为1，逐腿资金仍按数量×价格×乘数×保证金率；新默认情景100%，既有明确15%结果不改。
5. 连续档只用于计算/审计，持有到期锁定开仓时的实际合约；跨期仅01−03，任一腿到期时双平，再找越界。执行仍为下一共同有效原始 close、日结、收盘/逐报价风控；共用账户统一结算，独立账户与注册分日读取保留有界进程。

Python 入口 `workflow.factor_stage/cta_stage/backtest_stage`；独立结果用 `load_factors/load_cta`。CLI 为 `python -m dashboard.backtest.workflow factor|cta|run|all`，参数/示例见 WORKFLOW。桌面四页分别保存恢复，可单独计算、读取因子和仅运行 CTA。合成输入生成器为 `python -m dashboard.backtest.synthetic --output <新目录>`。

真实数据仍只在本机原位，源码发布不含行情、配置、缓存、截图或真实报告。已核对纯来源日线只有2025-07-01—2026-10-14，312个日期，4指数/76实际期货、84个参考；完整2024至今及暖启动仍缺数据。旧 backfilled 混合缓存及其派生试跑已排除，不可拼接。

**DDB 获取按用户最新要求继续暂停，不探测路由、不连接或登出 VPN。** 旧 VPN 曾获授权执行后仍遇到 DDB ConnectionRefused，随后用户明确暂停；不要回到旧“等待授权”结论，也不要根据此提示词恢复抓取。未来仅按新的明确指示接续已有 acquire_daily，自动增量另行制作。

修改后运行离线完整回归（ResourceWarning/FutureWarning作错误）、Ruff，以及 `test.validate_stages_ui` 的1080p/4K离屏验证；给出实际输出位置。合成收益不是市场证据，公司现场仍待实际执行。
