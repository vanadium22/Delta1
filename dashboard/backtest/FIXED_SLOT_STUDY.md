# 固定档位：16组独立期现与4组跨期

2026-11-03用户已确认两项口径：期现按 IF/IH/IC/IM × 00/01/02/03 分成16个独立账户，跨期每品种一组01−03，共4账户；阈值沿用 `abs(2p−1)>0.9/0.8`，即两侧5%/10%。这替代前轮“同品种共享资金、所有实际合约各自持有”的研究比较；旧模式及结果保留，不混为本轮。

## 一组到底怎样选 pair

以 IC02 为例：空仓时只看当天02档对应的实际合约及其因子；越界则与 IC_spot 反向开仓。成交后锁定实际代码和整数手数，直到它的真实到期日，不因它变成01/00而换月，不因其他组动作改变手数。到期双平后再从当时02档寻找信号。一个组任一时点最多持有这一组实际期现 pair。

普通历史分位使用今天所在档位此前60交易日的**年化基差**，历史上该档位可以对应其他实际合约；分位回归使用同品种前60交易日各期限的年化基差对剩余自然日拟合条件分位。回归的样本仍跨期限，账户和交易完全独立；它不回归未来收益。因子定义、LP、q网格和缺失规则沿用 [TERM_STRUCTURE](TERM_STRUCTURE.md)。

高尾部空期货、多指数，低尾部反向。IF/IH每手配300反向指数单位，IC/IM配200，指数乘数1。各组自己持有、成交、收费和占用保证金；即使两个组持相同合约或相反指数，也不跨账户抵消。每组默认1000万元、每腿目标 .495、保证金100%、手续费每腿每边万三，下一交易日真实close执行，分红显式D=0。指数为合成现货单位，未计真实ETF跟踪、借券融资或现金派息。

跨期只比较01−03的年化历史分位，锁定当时两份实际合约，任一到期双平后重新寻找。年化为 `100*(F01-F03+D01-D03)/F01*365/(T03-T01)`；期现仍按各自T年化。条件期限分位回归比较目前用于期现。

报告保留16条期现曲线。品种汇总只把该品种四份独立权益相加、用四份本金计算CAGR和回撤，属于展示汇总，不反过来共享资金或指数净额。不能平均四条回撤替代合计权益的回撤。

## 已授权的Z只读导入

用户本轮明确授权**只读**使用Z，不能修改源文件；DDB获取/VPN继续暂停。`readonly_import` 仅读取可信的原始日线close、同日实际映射、last_tradedate、contract_remain_days、指数spot_price和交易日历；不读取调整价替代成交价，不创建源端锁、日志、缓存或临时文件。

- 输出必须是本仓库data内的新目录，不能位于源目录或Z，不能覆盖旧快照。
- 逐文件读取字节并记SHA、大小/修改时间，读取期间变化则拒绝；批次结束再次检查。若仅其他品种或截止日后的内容变动，重读并精确核对所用四品种截止日及以前的值，任何所用历史变化都拒绝发布，保留未发布状态。
- 按同日四档映射转换成实际代码；同实际代码/日期冲突拒绝。到期日须跨行/档位一致，独立自然日必须与到期日差一致。
- 历史挂牌参考由完整四档成员首次出现和前一交易日完整排除证据重建，记录来源与证据日；不是按到期月份猜日期。与已有明确挂牌/到期参考重叠时必须一致。
- 已有冻结注册行情在同一单元优先，Z源只补缺；记录每格来源和重叠差异，绝不跨日填价。新源不自动覆盖已有非空值。
- Z项目的 `project_declared_time_v1` 口径按T收盘后使用；已有注册源发布时间未知仍单独标记。两种来源和重叠审计均保留，不能冒称全库均已取得原始发布档案。

产物为 `daily_close.parquet/contracts.parquet/days_to_expiry.parquet/calendar.csv/cell_sources.parquet/overlap_conflicts.parquet/import_manifest.local.json`。新快照source_id明确包含授权导入来源，配置必须同时声明 `allow_readonly_z_import=true` 和 `source_manifest_path`；读入核验清单、来源及所有使用文件SHA。默认不放行；直接Z运行路径及旧backfilled/excluded混合目录继续拒绝。独立因子产物重载不要求原Z文件仍在线。

```powershell
python -m dashboard.backtest.readonly_import --source Z:/Project_data/future_investment/data --output data/market/index_futures/backtest/NEW_SNAPSHOT --primary-config pure_registered.local.json --start 2023-07-01 --end 2026-10-14 --authorize-readonly-z
```

输出 `data.local.json` 是data段，加入本机job即可；旧纯来源数据保持原位。当前本机新快照覆盖2023-07-03—2026-10-14，795交易日、172实际合约参考；重叠5984格无价格冲突。2023年数据暖启动后评估从2024年第一个交易日2024-01-02开始。Z指数spot_price仅至2026-07-08，已有注册指数补到2026-10-14；不能把期货更晚的尾段当作两腿均已齐备。

## 调用与配置

完整可调参数与批次复用见 [PARAMETER_TUNING](PARAMETER_TUNING.md)。`slot_study`保留预设对照矩阵，逐函数独立窗口、跨期分母、阈值、费用等自由调节可直接使用标准 `workflow factor/cta/run/tune`，不需要改计算或执行代码。

模板 [slot.config.example.json](slot.config.example.json) 的CTA为单独02档；用 `workflow factor/cta/run` 可单独运行此档四品种，factor.roots仅选IC时就是IC02一组。四段配置仍独立，资金/费用在backtest，方向/权重在cta，窗口/回归参数在factor，路径/授权在data。

```powershell
python -m dashboard.backtest.slot_study --config slot.local.json --output outputs/backtest/NEW_FIXED_STUDY
python -m dashboard.backtest.slot_report --study outputs/backtest/NEW_FIXED_STUDY
```

`slot_study` 是明确的实验矩阵：复用一次保存的原始因子，逐档生成普通历史分位和条件分位回归的CTA，再增加历史分位跨期。默认两阈值，可 `--thresholds .9`；每腿权重、方向和变换从cta内部参数读取，资金/费用从backtest读取，各case保存最终完整配置。两阈值共18个case、72个独立账户；16/4是每种方法、每个阈值各自的账户数，不把不同策略互相加总。

`--no-render` 先完成数值，`slot_report` 只读保存产物，不读原始行情或重算因子。输出包括：

- `product_comparison.csv`：四品种各自CAGR/回撤，两方法、两阈值；只汇总四份独立本金。
- `slot_comparison.csv` / `account_metrics.csv`：16组分别比较及4跨期组的完整指标。
- `actual_pair_legs.csv`：按组别、方法、阈值、实际合约逐腿的毛PnL、费用、净PnL和期末状态。
- `pair_comparison.csv`：按同组同实际合约对齐两方法；未交易表示零贡献，不是缺价填零。
- `returns_*.png/pnl_*.png/legs_*.png`：16格收益、PnL、两腿贡献；`calendar_returns.png` 为4跨期；`pairs_latest_16.png` 为期末实际pair。
- `report.html`：离线切换方法/阈值、独立组、日期和实际合约；展示两腿表格、持仓和PnL。无CDN。

`future_pnl/hedge_pnl` 已各自扣费，二者相加等于net_pnl；`future_gross_pnl/hedge_gross_pnl` 未扣费，减两腿各自费用后才等于net_pnl。单个合约的贡献没有重复分配一份独立本金，不把贡献伪报为独立CAGR。

逐日检查一个期现组最多一份实际期货、跨期最多两份；实际手数不因换档改变，等价数量和为零，成交严格晚于信号，逐pair盈亏/费用/保证金与账户对账。保存因子重新生成全部权重逐单元一致，改CTA不改变原始因子。

真实快照、配置、数值及图表均只留本地忽略目录，不随源码发布。公司现场仍待运行。
