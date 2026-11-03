# 股指期货大表回测

独立的本地研究模块：数据读取/标准化 → 因子 → CTA 目标权重 → 实际手数、成交和账户权益。三个计算阶段可以分别调用、保存和重新读取。仅使用明确配置的本地数据，不启动行情采集或网络连接。新规范见 [数据格式](DATA_FORMAT.md) 和 [分阶段调用及最小示例](WORKFLOW.md)。

年化期现、按两到期日差年化的 01−03、各实际合约独立对冲指数及期限结构条件分位回归见 [结构研究](TERM_STRUCTURE.md) 与 [配置模板](structure.config.example.json)。`structure_study` 保存因子后复用两阈值、逐 pair 对账并生成 PnL/收益/具体持仓图和离线交互报告；`structure_report` 可只重读产物画图，不重新计算因子。

用户最新确认的研究口径是 **16个固定档位独立期现账户＋4个独立跨期账户**，各组不共享资金/指数净额；开仓锁定实际合约，到期后仍从原档位选下一组。当前入口 `slot_study/slot_report`、[固定档位说明](FIXED_SLOT_STUDY.md)、[模板](slot.config.example.json)。2026-11-03获准只读Z源后，可独立导入本地data快照；默认仍不连接DDB/VPN、不在Z写文件。

## 桌面窗口

双击仓库内 `dashboard/start_backtest.vbs` 启动蓝白风格的独立桌面窗口；需要命令行入口时用同目录 `start_backtest.cmd`。复用已有看板的 Python 选择规则、PySide6 和 pyqtgraph，不启动看板采集或更改 Wind 环境。依赖清单为 `requirements-desktop.txt`，已有环境可直接复用。

1. “数据配置”集中设置数据根、文件、版本、参考、保证金和分红假设；显示实际绝对路径和覆盖。不预选 native，不发现混合缓存。新配置显式固定保证金默认 100%。
2. “因子参数”单独计算并保存原始因子；“CTA 参数”读取该目录，修改阈值/方向/持仓规则后点“仅运行 CTA”，无需重算因子。支持原两个因子、固定/Z、四档择优反向持有到期，以及连续价格/价差和 01−03 跨期示例。
3. “回测执行参数”设置目标表、资金、费用、账户、执行精度/进程及 d0。“检查数据”核对本地覆盖后执行。读取和计算可取消，写出与关闭安全等待。
4. 右侧查看净值、保证金占比、收益/回撤/费用、实际开平仓/持仓/账户明细。按账户切换，表格可搜索及排序，鼠标悬停曲线可查看时点数值。图表按实际观测序列压缩非交易间隔，标签仍是对应上海时间。
5. 每轮在结果根目录下生成独立 `run_*` 子目录，包含实际成交表、输入指令快照和本机 `job.local.json`。可复制成交表绝对路径，或“打开历史结果”重新读取完整运行目录；整个目录移动后仍可重新打开。
6. 四段配置及因子输入目录均可保存恢复；因子与执行进程分别配置。标准宽表模板为 `config.example.json`，分片模板为 `registered.config.example.json`。完整最小合成输入由 `python -m dashboard.backtest.synthetic --output <新目录>` 生成。

“打开配置”/“保存配置”和文件选择均在窗口内显示。配置文件使用 `.local.json`，默认保存位置为 `dashboard/localsetting/backtest/job.local.json`；保存过该默认配置后，下次启动自动读取。界面适配 1920×1080 和 3840×2160，窄窗使用滚动及上下排列图表。

直接调用可使用 `python -m dashboard.backtest.desktop_run --config <本机配置>`、`--result <既有结果目录>`，或 `python <仓库>/dashboard/backtest/desktop_run.py ...`。桌面入口仅本地，不访问外部网络，不弹出模态向导或自动打开 Excel。

## 回测精度、日结与多进程

| `BacktestConfig.precision` | 指令与成交 | 爆仓检查 | 权益输出 |
| --- | --- | --- | --- |
| `"1d"`，默认 | 每个交易日取输入最后一个完整目标，于当日收盘时视为已知；下一交易日首个共同有效报价执行 | 每日收盘、在同一收盘时点的调仓前后检查 | 每个交易日一条，用当天实际 close 估值 |
| `"auto"` | 对齐输入日频/分钟精度，保留日内信号；严格在之后的首个共同有效报价执行 | 对每个可观测报价逐时点检查，恒定持仓区间用向量化批量计算 | 同样只输出每日收盘，不生成完整分钟净值表 |

当天末条指令不能在当天 close 立即成交。例如日频 D 日目标在 D+1 日首条有效分钟 close 成交，随后使用 D+1 日的日线 close 统计当日总权益。没有分钟报价时，回退到 D+1 日真实日线 close 及其原始时刻成交；不会将该收盘价标成开盘价。多腿账户使用持仓和新目标共同可用的首个报价，具体合约独立账户可各自找到首个有效时点。成交表的 `price_source`、`execution_precision` 记录实际分钟价或日频回退。

日频模式只保留必要的开仓报价与每日 close；自动模式读取持仓期间的必要分钟分片，行情无持仓的时段不做逐条账户计算。指令生效、实际成交和每日收盘是核算事件；两事件之间持仓恒定，可直接计算价差，并在自动模式批量扫描所有报价的爆仓条件。分钟缺口不会用未来价格补齐，只在下一真实报价/日线 close 回退，缺口数量记录在本轮元数据。

最大回撤按日结净值统计。爆仓当日只输出一条强平后权益，`trigger_time`、`blown_at` 和实际成交时间保留准确触发时刻，后续交易日不再产生结果。`positions` 为日结实际持仓，`target_weights` 只保留实际执行时的有效目标；原始全部输入仍在 `instructions.parquet`。

`workers=0` 默认按任务量选择最多 4 个进程，小任务串行避免启动开销；`workers=1` 强制串行，也可指定 2/4 等正整数。注册行情按日分片并行读取与预处理，单标的和同品种独立账户可并行核算。全市场账户保持一份资金统一结算，其行情预处理可以并行。已停止的任务等待自有进程安全退出，保存阶段完整写出后结束。

Windows 的 Python 外部调用应放在 `if __name__ == "__main__":` 保护下；现有 CLI/桌面启动器已经处理入口。交互单元可设 `workers=1`，没有可导入入口时自动进程选择会保守使用串行。

## 交易与资金口径

- 列为具体合约，如 `IC2612.CFE`、`IF2703.CFE`，或 `IC_spot`；行是时间戳。正负数表示多空，零表示平仓。每一行是完整目标，没有新指令时保持实际手数。
- 兼容的 `weight_mode="capital"` 中，`0.3` 表示目标占用权益 30%；多空绝对值合计超过 `max_capital_usage=0.99` 才缩减。新的 `neutral_units` 模式要求每品种合约等价手数权重和为零，配对整数数量和资金核算见下文。
- 在严格晚于信号时间的下一条行情以原始 close 成交，先平后开。名义本金手续费默认每边 `0.0003`，反手拆平旧仓和开新仓。
- 日期及无时区午夜标签默认转上海时间当日 15:00；收盘信号下一交易日首个有效分钟报价成交，没有分钟时在真实日线 close 回退。可用 `date_at` 修改日期时刻，日频精度仍按当日收盘目标处理；Unix 时间戳必须设置 `timestamp_unit`。
- 期货按旧持仓相邻 close 价差盯市，不扣整笔名义本金。`_spot` 为乘数 1、全额资金占用的合成指数份额，支持做多、做空；未包含真实 ETF 跟踪、借券或现金派息。
- 默认爆仓条件为 **账户总权益 < 当前持仓所需保证金 × 0.0001**，对应 `margin_call_basis="equity"`。触发时以当前 close 强平并停止账户。输出 `available_equity` 是总权益减保证金后的余额，仅用于资金占用展示；要用它判断必须显式选择同名可选口径。
- 新订单寻找下一真实有效报价，必要时日频回退，延期及实际成交源可追溯；必须估值的日末持仓价格或保证金率缺失会报错。不自动换月或猜测到期结算。未到临期阈值的末日仓位默认保留，可用 `liquidate_at_end=True` 平仓并收费。
- `d0=0` 默认在到期日实际 close 强平对应期货；可设正整数提前，比较 `T<=d0`，T 为剩余自然日。临期不新增仓位，已有非零目标保持原手数至收盘，明确零目标仍可按普通指令提前退出。强平计费并记录 `reason="expiry_d0"`；有 `HedgeRule` 时同步关闭对应指数单位，其他合约及未关联现货保留。开启时非零期货目标必须有到期参考或 T 表；`d0=None` 仅为显式停用兼容选项。
- `symbol` 每列独立账户，`product` 同品种合约及现货共用账户，`portfolio` 全表共用账户；`contract_pair` 将每个实际期货和关联指数腿放在一个独立账户。每个独立账户拥有一份初始资金，分组后不将子表放大到满仓。
- `rebalance_on_change_only=True` 先在各账户去除重复目标，之后保持实际手数；适合持有到期。默认 False 保持原有“每个输入行都代表一次调仓”的接口行为。

## 指数点值对冲与 60 日持有到期研究

新 `weight_mode="neutral_units"` 输入例如 `IC2612.CFE=+.495, IC_spot=-.495`，等价手数权重和为零；引擎按整数期货手数生成反向 200 个指数单位（IF/IH 为 300），指数乘数为 1。逐腿资金占用仍是数量绝对值×价格×乘数×保证金率；默认显式保证金 100%，两腿合计 .99 预算并预留费用。跨期两份同品种实际合约取相反整数手数，首腿到期时双平，持仓代码不随档位滚动。完整规则见 [WORKFLOW](WORKFLOW.md)。

旧 `capital` 模式的 `HedgeRule("IC2612.CFE", "IC_spot", -200)` 和 `index_hedges` 保留：只填期货资金预算，指数列省略或零，主腿预算整组；该输入语义不变。

本轮专项入口 `python -m dashboard.backtest.carry_study --config <study.local.json> --output <新目录>`，默认 2024-01-01 至 2026-11-02、前 60 个交易日同档分位、中心化 score=2p−1，分别跑绝对阈值 0.9/0.8，反向交易、四档择优、实际手数持有到期双平，分红明确为零。同时运行全部实际合约的独立对冲账户，分别输出期货腿、指数腿和合并盈亏。数据位置和资金参数见 [专项说明及模板](CARRY_STUDY.md)。

正式入口先校验暖启动和交易日覆盖，缺历史默认报错。`--allow-partial` 只生成显式标注的已有覆盖期检查，不能当作完整 2024 至今结果。当前纯 DDB 本地日线仅覆盖 2025-07-01 至 2026-10-14；全区间仍待补取。报告包含 PnL/回撤/逐合约图、离线交互因子图、实际开平仓和逐笔因子值，可在桌面重开每个标准运行目录。

## 数据与指令接口

| 接口 | 输入 |
| --- | --- |
| `instructions` / `instructions_path` | 直接传目标 DataFrame 或可读文件位置 |
| `instruction_loader` | 自定义 `Path -> DataFrame` 读取函数 |
| `market_data` | 直接传 `MarketData(close, multiplier, margin_rate, adjusted_close)` |
| `DataConfig.data_root` / `history_roots` | 已有共享 data 根目录或已注册行情数据集 |
| `dashboard_config_path` | 可选已有看板配置，只读取数据路径，不写回设置 |
| `close_path` | 自有原始 close 大表，替代默认行情源 |
| `minute_close_path` / `daily_close_path` | 分钟成交价与每日收盘估值表，可分别指定；未指定日线时从已有分钟数据取当天最后观测，保留真实时间 |
| `reference_path` / `MarketData.contracts` | 已有实际合约挂牌/到期参考，计算剩余自然日、限制合约区间及构造四档映射 |
| `days_to_expiry_path` / `MarketData.days_to_expiry` | 可选逐日剩余自然日；与明确到期日有冲突时报错，不把昨天 T 原值沿用至今天 |
| `multiplier_path` / `multipliers` | 时变乘数表或固定映射；内置 IF/IH=300、IC/IM=200 |
| `margin_rate_path` / `margin_rates` | 历史保证金率表或显式固定假设，15% 写 `0.15`，不猜测缺失值 |
| `adjusted_close_path` / `dividend_points_path` | 分红调整价或分红点数表，供上游研究使用，不替代成交 close |

文件支持 Parquet、CSV、TSV、Feather；本机可信 pkl 需显式 `trusted_pickle=True`。CSV 使用 `timestamp` / `date` / `datetime` / `event_time` 列。指令 NaN 默认报错，需要把它解释为零目标时明确设置 `nan_policy="zero"`。

指数映射：`000905.SH -> IC_spot`、`000300.SH -> IF_spot`、`000016.SH -> IH_spot`、`000852.SH -> IM_spot`。保证金率和乘数按生效时间沿用上一行，不倒填未来值；显式 NaN 不恢复旧值，参数也不跨合约列填充。

数据集必须为未复权、具体合约序列，通过活动 manifest 冻结版本读取；重复 bar 报错。历史发布时间未知时需显式 `allow_unverified_availability=True`，只表示允许修订历史研究，不证明当时可知。分红快照须显式选择情景，规则见 [数据接口说明](DATA_ASSESSMENT.md)。

## 调用

仓库根目录下运行：

```python
from pathlib import Path
import pandas as pd
from dashboard.backtest import BacktestConfig, DataConfig, run_backtest

def main():
    result = run_backtest(
        instructions_path=Path("dashboard/backtest/inputs/targets.parquet"),
        data_config=DataConfig(
            minute_close_path=Path("data/backtest/minute_close.parquet"),
            daily_close_path=Path("data/backtest/daily_close.parquet"),
            reference_path=Path("data/backtest/contracts.parquet"),
            margin_rate_path=Path("data/backtest/margin_rate.parquet"),
        ),
        config=BacktestConfig(mode="portfolio", initial_capital=10_000_000,
                              precision="1d", workers=0),
        output_dir=Path("outputs/backtest/my_run"),
    )
    actual_orders_df = result.actual_orders
    actual_orders_path = result.output_paths["actual_orders"]
    actual_orders_df = pd.read_parquet(actual_orders_path)

if __name__ == "__main__":
    main()
```

从任何目录可调用 `python <仓库>/dashboard/backtest/run.py audit|run`，直接执行已有目标表。新研发优先用 [WORKFLOW](WORKFLOW.md) 的 `factor/cta/run` 独立命令。数据文件相对路径以 `data_root` 为基准，根目录本身和无根时的路径以配置文件目录为基准；输出每次使用新目录。

运行可用 `--precision 1d|auto --workers 0|1|2|4` 覆盖配置。行情源按需组合分钟和日线；旧 `data.frequency` / `--frequency` 保留给单频审计和兼容读取，运行精度以 `precision` 为准。

`--d0 0` 为默认到期强平阈值。可直接输入 00—03 目标，按信号当天四档映射展开；最终成交仍为实际代码，原始表及 `execution_instructions.parquet` 分别保存。分位/CTA 示例输出已经是实际合约表，无需再转换。剩余天数保存到 `days_to_expiry.parquet`，位置通过 `result.output_paths` 返回。

运行时拒绝直接Z路径和旧未经审计的混合来源缓存。用户2026-11-03已授权Z只读导入，须走新快照、授权标记及SHA清单核验，见 [FIXED_SLOT_STUDY](FIXED_SLOT_STUDY.md)，不自动复用旧混合试跑。DDB获取继续暂停；独立 `acquire_daily` 和自动增量留后续。

`output_dir` 保存全账户 `actual_orders.parquet`、可读的 `actual_orders.csv`、`summary.csv`、`metadata.json`，以及每账户的权益、实际持仓、有效目标、信号执行计划。所有输出位置通过 `result.output_paths` 返回绝对路径。成交表包括信号/成交时间、具体合约、开平动作、方向、手数、价格、乘数、保证金率、费用和前后持仓；元数据记录参数、信号指纹和行情版本。

`result.input_instructions` / `instructions.parquet` 保留本轮输入指令快照；`load_result(目录)` 可重新读取结果。原有内存及文件读取接口兼容，新增可选 `cancel_event` 和 `progress` 回调便于接入其他前端。

## 验证与交付

仓库根运行 `python -m unittest discover -s dashboard/backtest/test -v`。测试只用隔离核算输入，覆盖交易时序、手算盈亏、整手/费用预算、三种分组、默认总权益爆仓、保证金变化、缺价不填和文件导出，不进入真实数据目录。

2026-11-02 本机隔离合成基准，使用自动精度、显式 d0=None 隔离核算开销；成交、日末权益和费用与前序 `93e467f` 实现对账，串行/多进程结果一致：

| 场景 | 输入规模 | 原实现或串行 | 本轮实现 |
| --- | --- | --- | --- |
| 稀疏指令、全市场账户 | 252 天 × 240 分钟 × 16 标的，51 条信号 | 逐分钟 2.085 秒 | 事件核算 0.104 秒，303 次估值，252 条日结 |
| 密集指令、4 个独立品种账户 | 24 天 × 240 分钟 × 16 标的，5,759 条信号 | 串行 3.181 秒 | 4 进程 1.759 秒，包含进程启动 |

这是本机该组输入的单次计时，实际任务取决于指令密度、账户数量、磁盘与进程开销。可将 `93e467f` 的 `dashboard/backtest/engine.py` 保存至本机忽略目录，再运行：

```text
python -m dashboard.backtest.test.benchmark_performance --baseline <旧引擎.py> --output <本机报告.json>
python -m dashboard.backtest.test.validate_performance_ui --config <本机配置> --output <本机验证目录>
```

前者只生成隔离合成价格；后者显式读取所选本机数据，离屏运行日频/自动和两个分辨率，所有报告及截图保持本机。

源码和无真实数据的配置模板随统一分支发布。真实指令、数据、配置及产物仅本机保留，当前工作见 [交接](PROJECT_HANDOFF.md)。
