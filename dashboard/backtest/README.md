# 股指期货大表回测

独立的本地研究模块：目标比例大表输入，下一行情时间戳默认足额成交，输出账户、实际整数持仓和可直接读取的开平仓指令。仅使用本地数据，运行不启动行情采集或网络连接。

## 交易与资金口径

- 列为具体合约，如 `IC2612.CFE`、`IF2703.CFE`，或 `IC_spot`；行是时间戳。正负数表示多空，零表示平仓。每一行是完整目标，没有新指令时保持实际手数。
- `0.3` 直接表示目标占用权益 30%；多空绝对值合计超过 `max_capital_usage=0.99` 才同比例缩减。按价格、乘数、保证金率计算手数并向零取整，再预留手续费。
- 在严格晚于信号时间的下一条行情以原始 close 成交，先平后开。名义本金手续费默认每边 `0.0003`，反手拆平旧仓和开新仓。
- 日期及无时区午夜标签默认转上海时间当日 15:00；日线信号下一交易日 close 成交，日期信号接分钟线时下一交易日首条行情成交。可用 `date_at` 修改日期时刻；Unix 时间戳必须设置 `timestamp_unit`。
- 期货按旧持仓相邻 close 价差盯市，不扣整笔名义本金。`_spot` 为乘数 1、全额资金占用的合成指数份额，支持做多、做空；未包含真实 ETF 跟踪、借券或现金派息。
- 默认爆仓条件为 **账户总权益 < 当前持仓所需保证金 × 0.0001**，对应 `margin_call_basis="equity"`。触发时以当前 close 强平并停止账户。输出 `available_equity` 是总权益减保证金后的余额，仅用于资金占用展示；要用它判断必须显式选择同名可选口径。
- 价格缺失直接报错，不填充或跳过订单。不自动换月或猜测到期结算；到期前应发出平仓指令。默认末日保留仓位，可用 `liquidate_at_end=True` 平仓并收费。
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

result = run_backtest(
    instructions_path=Path("dashboard/backtest/inputs/targets.parquet"),
    data_config=DataConfig(
        close_path=Path("data/backtest/close.parquet"),
        margin_rate_path=Path("data/backtest/margin_rate.parquet"),
    ),
    config=BacktestConfig(mode="portfolio", initial_capital=10_000_000),
    output_dir=Path("outputs/backtest/my_run"),
)
actual_orders_df = result.actual_orders
actual_orders_path = result.output_paths["actual_orders"]
actual_orders_df = pd.read_parquet(actual_orders_path)
```

从 dashboard 或任何目录可调用 `python <仓库>/dashboard/backtest/run.py audit|run`。复制 `config.example.json` 为本机 `job.local.json`，填好指令及行情/保证金位置，运行 `python <仓库>/dashboard/backtest/run.py run --config <配置文件>`。配置中相对路径按配置文件所在目录解释。输出每次使用新目录，不覆盖旧结果。

`output_dir` 保存全账户 `actual_orders.parquet`、可读的 `actual_orders.csv`、`summary.csv`、`metadata.json`，以及每账户的权益、实际持仓、有效目标、信号执行计划。所有输出位置通过 `result.output_paths` 返回绝对路径。成交表包括信号/成交时间、具体合约、开平动作、方向、手数、价格、乘数、保证金率、费用和前后持仓；元数据记录参数、信号指纹和行情版本。

## 验证与交付

仓库根运行 `python -m unittest discover -s dashboard/backtest/test -v`。测试只用隔离核算输入，覆盖交易时序、手算盈亏、整手/费用预算、三种分组、默认总权益爆仓、保证金变化、缺价不填和文件导出，不进入真实数据目录。

源码和无真实数据的配置模板随统一分支发布。真实指令、数据、配置及产物仅本机保留，当前工作见 [交接](PROJECT_HANDOFF.md)。
