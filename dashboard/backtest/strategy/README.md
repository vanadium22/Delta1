# 因子 → CTA → 实际合约目标

本模块先按每个交易日的挂牌/到期资料将实际合约映射为 `IC00.CFE`—`IC03.CFE` 等计算档位，再生成因子和 CTA 状态。最终 `factors`、`scores`、`targets` 的列全部是实际合约；00—03 只在 `panel`、`continuous_factors` 和映射审计中出现，不作为成交代码。

## 数据与参数接口

| 接口 | 内容 |
| --- | --- |
| `market_data: MarketData` | 内存价格、乘数、保证金、合约挂牌/到期参考及可选调整价、剩余天数 |
| `data_config: DataConfig` | 注册 data/看板配置，或 `close_path`、`daily_close_path`、`minute_close_path` 等已有文件入口 |
| `data_loader(DataConfig) -> MarketData` | 自定义数据读取器；后续 DDB 更新应落 Delta1/data，再通过该接口或文件位置接入 |
| `StrategyDataConfig.dividend_store_root` | 已有按实际合约和生效版本保存的 `records.sqlite` 目录，只读 |
| `dividend_records_path` / `dividend_book` | 分红版本 JSON，或兼容现有 `DatedDividendBook` 的内存读取器 |
| `dividend_points` / `DataConfig.dividend_points_path` | 实际合约 × 日期的剩余分红点数，明确 0 有效，缺失不当 0 |
| `DataConfig.adjusted_close_path` | 明确提供的 `F+D` 调整价格，与原始 close 的差为 D |
| `calendar` / `calendar_path` | 交易日序列或 JSON `trading_days`、CSV `trade_date/date/timestamp`；未指定时使用行情出现过的日期 |
| `extra_data` | 自定义因子额外大表，按同一映射转成连续档位，放入 `panel.extras` |
| `FactorConfig` | 品种、00—03 档位、精度、分位窗口、年化有效最小 T、最少有效样本和读取进程数 |
| `CTAConfig` | 固定/Z 阈值、Z 历史窗口、方向、每档资金占用和缺失值处理 |

要完整核对交易日缺口，应显式提供交易日历。已有行情中出现的缺数不会被跳过，显式日历缺整天会保留为缺失；仅凭观测日期不声称覆盖完整交易日历。日频默认使用实际日末观测；`FactorConfig.precision="auto"` 保留输入日内时刻，统计窗口仍使用之前交易日的最后观测。

注册行情复用按日分片、SHA 核验和有界进程读取，默认日频仅读取所选品种的每日 close；没有日线时才读分钟取得当天最后实际观测。`FactorConfig.workers=0` 按规模自动选择最多 4 个，`1` 串行，桌面共用“计算进程”设置。自动精度读取所需分钟与日线。

合约参考必须包含实际 `instrument_id`、`listing_date`、`expiry_date`。每日每品种按到期排序形成四档；到期当天保留旧映射，下一挂牌日再切换。四档不完整时记录缺口，不将仅有的远月随意改成 00。映射依赖历史挂牌/到期资料，不声称其历史发布时间已经核验。

分红复用原项目 C 列实际合约、G 列点数、Sheet1!B1 业务日期及生效版本逻辑。新版本不回写过去，明确 0 优先；缺合约时仅按原逻辑读取当时已知的前序到期合约估计，保留版本和来源。单日固定快照只能作为显式情景，不能冒充逐日历史 D。`dividend_revisions.parquet` 保留每个计算单元的版本。

项目排除 Z 盘依赖；不扫描或回退到 Z 盘。DDB 自动抓取/更新按用户最新要求留给后续制作，当前不隐含网络任务。

## 两个示例因子

`annual_basis` 按既有口径计算：

```text
annual_basis = 100 × (F - S + D) / S × 365 / T
```

单位是百分点；D 是到期前剩余分红点数、T 是剩余自然日。默认 `min_annual_days=5`，T<5 不生成有效年化，不用图表填充值交易。此参数与回测的强平 `d0=0` 独立。

`basis_percentile` 取当前实际合约今天所在档位的过去 `window_days=20` 个交易日年化序列，排除今天。比如 `IC2703.CFE` 今天是 02，使用过去各日当时 02 对应合约的年化，不使用 IC2703 自身整段历史。

```text
p = (历史值小于当前值的数量 + 0.5 × 历史值等于当前值的数量) / 历史有效数量
```

输出 0—1。窗口内已知 T<5 的日期明确排除；其余缺价、缺 D、缺映射会使窗口不可用，不缩短成较少天数。默认最少 2 个有效样本。计算后自动将今天的分位值放回今天的实际合约列。

## CTA 阈值与状态

- 固定模式：`abs(score)>0.7` 按符号开多/空，`abs(score)<0.2` 平仓，其间保持原状态；强反向信号直接反手。等于阈值时保持。
- Z 模式：用之前 `lookback_window=20` 个交易日的均值和总体标准差（ddof=0）计算当前 Z，`abs(Z)>2` 开仓、`abs(Z)<0.4` 平仓。当天后续价格不参与当天任何时刻的历史统计；缺失或零标准差保持不可用。
- `direction=1` 正值开多、负值开空，`-1` 反向。`position_weight=0.2` 表示每个档位占用权益 20%，总预算仍由回测的 0.99 上限控制。
- 分位示例先用 `transform="center_percentile"` 计算 `score=2p-1`；0.7 对应 p>0.85，-0.7 对应 p<0.15，平仓区间为 0.4<p<0.6。原始因子文件仍保存 p。
- `missing="flat"` 默认将不可用因子输出零目标；可显式选择 `hold` 或 `error`。不会填补因子值。状态在连续档位上保持，再按当日映射输出完整实际合约目标，换月时旧合约列归零。

## 调用和运行

```python
from pathlib import Path
from dashboard.backtest import BacktestConfig, DataConfig, run_backtest
from dashboard.backtest.strategy import CTAConfig, FactorConfig, generate_strategy

def main():
    data = DataConfig(
        daily_close_path=Path("data/daily_close.parquet"),
        minute_close_path=Path("data/minute_close.parquet"),
        reference_path=Path("data/reference.json"),
        dividend_points_path=Path("data/dividend_points.parquet"),
        margin_rate_path=Path("data/margin_rate.parquet"),
    )
    strategy = generate_strategy(
        data_config=data, factor_config=FactorConfig(window_days=20),
        factor_name="basis_percentile",
        cta_config=CTAConfig(transform="center_percentile"),
        output_dir=Path("outputs/my_strategy"),
    )
    backtest = run_backtest(strategy.targets, data_config=data,
                            config=BacktestConfig(d0=0), output_dir=Path("outputs/my_backtest"))
    actual_orders_df = backtest.actual_orders
    actual_orders_path = backtest.output_paths["actual_orders"]

if __name__ == "__main__":
    main()
```

也可以直接给 `run_backtest` 输入 00—03 目标表，引擎会先按信号日期展开为实际合约，并分别保存原始指令和 `execution_instructions.parquet`。同品种不要同时输入连续和具体合约目标。稀疏指令不会在没有新指令时自动换月；生成框架输出逐日完整目标，因此会明确表达换月。实际交易始终遵循回测的下一有效报价、原始 close 和临期强平规则。

复制本目录 `config.example.json` 为本机 `.local.json`，填好输入位置后运行：

```text
python -m dashboard.backtest.strategy --config <策略配置.local.json>
python -m dashboard.backtest.strategy.examples --output <新的本机示例目录>
```

第二条生成 35 天隔离合成输入的两个因子及三组目标：年化固定阈值、分位固定阈值、年化 Z 阈值。其报价、挂牌日和到期日均为测试夹具，不是实际市场输入。

桌面“因子与CTA”页提供同样的品种/档位、窗口、固定/Z 阈值、方向、占用比例和分红资料入口；“生成因子与目标表”完成后自动填入实际合约目标位置，再检查并回测。

## 自定义因子

```python
from dashboard.backtest.strategy import CTAConfig, FactorDefinition, generate_strategy

definition = FactorDefinition(
    name="my_factor",
    required_data=("close", "spot"),
    required_parameters=("scale",),
    compute=lambda panel, params: (panel.close - panel.spot) * params["scale"],
)
result = generate_strategy(
    data_loader=my_data_loader,  # DataConfig -> MarketData，自行接入所需真实数据
    factor_definitions=[definition], factor_parameters={"my_factor": {"scale": 1.0}},
    factor_name="my_factor", include_examples=False,
    cta_config=CTAConfig(mode="zscore", lookback_window=20),
)
```

计算函数必须返回与 `panel.close` 完全同形、同索引的连续档位表，缺数据保留 NaN。通过 `required_data`、`required_parameters` 声明所需输入；额外实际合约大表传 `extra_data={"field": df}`，在函数中读取 `panel.extras["field"]`。只做自定义因子可设置 `include_examples=False`，不会强制要求两个示例所需的分红输入。

输出目录不覆盖已有运行。`targets.parquet/csv`、`scores.parquet`、`factors/` 为实际合约表；`continuous_factors/`、`continuous_*`、`slot_mapping.parquet` 和分红版本用于检查计算过程。全部位置通过 `result.output_paths` 返回。
