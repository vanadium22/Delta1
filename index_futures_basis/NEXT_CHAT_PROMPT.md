# 股指基差简报交接 · 2026-11-20

接续 `index_futures_basis` 的简报工作。当前功能版本 `b0e8483` 已推送至 `codex/company-apps`。本机发布工作区为 `P:/project/swhy/Delta1/company-apps-worktree`，用户原项目目录为 `P:/project/swhy/Delta1/project/index_futures_basis`。进入下一轮先核对分支、最新提交和工作区状态，读取 [项目交接](PROJECT_HANDOFF.md) 与 [每日生成说明](recent_brief/DAILY_GENERATION.md)。以最新需求和现有实现为准，保留其他模块的并行工作。

## 已确认版式和口径

- Word/PDF 共11页。首页是综合观察，随后是一页四品种16合约总表、一页8行跨期表，最后8页依次展示单合约年化、跨期年化、持仓成交和绝对基差。**仅前面的合约总表和跨期表**用低饱和蓝灰、灰紫、暖灰、无绿色的配色。后续图片、卡片、成交柱和分位表沿用用户确认的原示例配色。
- 前表用于核对收盘指数、连续档位、实际合约、期货收盘价、分红、去分红基差、年化和到期日。表内数值两位小数、天数为整数。去分红基差为 `F + G − S`。跨期用 `02−01`、`03−02`，远月减近月，按实际到期日间隔和现货年化。两腿原始合约和日期保存在 `current_tables.json`。
- 图上卡片保留名称、当前值、日变。年化曲线画01–03，00保留于当前值及统计表。逐档30/60/120交易日统计格列分位、年化均值和中位数，历史窗口排除当天，覆盖不足留空。剩余天数 `T ≥ 1` 参与年化，成交和持仓按四合约分别汇总。
- 首页按年化基差、持仓成交、跨期结构三段生成。各品种分别给出00/01、02/03和四档的当前等权年化均值，以及该组在前60个交易日同组每日均值分布中的分位。近期变化避免把换月造成的跳变描述成基本面变化。跨期描述延续用户原稿的整体结构、绝对价差和年化重点。

## 已验证的结果

- 本机通过67项简报及13项桌面测试，独立复核72组窗口统计，并逐页检查了Word与PDF各11页。后续四张图与原示例的颜色集合一致。桌面回归使用项目内临时目录避开Windows重定向Temp的改名错误。
- 新版样例文件夹为 `P:/project/swhy/Delta1/project/index_futures_basis/exports/recent_brief/2026-10-15/table_palette_20261120_v9`。里面有 `股指基差简报.docx`、`股指基差简报.pdf` 和核对CSV/JSON。样例使用2026-10-15行情与2026-09-18分红，用于版式和统计验证。验证记录在发布工作区的 `local_artifacts/validation/2026-11-20/basis_muted/verification.json`。

## 下一步做公司实测

1. 公司在原仓库根目录执行 `git pull --ff-only`，重开基差App，在「报告与记录」点「一键生成简报并打开PDF」。公司 Wind、最新本地分红 Excel 和工作自动化实际运行待现场验收。
2. 收到公司版结果后先看实际行情日、各品种最新行情日和分红业务日。用 `run_manifest.json` 的 `as_of`、`latest_by_root`、`market_refresh`、`dividends.snapshot_date`、`dividends.path`、`dividends.age_calendar_days` 复核。程序按 Excel 的 `Sheet1!B1` 在本地输入及看板落地缓存中选最新业务日。核对失败时保留批次和日志，结合前表、`current_tables.json`、`dividend_adjustment_audit.csv` 找到具体品种和档位。
3. 工作自动化工作台的「定时子任务」使用现有 `start_recent_brief_daily.cmd`。已有登记沿用原时间和启停，新登记默认北京时间工作日16:10。现场可运行一次并核对任务日志和 `exports/recent_brief/latest.json` 对应的新批次。正常日更需公司 Wind 已登录、工作台后台运行及本机 Python 配置可用。
4. 用户反馈版式或数值问题后，再修改对应模块。前表在 `table_layout.py`、前表配色在 `theme.py`、图片在 `card_charts.py`、文档分页在 `documents.py`、首页总结在 `narrative.py` 和 `overview.py`，都位于 `recent_brief/`。已有图替换可用「修正图片后重排Word/PDF」。
