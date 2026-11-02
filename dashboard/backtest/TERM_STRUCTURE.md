# 年化期限结构与逐实际合约 pair 研究

2026-11-03。数据规范及阶段接口沿用 [DATA_FORMAT](DATA_FORMAT.md) / [WORKFLOW](WORKFLOW.md)。研究链路为本地数据标准化 → 保存原始因子及拟合诊断 → CTA → 原回测引擎 → 逐 pair 对账与离线图表。DDB 获取继续暂停，不连接或探测 VPN，不使用 Z 或已知 Z 派生混合源。

## 年化定义

所有本专项的分位和回归响应均建立在年化数值上，收益报告也同时给出年化。F/S 是同日原始期货/指数 close，D 是明确配置的剩余分红指数点，T 是真实到期参考推导的剩余自然日。

```text
年化期现基差（百分点）= 100 × (F − S + D) / S × 365 / T
年化跨期（百分点）   = 100 × (F01 − F03 + D01 − D03) / F01 × 365 / (T03 − T01)
区间净收益            = 期末权益 / 初始资金 − 1
年化净收益 CAGR       = (期末权益 / 初始资金)^(365 / 实际经过自然日) − 1
```

跨期沿用用户指定的 01−03 符号，分母期限是**两者剩余天数之差**，不能单独除近腿或远腿 T；每日倒计时不改变两到期日的距离。默认用近腿 F01 归一化；`price_base=spot` 可显式改为同日指数。两腿同单位、相同乘数，D 取各自到期口径；ignore 模式显式 D=0，required 模式缺 D 保持缺失。年化过程不改变成交价格。

`annual_calendar_spread` 参数为 `min_gap_days=1`（自然日，整数≥1）、`price_base=near`（near/spot）；`annual_calendar_spread_percentile` 另外声明 `window_days=60/min_samples=2`。必须有 01/03 档，已知非正期限差直接报错。近腿已过期、价格非正或缺失则无值；已知期限差小于最小值排除，其他历史缺失使分位窗口无效。仅 01 列输出该两腿信号，映射另存。

CAGR 用权益序列首末上海时间戳的实际秒数/86400，含周末假期；默认包含闲置现金、已扣手续费和期末未平仓浮盈亏。没有正时长或期末权益为负时不报告 CAGR；终值为零且时长正时为 −100%。最大回撤不再年化。旧原始价格/F−S/跨期价差因子为兼容仍保留原名与原单位；本专项不把它们当成年化输入。

## 期限结构条件分位回归

`factor.name=term_structure_percentile` 按品种分别拟合，不混用品种价格水平。每个日期取**此前** 60 个交易日、全部所选 00—03 档对应实际合约的有效观察，响应 y 为该合约当天的年化期现基差，以 T/365 标准化后的一次或二次多项式作解释变量。所有历史样本等权，无当前日训练、无未来收益标签。

| 内部参数 | 默认值和单位 | 校验 |
|---|---|---|
| window_days | 60，交易日 | 整数≥2；取完整此前窗口 |
| min_annual_days | 5，自然日 | 整数≥1；已知 T 更小的样本排除 |
| min_training_samples | 120，日期×合约观察数 | 整数≥3，不能超过窗口×档数 |
| degree | 1，期限多项式阶数 | 1 或 2 |
| quantiles | .05/.10/.25/.50/.75/.90/.95，概率 | 3—19 个严格递增 (0,1) 概率，必须包含 .5 |

其他缺价、缺 D、未知 T 或映射使窗口无效，不缩窗。期限无变化/设计矩阵秩不足时记明原因并输出缺失；求解失败报错，不代用历史分位。按每个 q 最小化 check loss：`Xβ+u−v=y`，β 自由，u/v≥0，目标 `q·sum(u)+(1−q)·sum(v)`，使用 [SciPy HiGHS dual simplex](https://docs.scipy.org/doc/scipy/reference/optimize.linprog-highs-ds.html)。响应/解释变量的条件分位模型定义也见 [Statsmodels QuantReg](https://www.statsmodels.org/stable/generated/statsmodels.regression.quantile_regression.QuantReg.html)；本实现使用 LP，不调用其 IRLS 求解器。

当日每个期限上的预测分位排序，消除交叉后反插值得到 `p∈[0,1]`；网格之外饱和为 0/1，预测值相同取对应概率均值。原始 p 不包含方向、阈值或仓位。因子另外保存 q 曲线（百分点）和 `diagnostics/quantile_models.parquet`：训练首末日、样本数、缺项/求解状态、期限均值/标准差、β、loss 和交叉计数。报告画最近一次各品种期限曲线及实际合约点；覆盖率 CSV 使用时间向前的预测，仅作描述统计，不声称观察彼此独立。

当前检验的是“偏离历史条件期限结构后反转”；没有将未来 pair 收益作为回归响应。滚动前序拟合不等于数据本身已通过严格 point-in-time 可用性审计，未核验的注册 available_at 必须继续显式标记。

## 每个实际合约单独组成 pair，同品种共享资金

`cta.name=expiry_index_structure` 接收原始因子及日期/真实合约映射，不读取价格或重算回归。每个合约独立检查 `abs(2p−1)>threshold`，`direction=-1` 做反转；开仓后忽略中途分数变化，锁定实际代码直到真实到期。连续合约换档不换持仓实际代码。

默认 `threshold=.9`、每腿 `position_weight=.12375`、候选四档，四组两腿的预算合计 .99。0.9 是中心化分数阈值，对应原始 p 的两侧 5%，0.8 对应两侧 10%。CTA 的权重和按品种为零；IC/IM 每手配反向 200 指数单位，IF/IH 配 300，指数自身乘数为 1。例如 +2 手 IC2612 配 −400 IC_spot 单位。

引擎要求 `mode=product, weight_mode=neutral_units, d0=0, rebalance_on_change_only=true, preserve_pair_lots=true`。新增 preserve_pair_lots 只锁住非零且目标未变的已持有期货手数，避免其他 pair 开平触发旧 pair 重新按权益/价格定手；显式改目标或清零仍正常执行，风控及到期仍由引擎处理。默认 false 保持既有执行行为。

每腿占用为 `abs(实际数量)×价格×乘数×保证金率`，默认两腿 100%。不同 pair 的虚拟指数腿可以相互抵消；实际账户持有、成交、计费和保证金都按指数净额计算。逐 pair 归因按各期货手数生成虚拟指数流，指数**实际**成交费用按当事件各 pair 的期货等价变动分摊；不凭空按虚拟毛额收费。实际净指数保证金按各虚拟腿绝对数量分摊，另列 `gross_pair_margin` 供毛额审计，不能把它相加当实际保证金。

逐 pair 期货盈亏＋指数盈亏−分配费用必须逐日与账户盈亏对齐，数量与实际净指数对齐，分配保证金和费用也必须对齐，否则研究中止。跨期归因另按实际成交、到期双平重建每一组近远合约，不将不同合约组合并成一个永久 pair。全部归因可按品种本金计算收益贡献，不能为每个合约重复分配一份初始资金。

主比较默认每品种 4,000 万元，四品种合计 1.6 亿元，所有方法同资本；另显式测试每品种 1,000 万元。四份预算在 100% 保证金下容易不足一手，不能把由整数约束造成的低资金利用率误判为无信号。此资本设置是研究配置，不是数据修改。

## 调用和最小合成例

无真实数据模板：[structure.config.example.json](structure.config.example.json)。宽表根目录可以仅改 data_root，注册分片适配沿用 [注册模板](registered.config.example.json)。全部活动参数可在桌面四页保存并恢复。

```powershell
python -m dashboard.backtest.synthetic --output local_artifacts/validation/demo_structure/inputs
python -m dashboard.backtest.structure_study --config local_artifacts/validation/demo_structure/inputs/structure.local.json --output local_artifacts/validation/demo_structure/run --synthetic --capital-sensitivity 10000000
```

该合成配置窗口 3 日、最少 8 个训练观察、q=.1/.5/.9，仅用于验证。正式使用本机配置后运行：

```powershell
python -m dashboard.backtest.structure_study --config my_structure.local.json --output outputs/backtest/NEW_STUDY --capital-sensitivity 10000000
python -m dashboard.backtest.structure_report --study outputs/backtest/NEW_STUDY
```

第二条仅从保存的因子、账户和归因重画，不读取原始行情、不重新拟合。第一条默认计算并保存一份合并因子集，比较年化基差四档择优、年化基差各 pair、条件分位回归各 pair 和年化 01−03 两阈值。`--no-render` 可先完成数值；`--factor-artifact OLD_STUDY/factors` 复用已存因子并检查声明、数据版本/文件 SHA 和分红假设。修改阈值不重算原始因子，研究检查逐单元指纹。

仍可单独使用 `workflow factor` → `workflow cta` → `workflow run`；回归因子文件也能复用于其他兼容 CTA。新增专项产物：

- `summary.csv/by_product.csv/study.local.json`：CAGR、区间收益、回撤、费用、绝对源路径、版本及逐账户审计。
- `pnl_returns.png/per_product.png`：总 PnL、累计收益、回撤和分品种收益。
- `pairs_latest.png/pairs_maximum.png/pair_positions.png/pair_contribution.png`：实际两腿、最多同时 pair 的首日快照、持仓历史和全部 pair 贡献。该日按持仓数选择，未按收益挑选。
- `quantile_structure.png/quantile_coverage.csv`：条件期限曲线、实际合约和描述覆盖率。
- `report.html`：离线交互切换方案/品种/日期/实际 pair，查看具体数量、净指数、保证金、pair PnL 和账户收益；无 CDN。
- 各方案目录含独立 CTA、标准 backtest、可重开本机 job、逐 pair Parquet/CSV；不覆盖旧运行。

真实配置、输入、数值、图片和报告均留本机忽略目录；发布只含源码、说明及数据为空的模板。本机真实覆盖仅 2025-07-01—2026-10-14，60 日暖启动后共同评估 2025-09-23—2026-10-14，不能称完整 2024 至今回测。公司现场仍待运行。
