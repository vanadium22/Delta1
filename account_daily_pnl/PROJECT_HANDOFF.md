# PnL 项目交接

2026-11-20 · 三账户场内持仓、日盈亏和收益统计

## 新对话从这里开始

在 `P:/project/swhy/Delta1/company-apps-worktree` 的 `codex/company-apps` 分支继续。读本文件、[操作说明](README.md) 和 [账户收益接口](series.py)。公司电脑的验证和本机验证分开记录。公司已确认 2026-11-18 持仓，并反馈此前用 Wind 下过一遍行情。本机的历史包和收益样本截止 2026-11-18，公司最近的有效交易日应以其实际输出为准。

第二步是在第一步账户收益上做新增统计。先按该对话的业务目标和统计口径选取数据，随后接入已有收益接口。三个账户的成交处理、手续费和权益计算已由第一步负责。现有 Git 代码及回归测试可作为基准。

## 第二步已接入策略台合约收益

入口为 `python -m account_daily_pnl.strategy_pnl`，运行前复用日报模块同步并核对前一交易日。手动下载和历史回放命令见 [操作说明](README.md#第二步--策略台合约收益)。结果按「策略部交易台」原始明细汇总股指期货、全部 ETF、个股和四指数 ETF 子集，并保留起始日小计。四指数口径为上证50、沪深300、中证500和中证1000。收益为日报结算货币的资产和利率收益，使用源表符号。

本机正式 2026-11-18 样本已核验。手动目录的日期核对与已有同步器的隔离验证覆盖新旧日报，实际公司公盘仍需在公司环境验收。后续做合并归因时沿用第一步接口，检查报告日覆盖和所需字段完整度。

## 第二步的数据入口

完整运行后读取仓库输出根下的 `account_daily_pnl/account_daily_pnl.json`，默认是 `outputs/account_daily_pnl/account_daily_pnl.json`。从仓库根目录可这样读取，示例日期需替换为实际统计日。

```python
from pathlib import Path
from account_daily_pnl.series import SERIES_FILENAME, load_series
from shared_data.paths import DataPaths

paths = DataPaths.for_repo(Path.cwd())
series = load_series(
    paths.export("account_daily_pnl") / SERIES_FILENAME,
    required_through="2026-11-18",
)
```

| 字段 | 第二步使用口径 |
| --- | --- |
| `schema_version`、`baseline_date`、`through`、`currency` | 当前版本为 1，基准是 2025-12-29 收盘，币种 CNY。显式传 `required_through` 来校验截止日。截止日匹配后仍要检查所需列的数据完整度。 |
| `trading_date`、`account_id` | 唯一主键。每个交易日为 `2602`、`5526`、`5524` 和 `total` 四行。按账户加总时只取前三个账户，`total` 可用于交叉核对。 |
| `net_pnl`、`trade_net_pnl`、`equity_net_pnl`、`fee` | 主口径净盈亏、成交估值净盈亏、权益法净盈亏及流水费用。净盈亏已经计入适用费用。用 `pnl_source` 判断主口径，`equity_source` 辅助区分结算单与模型。 |
| `opening_equity`、`closing_equity`、`net_external_flow` | 期初、期末权益和当日外部净资金流。读取时关注 `equity_source` 和 `status`，特别是缺少资金确认的日期。 |
| `daily_return`、`since_baseline_return`、`ytd_return` | 十进制小数收益率，例如 `0.01` 表示 1%。累计收益率按逐日收益率连乘，年内序列在新年重置。 |
| `since_baseline_net_pnl`、`ytd_net_pnl` | 截至当日的基准以来及今年累计金额。任意区间的逐日合计使用 `net_pnl`，并检查期间缺项。若要用累计端点相减，在 Excel 的累计盈亏来源列核对两个端点口径。 |

金额为人民币元的十进制字符串，使用 `Decimal` 读取。收益率也是十进制字符串。`null` 是缺数据或口径待确认，保留给第二步的完整度处理，数值 0 表示真实零值。单日模式只出对应日报，完整日更才更新 JSON、历史 Excel 和两张收益图。人工复核可使用 `逐交易日统计.xlsx` 和 `场内账户_YYYY-MM-DD.xlsx`。

## 日常运行和目录

- 公司 Git 根目录为 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`。更新后双击根目录的 [收益统计.cmd](../收益统计.cmd)。默认使用公司 `D:/conda/envs/swhy_delta1/python.exe`，按北京时间统计前一个交易日。漏跑、断网或中断后再点同一入口即可补跑。
- 复查固定日期可执行 `.\收益统计.cmd --only-day --date 2026-11-18`。加 `--wind-log-detail` 可查看本次估值中复用、新下载、仍待补的标的、交易日和价格字段。
- 默认数据根为 `data/account_daily_pnl/`。其中 `inputs/` 放基准、资金、结算权益和本机加密登录设置，`flows/` 是原始 BCT 流水，`snapshots/` 是 BCT 估值快照，`wind/` 是按交易日保存的 Wind 报价。真实数据与凭据均保存在本地忽略目录。
- `daily_cache.json` 保存日终持仓和可复用估值，`download_state.json` 记录下载截止，`reports.json` 记录报告指纹。首次运行建立缓存后只续算新增和受影响日期。改过历史流水会从该交易日重建持仓，改价或资金输入会更新受影响估值。
- 日常结果在 `outputs/account_daily_pnl/`，包括单日、历史、今年和图表。公司有已有 Wind 报价时，新旧运行使用同一数据目录即可复用。定时是可选入口，详见 [操作说明](README.md)。

## 源码导航

| 文件 | 职责 |
| --- | --- |
| [__main__.py](__main__.py)、[daily_cache.py](daily_cache.py) | 日更、断档补跑、按交易日续算及结果发布。 |
| [baseline.py](baseline.py)、[sources.py](sources.py)、[seed.py](seed.py) | 基准导入、BCT 归档与历史包。 |
| [ledger.py](ledger.py)、[prices.py](prices.py) | 持仓、费用及日盈亏，BCT 估值与 Wind 补价。 |
| [performance.py](performance.py)、[series.py](series.py)、[charts.py](charts.py) | 账户统计、第二步数据接口以及收益图。 |
| [setup_daily.py](setup_daily.py)、[test_account_daily_pnl.py](test_account_daily_pnl.py) | 公司工作台可选登记和专项回归。 |

## 已验证及待核事项

- 基准日是 2025-12-29 收盘。2602 在 BCT 中映射为 5102，5526 使用基准持仓，5524 初始空仓。日报从 2025-12-30 起。文件名为 2026-11-18 的一份附件快照实际为 2025-12-29，归档以表内交易日为准。
- 本机历史包截至 2026-11-18，有 213 个交易日流水、206,329 条原始记录、12 份快照和 4 份基准资料。账户收益 JSON 的 852 行已逐行与 Excel 核对；同一输入首次建缓存及续算的 JSON 一致。15 项专项测试通过，含跨期补跑、历史更正重算、Wind 缓存及日志。
- 手续费复核覆盖 213 天，流水 ID 和成交 ID 跨日重复为 0，逐日费用与原始 `fee` 一致。2026-11-18 的 28,397.24 元全部来自 2602 股票成交。该批 BCT 的 5526 和 5524 期货 `fee` 为 0，期货结算单用于核对是否另有费用。
- 公司用户确认 2026-11-18 持仓，并反馈盈亏看起来大致正确。账簿级对账差异保留在日报检查中，两项可追溯到基准来源，另有无交易账号的流水。本机原始校验样本和对账证据位于 `local_artifacts/validation/2026-11-19/account_daily_pnl/`。
- 本机缺 WindPy，2026-11-19 的 BCT 实测连接超时。公司如下载了更新行情，以其 `wind/` 文件和实际导出的 `through` 为准。11 月 18 日的本机样本仍缺 11 月 17 日 44 个报价，缺项以 `null` 和状态保留。
- 正式权益仍依赖结算单与确认的外部资金流。需要做严格收益率或拓展资金相关统计时，向用户核实三账户资金来源、覆盖期及期货结算价口径。运行返回 2 表示有日报但目标日仍有盈亏缺项。
