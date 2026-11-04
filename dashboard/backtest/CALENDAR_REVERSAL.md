# 跨期反转：相邻跨期与独立账户

2026-11-04当前要求：**01-02、02-03 × IF/IH/IC/IM，仅原始 q_open=.9、持有到期，共8个独立账户，双腿保证金各100%**。模板已同步；按100%实际重跑整数手数、费用和权益。20%相邻跨期、原48账户和所有旧报告完整保留。用户已确认四品种全历史示例，要求下方补分位并更新PDF；新版6页PDF已完成。收益数值表与每笔收益分布合并一张，账户累计收益与每笔收益明确标非年化，账户CAGR标年化，收益/回撤曲线后置。最差回撤及最终净亏损案例分别排名，详图同时给原始点差和带多空方向的净盈亏点数，标明实际合约、方向、手数、单位及完整日期。

当前报告沿用用户确认的四品种2×2全历史版式，各面板从上到下为原始点差、同时间轴原始分位p、实际收盘持仓。p轴0至1，虚线0.9/0.1仅严格越界开仓；细线读当日连续通道p，粗线读本笔锁定实际pair相对入场通道此前60日分布的p。均来自保存因子，排除当前日，历史不足留空；连续换档处断线。菱形为开仓信号p，圆点为下一有效观测成交日p，倒三角为退出p，不把成交日p当原信号。

新版PDF为6页A3横向，首页原生表前置全部8账户累计收益、年化CAGR、最大回撤/前高/谷底/恢复日期与年化Sharpe，并附总结和收益分布；两通道各有全历史点差/p/持仓图、整笔/回撤段专表及后置收益/回撤曲线。全部32PNG、29CSV、离线HTML和8笔放大案例外置。聊天交付包解压后打开preview.html，PDF在output/pdf/；真实数据和本机绘图脚本不随Git。当前路径、逐格对账和视觉验证见PROJECT_HANDOFF。

本研究复用 `workflow.factor_stage → cta_stage → backtest_stage` 和原执行引擎。每账户默认1000万元，方案间无资金共享或净额。默认前60交易日，保留2023暖启动，从2024年首个交易日评估至所选期货pair共同有效覆盖末日。**当前模板两腿固定保证金100%**。study读取各品种显式且一致的固定margin_rates并写入有效协议，不再硬编码20%；旧20%配置仍可运行，不重写其他情景。改变保证金后复用因子，但必须重跑执行，手续费继续按实际成交的完整名义金额计算。

当前图表示例新增四品种全历史点差与开仓状态，每通道分别为IF/IH/IC/IM选最大单笔持仓峰谷回撤案例。细线按每日实际合约映射画连续入场通道的 `F近-F远` 原始点差（点、非年化、保留正负），粗线只画本笔锁定实际pair；浅金为持仓区间、深金为回撤峰谷区间。红色涨/盈利、绿色跌/亏损；点差涨跌与交易方向后的盈亏独立判断，空价差点差上涨可以亏损。最终净亏损最大的两笔保留补充对照。收益数值与分布仍合并，收益/回撤曲线后置。

同时间轴增加实际成交后/收盘后持仓状态带：灰=空仓无持仓、蓝=多价差（多近空远）、紫=空价差（空近多远），2023暖启动不交易。开仓日纳入、闭合平仓日收盘排除，高亮价格轨迹仍包含平仓成交日。每面板注明样本末日期和是否已开仓；不得把样本末状态当今天状态。离线交互可逐日悬停查实际合约、方向、每腿手数及trade_id，连续映射切换不等于账户隐含换月。逐日状态须与原引擎positions逐格核对，价格须与冻结快照实际代码一致，且每账户无重叠；图表阶段不重新计算因子/CTA/账户。

大回撤示例采用全历史上下文＋固定实际pair局部放大，每行直接写明“卖出近月某合约几手；买入远月某合约几手”等文字及价差上涨时盈亏；单品种详图另附信号/开仓成交/回撤前高/谷底/退出关键节点的两腿价格、p、T、累计净PnL和收盘持仓。期间专表对每笔分别列整笔与最大回撤段的起止日期、实际仓位、点差始末/变化、所持pair的p始末、原信号日p、毛PnL、新增已付费用、净PnL和非年化冻结入场保证金收益率。回撤段净PnL为终点累计净PnL减前高累计净PnL；开仓前0基准需计开仓费。回撤段不是另一笔闭合交易，不计入胜率，最终盈利也可经历大回撤。

连续通道换实际合约时不连线，保留断口/换档标记；局部图全程用同一实际pair。逐日跳变严格拆为 `S新(t)-S旧(t-1)=[S旧(t)-S旧(t-1)]+[S新(t)-S旧(t)]`，两部分分别为旧pair自身跨日变化和当天换pair差异。期限间隔变化可改变原始点差水平，必须给实际代码和T间隔；同一实际pair大变动另列 `ΔS=ΔF近−ΔF远`、来源标签和PnL增量。均读冻结本地快照，无缺价填充；此对账不能代替市场事件归因。p继续只读已保存的实际pair因子，原信号日p与下一有效观测成交日p允许不同，不混用。

## 因子和交易规则

`calendar_pair_percentile` 同时保存两个通道的年化值、原始p、逐日实际合约映射，以及所有此前已出现且尚未到期的实际pair观察表。公式为 `100*(F近-F远)/F近*365/(T远-T近)`，T使用真实剩余自然日，分红显式忽略。历史窗口严格取此前完整window_days交易日，排除当前整日；等值半权，缺项不填补、不缩短窗口。持有旧pair时，使用旧pair当日实际价差相对其**入场通道此前60日连续年化分布**的分位；不是当天新连续pair的p，也不是冻结入场日分布。

CTA `calendar_reversal` 仅读取保存因子，不重读行情或计算分位。参数：

| 参数 | 含义 |
|---|---|
| channel | `01-02`、`01-03` 或 `02-03`，必须包含在保存因子的channels内 |
| root | `all` 或单个IF/IH/IC/IM；all仍是四个独立账户 |
| q_open | 原始p上尾严格越界；`.8`对应p>.8空价差/p<.2多价差，`.9`对应p>.9/p<.1 |
| exit_mode | `expiry` 或 `threshold` |
| q_close | threshold时空价差p≤q_close平、多价差p≥1-q_close平 |
| position_weight | 默认每腿.495；由原引擎按双腿真实保证金和费用预算生成等整数手数 |

多价差=多近/空远，空价差相反。原始q_open=.8/.9等价中心化绝对阈值.6/.8，不能混用旧研究的中心化.8/.9标签。

开仓后锁定实际代码及手数。CTA通过已保存的逐日报价有效标志管理待开/待平状态，旧pair平仓的有效观测到达前不能寻找新开仓，平仓信号当日不重新开仓。原引擎负责下一有效观测成交、整数手数、全名义金额每腿每边万三费用、逐日结算和爆仓；任一腿到期当日close双平优先，未执行的零目标不重复计费。期末不强制平仓。真实行情仅有日线时使用下一交易日实际close，不伪造开盘价。

## 配置与可复制命令

在仓库根（本机 `P:/project/swhy/Delta1/company-apps-worktree`；公司使用现有统一Git根）运行。复制无真实数据的模板到忽略的本机配置目录：

```powershell
Copy-Item dashboard/backtest/calendar_reversal.config.example.json dashboard/localsetting/backtest/calendar_reversal.local.json
```

编辑该本机JSON的 `data.data_root` 为**已有审计快照**目录，所有文件名可保留相对路径。填写真实dataset_id/data_version/source_id。如果复用经授权只读Z导入的本地审计快照，必须显式设置 `data.source_id="local_ddb_plus_authorized_readonly_z_v2"`、`data.allow_readonly_z_import=true`、`data.source_manifest_path="import_manifest.local.json"`；原加载器核验清单及输入SHA。运行时不接受直接Z路径、旧未经审计backfilled缓存。无需重新导入，不连接DDB/VPN。

当前8账户（包括8个单独重跑、因子重读、3个前缀和逐笔对账）：

```powershell
python -m dashboard.backtest.calendar_study --config dashboard/localsetting/backtest/calendar_reversal.local.json --output outputs/backtest/calendar_adjacent_margin100_run01 --q-open 0.9 --exits expiry --no-render
```

输出必须使用新目录。因子参数 `channels=["01-02","02-03"]` 冻结所计算的通道；同一近档只允许一个远档，连续因子列始终对应明确入场通道。改channels或window_days必须重算因子；不能给旧01-03因子改CTA标签后冒充01-02。CTA若请求未保存通道会报错。旧因子未声明channels时仅兼容原默认 `["01-03","02-03"]`。

`--q-open` 可列原始开仓阈值，`--exits` 可选expiry、close0.6、close0.4；矩阵只组合显式所选项。`--no-render`只跳过旧报告生成器，完整计算验证不受影响；`--no-verify`是探索选项，不能作为最终验收。旧报告生成器只接受原完整48方案及20%保证金。复现旧研究时将因子channels改回 `["01-03","02-03"]`、data.margin_rates全部改为0.2，删除factor_input或指向匹配旧因子，再按原默认48矩阵运行：

```powershell
python -m dashboard.backtest.calendar_study --config dashboard/localsetting/backtest/calendar_reversal_legacy.local.json --output outputs/backtest/calendar_legacy_run01
```

标准单方案/单品种（修改本机JSON的cta参数；root=IF只跑IF）：

```powershell
python -m dashboard.backtest.workflow factor --config dashboard/localsetting/backtest/calendar_reversal.local.json --output outputs/backtest/calendar_factor01
python -m dashboard.backtest.workflow cta --config dashboard/localsetting/backtest/calendar_reversal.local.json --input outputs/backtest/calendar_factor01 --output outputs/backtest/calendar_cta01
python -m dashboard.backtest.workflow run --config dashboard/localsetting/backtest/calendar_reversal.local.json --input outputs/backtest/calendar_cta01 --output outputs/backtest/calendar_account01
```

只改CTA阈值/退出/已保存通道/品种、资金或费用，复用同一因子；改 `factor.parameters.window_days`（例如40或120）或channels后重新运行factor。再次跑矩阵时可将顶层 `factor_input` 设为原run的 `factors` 绝对路径，声明和输入SHA不符会拒绝。原 `workflow tune` 兼容此因子与CTA；当前模板grid仅两组通道、固定q_open=.9和expiry：

```powershell
python -m dashboard.backtest.workflow tune --plan --config dashboard/localsetting/backtest/calendar_reversal.local.json
python -m dashboard.backtest.workflow tune --config dashboard/localsetting/backtest/calendar_reversal.local.json --output outputs/backtest/calendar_tuning01
```

以下仅用于原完整48方案的已有结果（不读取行情、不重算；当前8账户的定制6页报告另随聊天交付，不调用此旧PDF入口）：

```powershell
python -m dashboard.backtest.calendar_report outputs/backtest/calendar_reversal_run01
python -m dashboard.backtest.calendar_pdf outputs/backtest/calendar_reversal_run01
```

图表依赖pandas/pyarrow/numpy/matplotlib；PDF另需reportlab/Pillow/pypdf和Windows微软雅黑。PDF固定6页，首页全48方案总结，报告生成器要求完整验证已通过；可通过 `--output` 指定PDF文件。既有引擎依赖不改。

当前示例的Sharpe使用包含空仓交易日的账户日简单收益率，首日以前一初始资金为基准，`mean(r_daily)/std(r_daily, ddof=1)*sqrt(252)`，无风险利率取0；标准差为0时N/A。它与按真实自然日计算的账户CAGR分开，不用每笔入场保证金收益代替账户收益。

用户补充要求展示单笔最大回撤对应持仓日期的绝对价差。示例分别按单笔持仓期净PnL峰谷回撤金额、已闭合交易最终净亏损金额独立排名，各通道各取前两笔，不能把曾经浮亏后收回的交易遗漏。持仓回撤包含开仓前净PnL=0的前高基准；未平仓截至样本末估值。详图只画实际开仓至退出/估值日期的 `F实际近-F实际远` 收盘点差，单位点且保留正负，标出开平仓和回撤前高/谷底；同时保存交易ID、手数、保证金、两腿毛PnL/费用/净PnL。原最终净亏损案例保留作对照，不把跨账户案例排名混成组合账户胜率。

空价差是卖近、买远；近减远点差扩大时会亏损，因此真实点差本身会上行。新版不反转原始价格轴，另外画 `d*(S(t)-S入场)-累计实际费用/(每腿手数*乘数)` 的净盈亏点数，d=+1多价差、d=-1空价差。该线为负即净亏损，回撤向下；乘回实际手数及乘数应逐日等于该笔净PnL。它是带方向的点数损益，不是百分比收益或年化收益；收益分布中的百分比始终为净PnL/冻结入场双腿100%保证金（非年化）。

## 外部详细交付与统计定义

| 文件 | 内容 |
|---|---|
| report.html、figures/*.png | 离线选择全部48方案；收益/同轴百分比回撤、48幅横向分布、8组首笔实际pair示例 |
| csv/account_metrics.csv | 48行账户CAGR/累计收益/回撤/费用，逐方案闭合交易数、盈亏/持平次数、净胜率、平均盈亏金额与收益率、金额及收益率盈亏比 |
| csv/round_trips.csv、trade_legs.csv | 每次完整开仓至双腿退出、实际代码、信号与成交、方向手数、p/T、持有天数、两腿毛净PnL/费用；open单独标记 |
| csv/trades_daily.csv、equity_drawdown.csv | 每笔逐日两腿归因和48账户逐日权益/收益/回撤 |
| csv/drawdown_top3.csv、chart_drawdown_markers.csv | 各账户最大及前3个不重叠的前高至恢复区间；不足3个时如实保留；未恢复持续至期末；图中P/T/R逐点坐标 |
| csv/distribution_bins.csv | 每方案分箱计数、样本量、均值、中位数，与闭合胜率样本一致 |
| csv/factor_actual_pairs.csv | 实际pair当日价差/p、两腿实际价格/T、历史首末日/数量、报价有效标志 |
| cases/*/cta、cases/*/backtest | 原标准产物，可重读权重、成交、权益、持仓、调度；各case四个独立品种账户 |
| study.local.json、input_sha256.local.json、csv/verification.csv | 冻结有效参数、覆盖末日、因子/源文件SHA及每方案验证 |

每笔收益率分母为入场双腿实际 `价格×乘数×绝对手数×20%` 之和，入场后冻结；净PnL扣两腿开平费。净收益率r=净PnL/入场保证金；年化金额为净PnL×365/自然持有天数（元/年）；年化收益率为 `(1+r)^(365/天数)-1`。天数0或r≤-1时两项年化均N/A，注明原因，不截断。账户CAGR以初始资金及实际首末自然日另算。若执行源有分钟，signal p来自信号日，无法对应同刻的执行p留空，绝不把稍后日线p当成交时可知信息。

胜率=该方案净盈利闭合笔数/全部闭合笔数，持平单独列出。平均亏损为负数，盈亏比=平均盈利/平均亏损绝对值；没有盈利或亏损样本时N/A。未平仓净浮盈亏包含已付开仓费，不虚构平仓费，不纳入闭合胜率/年化。不同方案不混合统计胜率。

验证通过只能说明算法前缀、阶段分离和账务一致。本研究是描述性历史参数比较，没有样本外/多重检验修正，参考元数据未包含完整历史发布时刻档案。公司现场运行状态须单独验收；真实数据、配置、CSV/图/PDF及运行结果保持忽略，不提交Git。
