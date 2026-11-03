# 标准框架调参与阶段复用

本功能直接使用 Delta1 已有的 `factor_stage → cta_stage → backtest_stage`，以及 `FactorResult/CTAResult` 的 Parquet＋SHA产物。逐个调用、桌面单次调参和批次调参使用相同函数及同一回测引擎。无需另外维护因子、成交、保证金或权益实现。

## 蓝色历史分位与紫色回归

两者的数值输入都是 `100*(F-S+D)/S*365/T`。普通历史分位在**同一连续档位**此前N交易日的年化基差里计算当前值的位置，当前日不进历史，等值计半权。它不单独解释剩余期限。

条件分位回归在同品种此前N交易日的各有效期限观察中，拟合年化基差对标准化T/365的条件分位，默认一次项，也可配置二次项。当前实际合约根据自身T取得预测分位曲线，再反插值得到p；回归响应不是未来收益。它对“什么期限应该对应什么基差分布”增加了模型假设，不保证优于直接历史分位。

两种原始p均由CTA显式转成2p−1，同一阈值、方向、独立账户和持有到期规则保持一致。交易日窗口、最小样本等参数均由各因子的现有schema校验。

跨期图 `calendar_returns.png` 的颜色含义不同：蓝色为阈值0.9、橙色为0.8，目前跨期为01−03年化历史分位。四格分别IF/IH/IC/IM，收益已扣费；完整结果仍由 `slot_report` 从保存产物重画。

## 哪些参数放哪里

| 配置 | 参数例子 | 改动后的阶段 |
|---|---|---|
| data | data_root、文件、版本、分红假设 | 新输入重新计算因子，执行仍核验版本/SHA |
| factor | window_days、min_samples/min_training_samples、degree、quantiles、min_annual_days；跨期min_gap_days/price_base | 重算该因子 |
| cta | threshold、direction、position_weight、slots；固定/Z各自内部参数 | 复用因子，重新生成CTA |
| backtest | 初始资金、费用、执行精度、进程等 | 复用因子和不变CTA，重新执行 |

backtest.start/end会改变CTA的起始持仓状态，因此重新生成CTA。持有到期CTA的执行约束仍适用，包括d0=0、on-change和neutral_units；批次配置不会绕过这些规则。保证金/乘数属于执行输入，不改变数值因子缓存。

桌面四页继续用于单次调参。改变因子窗口/模型/计算范围/数据声明后，点击“仅运行CTA”会明确提示先重新计算，不能把旧60日因子当成新40日；仅改变CTA参数则可直接复用。保存重开同时保留JSON中的tuning批次设置。

四页修改的是单次基础配置；运行批次时grid候选值优先，批次阈值/窗口请修改tuning.grid中的列表。

## 单独调用及兼容现有产物

```powershell
python -m dashboard.backtest.workflow factor --config my.local.json --output outputs/backtest/NEW_FACTOR
python -m dashboard.backtest.workflow cta --config my.local.json --input outputs/backtest/NEW_FACTOR --output outputs/backtest/NEW_CTA
python -m dashboard.backtest.workflow run --config my.local.json --input outputs/backtest/NEW_CTA --output outputs/backtest/NEW_RUN
```

Python API仍为 `workflow.factor_stage/cta_stage/backtest_stage`；原run_backtest、自定义内存输入和桌面打开历史结果保持兼容。CTA输入旧的已发布因子产物仍受支持，新增元数据仅补充因子所用数据声明，不改变原始数值。

## 批量调参

在原四段配置之外增加可选tuning段：

```json
{
  "tuning": {
    "grid": {
      "factor.parameters.window_days": [40, 60],
      "cta.parameters.threshold": [0.9, 0.8],
      "cta.parameters.slots": [[2]],
      "backtest.commission_rate": [0.0003, 0.0005]
    },
    "max_runs": 32
  }
}
```

此例为8组配置：两个因子窗口各算一次，四份CTA各生成一次，执行8次。slots=[2]表示固定02档入场，成交后锁定实际合约到期；如需16条期现PnL，可使用[[0],[1],[2],[3]]及四品种。先校验、预览，再执行：

```powershell
python -m dashboard.backtest.workflow tune --config my.local.json --plan
python -m dashboard.backtest.workflow tune --config my.local.json --output outputs/backtest/NEW_TUNING
```

--plan不读行情、不执行回测；执行时才核验实际文件和来源。每个候选配置都走原函数的参数校验，未知字段/不兼容组合明确拒绝；超出max_runs须调整配置。不会自动挑选一个“最佳参数”替代完整结果。

`factor_input` 可指向已保存因子目录，适合只调CTA和执行参数，此时计算次数为0。重用会核对函数、内部参数、根/档位、精度和数据声明；进程数不改变原始因子语义。改变因子参数时清空factor_input重新计算，或提供匹配的产物。已有合并因子目录可以同时提供其中已声明的普通分位、回归和跨期因子。

模板 [tuning.config.example.json](tuning.config.example.json) 提供历史分位/回归两个命名case及四档两阈值，共16组配置；[tuning.calendar.config.example.json](tuning.calendar.config.example.json) 提供跨期窗口/阈值四组配置，均不含真实数据。case沿用四段配置的覆盖语法；换因子函数时清除上一函数的内部参数，避免将min_samples误传给回归。grid在case合并后生效。

每个不同的因子声明/数据输入只计算一次；只改手续费、资金时CTA也复用。所有组执行前仍固定相同来源版本、检查实际使用文件是否变化；连续档位与实际合约两份原始因子均逐单元核验，在CTA后、执行前以及执行后检查不变。

输出 `plan.local.json`、`tuning.local.json`、`summary.csv`、共享factor/cta目录，以及每组 `variants/vXXXX/job.local.json` 和标准 `backtest/`。summary逐账户提供实际自然日CAGR、回撤、PnL、费用、订单、参数变化与缓存复用标记；单组结果可由现有桌面直接重开，或从该job＋CTA目录精确复跑。

## 本机验证

合成8配置验证：2次因子计算、4份CTA、8次执行；保存job通过标准执行入口重跑权益完全相同。保存因子两阈值验证计算次数0，窗口变化拒绝误用旧因子。输入位置仅改data_root可切换，桌面保存重开不丢批次参数，因子参数变化不会悄悄复用旧值。

已有2024起冻结因子的小范围真实验证为4组阈值×费用配置、16个品种账户：因子计算0次，唯一因子1份、CTA2份，原始数值指纹不变。未进行无关全量参数搜索。DDB/VPN继续暂停，Z源未操作；真实配置和结果均在忽略目录，不随源码发布。
