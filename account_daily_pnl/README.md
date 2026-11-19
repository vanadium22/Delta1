# 三账户场内持仓与盈亏

## 公司只测一天

1. 在公司 Git 根目录执行 `git pull --ff-only`。
2. 把单独交付的 `account_daily_pnl_history.zip` 放到本目录，与 `test-yesterday.cmd` 同级。首次运行会核验并导入到本机的 `data/account_daily_pnl`。已下载文件按哈希复用。
3. 打开本机 Wind 终端并确认已登录。双击 **test-yesterday.cmd**。它回放基准以来的持仓，只导出前一个交易日的报表。默认报表位置为仓库根目录的 `outputs/account_daily_pnl/场内账户_YYYY-MM-DD.xlsx`。窗口会显示日期、回放进度和保存位置，按键后关闭。

本次历史包截止 2026-11-18。以后要复测该日，可以在本目录执行 `.\test-yesterday.cmd --date 2026-11-18`。使用 11 月 18 日包测试 11 月 18 日时，BCT 流水和快照均可本地读取，Wind 用于缺少的前一交易日价格。若测试日超过数据包截止日，则按以下日更方式增量下载。

启动入口复用公司已有的 `swhy_delta1` Python（默认 `D:\conda\envs\swhy_delta1\python.exe`），窗口首行显示实际解释器路径。程序依赖 requests、openpyxl 和时区数据。首次从原始 ZIP 直接导入旧版 XLS 时还需要 xlrd。如果 WindPy 装在另一 Python 里，把 `config.example.json` 复制到数据目录的 `inputs/config.local.json`，填写本机的 `wind_python` 解释器路径。

## 正式日更和中断补跑

- 双击 **start.cmd** 执行常规日更。可供公司计划任务调用的命令为 `start.cmd --no-pause`。需要下载 BCT 时，将本机已有可信 BCT 脚本路径配置到 `inputs/config.local.json` 的 `bct_script`，或用 `BCT_CREDENTIALS_SCRIPT` 环境变量指向脚本。也可使用本机环境变量 `BCT_USERNAME` 和 `BCT_PASSWORD`。凭据直接交给 BCT 登录，无需放进数据包。
- 以北京时间取当天之前最近的交易日。程序从基准起核对交易流水存档，缺几天补几天。历史快照只补已结束月份的最后交易日。正常日更自最近成功下载日恢复，停跑期间遗漏的交易日逐日下载快照、流水和生成报表。节假日和周末按 [交易日历](../dashboard/marketdata/trading_calendar.py) 跳过。
- `flows/`、`snapshots/`、`wind/` 分别保存按业务日命名的原始流水、BCT 快照和 Wind 缺价补录 Excel。BCT 的账簿和日期从接口校验，分页核对 `totalCount`。无成交的交易日保留有表头和零行元数据的有效流水文件。下载中断后，下一次运行复用已保存文件，继续缺项。源归档和正式报表逐文件原子写入。
- 全量日更会回放并更新每天的明细和 `逐交易日统计.xlsx`。同一份明细在输入和结果相同时复用。需要指定统计日时，从仓库根目录运行 `python -m account_daily_pnl --date YYYY-MM-DD`。`--only-day` 只写该天的报表，`--prepare` 只准备输入 Excel，`--no-download` 和 `--no-wind` 用于离线核验。

## 报表口径

| 内容 | 计算 |
| --- | --- |
| 持仓 | 从 2025-12-29 日终滚动，2602 使用 BCT 5102 组合、5526 使用基准、5524 从空持仓起算。期货用买卖方向加开平记多空两边。送转入数量，现金分红入盈亏。 |
| 单日盈亏 | 日终持仓价值减上一交易日持仓价值，加净卖出成交金额及现金分红，减费用。期货持仓价值和成交金额使用相同乘数。缺估值、无法归类的流水和异常开平在数据检查中列出，受影响的合计留空。 |
| 价格 | BCT `instrumentQuote` 优先，缺项按实际交易日向 Wind 查询。默认现货为 `close`，期货为 `settle`，核对公司 BCT 估值口径后可用 `wind_futures_field` 改为 `close`。跨来源的期货价格会提示核对。 |
| 总权益 | 确认的基准权益 + 期间净入金 + 累计盈亏。每账户填 `opening_equity` 及 `cash_flows_confirmed_through`（已核对入出金覆盖截至日）。通过 `cash_movements` 列入已核实的 `date`、`account`、`net_deposit`，出金用负数。 |
| 参考权益 | 基准表中的基金净值或本机配置值，加已登记资金流和计算盈亏，在资金覆盖或基准权益待确认时提供参考。5524 空仓不代表期初资金为零。 |

表内的期货名义额用于查看敞口。BCT 持仓快照按交易簿归集，报表的「数据检查」使用三个账户的净持仓与账簿快照对照，差异保留供核对。
