# 股指期货大表回测

独立的本地研究模块：目标比例大表输入，下一行情时间戳默认足额成交，输出账户、实际整数持仓和可直接读取的开平仓指令。仅使用本地数据，运行不启动行情采集或网络连接。

## 桌面窗口

双击仓库内 `dashboard/start_backtest.vbs` 启动蓝白风格的独立桌面窗口；需要命令行入口时用同目录 `start_backtest.cmd`。复用已有看板的 Python 选择规则、PySide6 和 pyqtgraph，不启动看板采集或更改 Wind 环境。依赖清单为 `requirements-desktop.txt`，已有环境可直接复用。

1. 在“策略与资金”选择目标指令文件、账户分组、回测精度、计算进程、区间、初始资金及费用。精度默认日频，进程默认按工作量自动选择；资金比例和爆仓默认值与引擎一致。
2. 在“行情与参数”选择已有看板数据/共享根目录或自有 close 表，填历史保证金率表，或明确选择固定比例假设。分红调整、参考、乘数和历史发布时间选项也在此处。
3. “检查数据”读取指令及本地覆盖，区分必要缺项和可选分红缺项；“开始回测”在后台核算。读取和计算可以取消，保存阶段等待完整写出，关闭窗口也安全等待任务结束。
4. 右侧查看净值、保证金占比、收益/回撤/费用、实际开平仓/持仓/账户明细。按账户切换，表格可搜索及排序，鼠标悬停曲线可查看时点数值。图表按实际观测序列压缩非交易间隔，标签仍是对应上海时间。
5. 每轮在结果根目录下生成独立 `run_*` 子目录，包含实际成交表、输入指令快照和本机 `job.local.json`。可复制成交表绝对路径，或“打开历史结果”重新读取完整运行目录；整个目录移动后仍可重新打开。

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
- `0.3` 直接表示目标占用权益 30%；多空绝对值合计超过 `max_capital_usage=0.99` 才同比例缩减。按价格、乘数、保证金率计算手数并向零取整，再预留手续费。
- 在严格晚于信号时间的下一条行情以原始 close 成交，先平后开。名义本金手续费默认每边 `0.0003`，反手拆平旧仓和开新仓。
- 日期及无时区午夜标签默认转上海时间当日 15:00；收盘信号下一交易日首个有效分钟报价成交，没有分钟时在真实日线 close 回退。可用 `date_at` 修改日期时刻，日频精度仍按当日收盘目标处理；Unix 时间戳必须设置 `timestamp_unit`。
- 期货按旧持仓相邻 close 价差盯市，不扣整笔名义本金。`_spot` 为乘数 1、全额资金占用的合成指数份额，支持做多、做空；未包含真实 ETF 跟踪、借券或现金派息。
- 默认爆仓条件为 **账户总权益 < 当前持仓所需保证金 × 0.0001**，对应 `margin_call_basis="equity"`。触发时以当前 close 强平并停止账户。输出 `available_equity` 是总权益减保证金后的余额，仅用于资金占用展示；要用它判断必须显式选择同名可选口径。
- 新订单寻找下一真实有效报价，必要时日频回退，延期及实际成交源可追溯；必须估值的日末持仓价格或保证金率缺失会报错。不自动换月或猜测到期结算；到期前应发出平仓指令。默认末日保留仓位，可用 `liquidate_at_end=True` 平仓并收费。
- `symbol` 每列独立账户，`product` 同品种合约及现货共用账户，`portfolio` 全表共用账户。每个独立账户拥有一份初始资金，分组后不将子表放大到满仓。

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

从 dashboard 或任何目录可调用 `python <仓库>/dashboard/backtest/run.py audit|run`。复制 `config.example.json` 为本机 `job.local.json`，填好指令及行情/保证金位置，运行 `python <仓库>/dashboard/backtest/run.py run --config <配置文件>`。配置中相对路径按配置文件所在目录解释。输出每次使用新目录，不覆盖旧结果。

运行可用 `--precision 1d|auto --workers 0|1|2|4` 覆盖配置。行情源按需组合分钟和日线；旧 `data.frequency` / `--frequency` 保留给单频审计和兼容读取，运行精度以 `precision` 为准。

`output_dir` 保存全账户 `actual_orders.parquet`、可读的 `actual_orders.csv`、`summary.csv`、`metadata.json`，以及每账户的权益、实际持仓、有效目标、信号执行计划。所有输出位置通过 `result.output_paths` 返回绝对路径。成交表包括信号/成交时间、具体合约、开平动作、方向、手数、价格、乘数、保证金率、费用和前后持仓；元数据记录参数、信号指纹和行情版本。

`result.input_instructions` / `instructions.parquet` 保留本轮输入指令快照；`load_result(目录)` 可重新读取结果。原有内存及文件读取接口兼容，新增可选 `cancel_event` 和 `progress` 回调便于接入其他前端。

## 验证与交付

仓库根运行 `python -m unittest discover -s dashboard/backtest/test -v`。测试只用隔离核算输入，覆盖交易时序、手算盈亏、整手/费用预算、三种分组、默认总权益爆仓、保证金变化、缺价不填和文件导出，不进入真实数据目录。

2026-11-02 本机隔离合成基准，使用自动精度；成交、日末权益和费用与前序 `93e467f` 实现对账，串行/多进程结果一致：

| 场景 | 输入规模 | 原实现或串行 | 本轮实现 |
| --- | --- | --- | --- |
| 稀疏指令、全市场账户 | 252 天 × 240 分钟 × 16 标的，51 条信号 | 逐分钟 2.070 秒 | 事件核算 0.077 秒，303 次估值，252 条日结 |
| 密集指令、4 个独立品种账户 | 24 天 × 240 分钟 × 16 标的，5,759 条信号 | 串行 2.947 秒 | 4 进程 1.820 秒，包含进程启动 |

这是本机该组输入的单次计时，实际任务取决于指令密度、账户数量、磁盘与进程开销。可将 `93e467f` 的 `dashboard/backtest/engine.py` 保存至本机忽略目录，再运行：

```text
python -m dashboard.backtest.test.benchmark_performance --baseline <旧引擎.py> --output <本机报告.json>
python -m dashboard.backtest.test.validate_performance_ui --config <本机配置> --output <本机验证目录>
```

前者只生成隔离合成价格；后者显式读取所选本机数据，离屏运行日频/自动和两个分辨率，所有报告及截图保持本机。

源码和无真实数据的配置模板随统一分支发布。真实指令、数据、配置及产物仅本机保留，当前工作见 [交接](PROJECT_HANDOFF.md)。
