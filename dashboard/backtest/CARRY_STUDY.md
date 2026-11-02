# 60 日分位反向持有到期研究

专项入口复用现有因子、大表回测和桌面结果读取，参数模板为 `carry.config.example.json`。2026-11-02 的请求区间是 2024-01-01 至 2026-11-02。当前本地纯 DDB 日线只覆盖 2025-07-01 至 2026-10-14，已有覆盖期检查不能视为完整区间结果。

## 固定策略口径

1. 每日按真实挂牌/到期参考，把 IF/IH/IC/IM 各四个期限映射到 00/01/02/03。到期日仍保留当天真实合约；不从最后价格日或月份猜到期日。
2. 本专项分红明确设为零，年化基差为 `100*(F-S)/S*365/T`，单位百分点。`min_annual_days=5` 沿用框架默认值；持仓后不因近到期因子失效而提前平仓。
3. 取该合约今天所在档位的前 `window_days=60` 个交易日年化序列，排除今天，用小于值加等值半权算分位 p。窗口内已知 T<5 单列排除，其他缺价/映射不缩短窗口；实际历史样本数一并输出。实际合约换档后，历史窗口随当天档位选择。
4. `score=2*p-1`。分别运行严格 `abs(score)>0.9` 和 `>0.8`，对应 p>0.95/小于0.05，以及 p>0.9/小于0.1。每个品种空仓时选绝对值最大的期限；并列先较近档位，再实际代码。高分位做空期货、低分位做多，指数反向。
5. D 日 close 因子产生目标，严格在之后的第一个共同有效**日线 close** 成交。本专项只读日线，不能将次日 close 写成开盘或首分钟价。
6. 开仓后忽略因子变化和权益重估，实际手数保持到 T=0 当天 close，两腿同步平仓并各收费用。到期日收盘完成双平后可产生下一组信号，其成交仍为之后的有效 close；未到期的区间末仓位只盯市，不虚构双平。

同时运行 `product_best` 四个品种各自四档择优账户，以及 `contract_independent` 所有实际合约互不竞争的独立对冲账户。后者每个合约仍只在自身信号越线后开仓；无信号合约保留零收益账户。两个阈值分别从头计算，不共享持仓或资金。

## 对冲与资金

指数为乘数 1 的合成指数单位。1 手 IF/IH 对应反向 300 单位指数，1 手 IC/IM 对应反向 200 单位指数。两腿点值匹配，不分别按相等资金目标计算；期货整数手数决定指数数量，减仓、费用预算和到期平仓都保持此关系。

每手组合资金需求为 `F*期货乘数*保证金率 + S*指数单位数`。当前每账户初始资金默认 1,000 万、固定保证金率 100%（明确情景，不是历史实际账户率）、最大占用 0.99，两腿各按名义本金每边万三收费。既有 15% 输出保留原参数。指数多空均全额占用，未包含真实 ETF 跟踪、借券及现金分红。

账户总权益低于当前持仓保证金要求×0.0001 时爆仓。每日 close 输出权益和最大回撤；`attribute_legs` 依据实际成交和持仓分别计算期货/指数腿净盈亏，逐笔总和、两腿总和必须对到账户权益。独立账户不能直接相加冒充共享资金组合收益率。

普通大表可通过配置声明关联关系，例如：

```json
{
  "mode": "contract_pair",
  "d0": 0,
  "rebalance_on_change_only": true,
  "hedges": [{"primary": "IC2612.CFE", "hedge": "IC_spot", "quantity_ratio": -200}]
}
```

输入期货列，指数列省略或为零；非零指数权重与关联规则同时出现会报错。`index_hedges(实际合约列表)` 可批量构造规则。共享指数时引擎汇总各实际合约应对冲单位，到期仅解除到期合约对应的部分。

## 数据接口与完整性

复制模板为本机 `.local.json`，指定 `data.daily_close_path` 的时间×实际合约/指数 close 大表，及 `data.reference_path` 的合约参考；也可设置纯来源 `history_roots`。乘数默认 IF/IH=300、IC/IM=200。原始指数代码自动映射为四个 `*_spot`，最终因子/交易均输出实际合约代码。

模板 `study` 包含起止日、暖启动日、60 日窗口、两组阈值、初始资金、保证金情景、费用、资金上限、最小年化 T 和工作进程数。`run_carry_study(market_data=MarketData(...), config=CarryStudyConfig(...), output_dir=...)` 保留内存输入，文件输入使用 `DataConfig`。

完整运行要求首个请求交易日前至少 60 个交易日行情、四个指数和逐日四档实际合约都齐备。交易日历包含已核验的 2023—2026 年，超出范围会报错。缺暖启动、缺中间数据或超出允许尾部延迟时默认失败并输出 `requested_coverage.json`，不会补零、用 Z 混合来源或拼合成数据。`allowed_tail_sessions=1` 仅容许当天日线未发布，报告仍明确截至最近真实交易日，不标为完整覆盖今天。

```text
python -m dashboard.backtest.carry_study --config <study.local.json> --output <新的结果目录>
```

仅检查现有区间可显式追加 `--allow-partial`，所有图和报告带 `AVAILABLE DATA ONLY`；这会从可用数据起点重新暖启动，不会冒充 2024 年已开始的策略持仓。

## 一次性 DDB 历史补取

使用已有含 DolphinDB SDK 的 Python、原本机连接文件及已经可用的数据路由运行。命令不连接/切换/登出任何 VPN，不更改远端数据：

```text
python -m dashboard.backtest.acquire_daily --connection <原连接.local.json> --output <Delta1/data/market/index_futures/backtest/carry60/新快照> --start 2023-07-01 --end 2026-11-02
```

日线源为 `dfs://ods_tsdb_y_wind/cindexfutureseodprices`（期货）、`dfs://ods_tsdb_m_wind/aindexeodprices`（指数），挂牌/到期参考为 `dfs://ods_tsdb_wind/cfuturesdescription`。字段按当前目录声明读取，按年/标的有界查询，实际重复修订冲突报错。合约月份只用于查询筛选，真实日期全部从参考返回。

新目录保留 raw Parquet、归一 close、参考、覆盖、来源版本及文件 SHA/大小清单；父目录追加下载索引，生成 `data_config.local.json` 可直接传给专项入口。没有自动增量计划，不扫描 Z，不覆盖旧数据/配置；历史数据属于当前修订研究资料，不宣称历史发布时间可知。DDB 不提供本专项的历史账户保证金或分红假设。

2026-11-02 最新状态：VPN 此后曾获用户授权执行，但 DDB 返回 ConnectionRefused，随后用户明确暂停数据获取。当前继续暂停，不探测路由、不连接或登出 VPN。旧补取命令仅保留为未来接续说明，须按未来新指示执行；不能自行恢复。完整数据补齐后仍应从 2024 年重跑全部账户，不拼接已有覆盖期结果。

## 结果位置与桌面使用

- `report.html`：离线中文汇总，主策略及所有实际合约表可搜索；`pnl.png`、`drawdown.png`、`independent_contracts.png` 和 `legs_0_9/0_8.png` 可单独打开。
- `factor_inspector.html`：离线交互曲线，悬停显示当天实际合约、年化、p、score 和样本数；菱形/圆形是开仓信号。PnL 图三角/叉为实际开仓/双平。
- `factor_values.csv/parquet`：具体因子值、档位、F/S/T、年化、分位、score、样本数；00—03 只作为映射审计字段，交易 symbol 为实际合约。
- `trades.csv/parquet`：每次信号/成交/到期或末日估值、实际期货手数、反向指数单位、两腿费用与盈亏、每手盈亏；`decisions.csv` 保存每天择优/持有/到期/空仓决策。
- `summary.csv/parquet`、`daily_attribution.parquet`：所有账户的收益/回撤及两腿日结归因。每个阈值/分组目录均保留标准 `actual_orders.csv/parquet`、权益/持仓和 `job.local.json`。

双击 `dashboard/start_backtest.vbs`，用“打开历史结果”选择 `product_best_0_9`、`product_best_0_8` 或 `contract_independent_0_9/0_8` 目录；可切换品种/实际合约，查看 PnL、回撤和两腿开平仓明细。要复跑时打开该目录的 `job.local.json`，可读数据与目标位置已经保留。全部真实输入、配置和结果只留本机，不随源码提交。
