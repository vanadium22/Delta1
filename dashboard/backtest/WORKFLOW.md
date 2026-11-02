# 独立阶段与参数配置

执行链路为：数据读取/标准化 → 因子数值 → CTA 实际合约目标权重 → 回测整数手数/成交/权益。CTA 只接收因子文件及其中冻结的日期、连续映射和到期参考，不重读行情或重算因子。`generate_strategy` 作为旧组合 API 保留，独立入口使用下列函数。

因子阶段不读取执行专用的保证金率/乘数文件；这些文件尚未准备时仍可先做因子和 CTA，执行阶段再严格校验。旧组合 API 返回的 market_data 继续保留旧的完整参数读取方式。

## 最小可运行示例

在仓库根运行，所有输出目录必须是新的；这些命令只生成合成数据：

```powershell
python -m dashboard.backtest.synthetic --output local_artifacts/validation/2026-11-02/quickstart/inputs
python -m dashboard.backtest.workflow factor --config local_artifacts/validation/2026-11-02/quickstart/inputs/index_09.local.json --output local_artifacts/validation/2026-11-02/quickstart/factor
python -m dashboard.backtest.workflow cta --config local_artifacts/validation/2026-11-02/quickstart/inputs/index_09.local.json --input local_artifacts/validation/2026-11-02/quickstart/factor --output local_artifacts/validation/2026-11-02/quickstart/cta09
python -m dashboard.backtest.workflow cta --config local_artifacts/validation/2026-11-02/quickstart/inputs/index_08.local.json --input local_artifacts/validation/2026-11-02/quickstart/factor --output local_artifacts/validation/2026-11-02/quickstart/cta08
python -m dashboard.backtest.workflow run --config local_artifacts/validation/2026-11-02/quickstart/inputs/index_09.local.json --input local_artifacts/validation/2026-11-02/quickstart/cta09 --output local_artifacts/validation/2026-11-02/quickstart/backtest09
```

后两组 CTA 使用同一份 factor 目录。`workflow all --config <配置> --output <新目录>` 组合三个阶段，分别保存在 `factor/cta/backtest`。`workflow schema` 输出每个函数的输入、默认参数、单位、范围和选项。

合成输入目录另外生成 `close.local.json`（连续原始 close 分位＋指数对冲）、`price_basis.local.json`（F−S 分位＋指数对冲）、`spread.local.json`（01−03 价差分位）。分别用 `workflow all` 可独立运行，默认反向、100% 保证金、持有到期；简短示例窗口为 3，正式模板为 60。示例日期和价格不是市场证据。

## 四段配置

无真实数据模板为 [config.example.json](config.example.json)，注册分片模板为 [registered.config.example.json](registered.config.example.json)。仅把本机副本中的数据根目录改成实际路径；标准文件名不变时不需要修改代码或其他阶段。

| 配置段 | 管理内容 |
|---|---|
| data | 路径/格式适配、版本、日线标签、分红假设、参考参数来源；完整契约见 DATA_FORMAT |
| factor | `name`、该函数 `parameters`，以及 `roots/slots/precision/workers` 计算和映射上下文 |
| cta | `name/input_factor/parameters`；变换、阈值、方向、择约及目标仓位管理 |
| backtest | 资金、费用、精度、账户分组、执行进程、d0、数量对冲、换仓时序 |

因子参数不接受 `direction/threshold/position_weight`；CTA 参数不接受 `window_days`。固定阈值不接收 Z 参数，Z 不接收固定开平阈值。错误参数直接报错。旧 `factors/factor_name/strategy_data`、平铺 CTA 和 `FactorConfig/CTAConfig` 接口可迁移读取；桌面新保存统一四段形式，数据路径集中进 data，计算进程与执行进程分别恢复。

## 各函数参数

| 因子 | 输入和内部参数 | 输出 |
|---|---|---|
| annual_basis | F、S、D、T；`min_annual_days=5` 自然日，整数≥1 | `100*(F-S+D)/S*365/T`，百分点 |
| basis_percentile | 同档年化历史；`window_days=60` 交易日，整数≥2；`min_samples=2`，1≤样本≤窗口；`min_annual_days=5` | 原始 p∈[0,1]；保存年化依赖 |
| close_percentile | 连续档原始 close；`window_days=60/min_samples=2` | 原始价格分位 p |
| price_basis_percentile | 连续档 F−S，指数点；同上窗口/样本 | 原始价差分位 p |
| calendar_spread_percentile | 仅计算 01−03 的原始价格差，指数点；同上窗口/样本 | 原始分位放在 01 列，其他档缺失；两腿映射另存 |
| annual_calendar_spread | 01/03 的 F/D/T；min_gap_days=1 自然日，price_base=near/spot | 100*(F01-F03+D01-D03)/base*365/(T03-T01)，百分点 |
| annual_calendar_spread_percentile | 年化跨期，另加 window_days=60/min_samples=2 | 原始 p，年化依赖另存 |
| term_structure_percentile | 年化基差；window_days=60/min_training_samples=120/degree=1/quantiles=.05,.1,.25,.5,.75,.9,.95/min_annual_days=5 | 前序日期的条件期限分位 p，另存 q 曲线及模型诊断；详见 TERM_STRUCTURE |

分位统计采用前 N 个交易日，排除当日，等值计半权；分钟因子也不会将当天后续 close 放进历史。原始因子没有方向、阈值、择约或仓位状态。CTA 参数改变不影响因子文件和逐单元值。

| CTA | 参数/默认值 | 行为 |
|---|---|---|
| fixed | `open_threshold=.7/close_threshold=.2`，0≤close<open；`position_weight=.2`，(0,1]；`direction=1`，±1；`transform=identity`；`missing=flat`；`hedge=none` | 严格越界开/平，区间保持，强反向可反手 |
| zscore | `lookback_window=20`，整数≥2；`z_open=2/z_close=.4`；其余同 fixed | 前 N 日均值/总体标准差，当前日排除；零标准差为缺失 |
| expiry_index | `threshold=.9`，(0,1)；`position_weight=.495` 每腿，(0,.5]；`direction=-1`；`transform=center_percentile`；`selection=product_best` 或 `contract_independent`；`slots=[0,1,2,3]` 唯一档位 | 最大 abs(2p−1) 严格越界开反向仓；同绝对值按较低档/实际代码择优；实际代码锁定至到期 |
| expiry_spread | 与 expiry_index 的 threshold/weight/direction/transform 相同，固定使用 01−03 | 同时锁定当日实际近腿和远腿；任一到期时双平，之后再找越界 |
| expiry_index_structure | threshold=.9/position_weight=.12375 每腿/direction=-1/transform=center_percentile/slots=四档 | 同品种共享资金，每个实际合约独立 pair 并持有至到期；要求 product 和 preserve_pair_lots=true |

`transform=center_percentile` 显式执行 `2p−1`，要求原始值在 [0,1]。fixed/zscore 的 `missing=flat/hold/error`；expiry CTA 在持仓期忽略中途因子变化/缺失。`hedge=index` 为 fixed/Z 增加反向指数目标；expiry_index 固定产生该对冲。`direction=-1` 为反转。

`factor.precision/workers` 与 `backtest.precision/workers` 分别管理。连续 00—03 只用于计算/映射审计；最终权重、订单全是实际代码。持有到期不按每天的新档位替换持仓实际合约。

## 零和手数权重和资金

`backtest.weight_mode="neutral_units"` 要求每品种目标的合约等价手数权重和为零。比如 `IC2612.CFE=+.495, IC_spot=-.495`。指数列是指数单位，不是另一份期货，乘数恒为 1。引擎按每个整数期货手数生成反向 200 个 IC/IM 指数单位或 300 个 IF/IH 单位，保证：

```text
期货手数 × 期货乘数 + 指数单位 = 0
```

资金占用逐腿为 `abs(数量)*价格*乘数*保证金率`。两腿权重各 .495 表示合计 .99 权益预算；引擎先用两腿真实成本算整数期货手数，预留两边手续费，缩手后重新生成精确指数数量。实际资金占比会因两腿价格不同而不同，不能把它误称为资金比例和为零。

跨期使用同品种、相同乘数的两份实际期货，权重相反，整数手数相反；每品种同时只支持一组两腿。引擎在先到期腿的真实 close 关闭整组。当前默认固定保证金情景为 100%，指数也是 100%；可明确改用历史率表。

旧 `weight_mode="capital"` 和“主腿预算整组、指数权重留零”的 `HedgeRule` 输入继续兼容，既有数值语义不变。`neutral_units` 不可拆成 `symbol` 单列账户。指数独立对冲可用 `contract_pair`；择优或跨期可用 `product`，也可 `portfolio` 共用资金。

持有到期 CTA 声明执行要求 `weight_mode=neutral_units, d0=0, rebalance_on_change_only=true`。阶段执行对明确冲突参数报错；桌面生成权重时填入这些要求。d0、费用、实际手数、指数数量、保证金、成交和爆仓仍只由引擎计算。

## Python 独立调用与保存

```python
from dashboard.backtest.__main__ import load_job
from dashboard.backtest.strategy import load_factors, load_cta
from dashboard.backtest.workflow import factor_stage, cta_stage, backtest_stage

def main():
    job = load_job("my_job.local.json")
    raw = factor_stage(job, output_dir="new_factor")
    saved = load_factors("new_factor")
    signal09 = cta_stage(saved, job, output_dir="new_cta09")
    job08 = {**job, "cta": {**job["cta"], "parameters": {**job["cta"]["parameters"], "threshold": .8}}}
    signal08 = cta_stage(saved, job08, output_dir="new_cta08")
    result = backtest_stage(load_cta("new_cta09"), job, output_dir="new_backtest")
    orders = result.actual_orders
    orders_path = result.output_paths["actual_orders"]

if __name__ == "__main__":
    main()
```

更底层的 `compute_factors/generate_cta` 接受内存 `MarketData`、自定义因子和既有参数对象。`FactorResult.save/load_factors` 保存数值、逐日映射、参考和必要上下文，完全不含 CTA 参数；`CTAResult.save/load_cta` 保存实际权重、分数、决策、输入因子声明和指纹。`stage.json` 使用相对内部文件路径及逐文件 SHA，整个目录可移动，加载不访问记录中的原行情路径。损坏、路径越界、覆盖旧输出均拒绝。

执行继续使用原始行情。阶段执行固定相同根的注册版本，并检查同路径宽表是否在因子计算后变化；这些来源记录也随回测保存。未显式登记的本地文件身份不能仅凭文件名证明来源，需提供真实 `source_id`。

## 桌面与验证

四页依次为“数据配置”“因子参数”“CTA 参数”“回测执行参数”。先单独计算保存因子，或在 CTA 页读取因子目录；之后修改阈值直接点“仅运行 CTA”，再执行回测。保存/打开 `.local.json` 恢复四段设置、版本及因子输入目录；后台可取消，写出与关闭安全等待。

离线验收：`python -W error::ResourceWarning -W error::FutureWarning -m unittest discover -s dashboard/backtest/test`；新验收集中在 `test_workflow.py` 与桌面阶段测试，旧交易时序/日结/爆仓/到期双平/指数对冲/多进程回归保留。离屏截图命令见 [公司验证](COMPANY_BACKTEST_TEST.md)。DDB 数据获取继续暂停；合成通过不代表完整真实历史已具备。
