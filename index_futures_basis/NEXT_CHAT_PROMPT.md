# 股指基差简报交接 · 2026-11-20

最新版已改按实际合约和截止时刻向前匹配历史分红，同批生成两个13页版本，跨期绝对价差紧随跨期年化。历史Excel放公共inputs或其history子目录，下一批自动识别。以项目交接最上方及每日生成说明为准，下面旧版11页及最新单快照记录为前序。

接续 `index_futures_basis` 的简报工作。当前功能以 `codex/company-apps` 的 Git HEAD 为准。本机发布工作区为 `P:/project/swhy/Delta1/company-apps-worktree`，用户原项目目录为 `P:/project/swhy/Delta1/project/index_futures_basis`。进入下一轮先核对分支、最新提交和工作区状态，读取 [项目交接](PROJECT_HANDOFF.md) 与 [每日生成说明](recent_brief/DAILY_GENERATION.md)。以最新需求和现有实现为准，保留其他模块的并行工作。

## 已确认版式和口径

- Word/PDF 共11页。首页是综合观察，随后是一页四品种16合约总表、一页8行跨期表，最后8页依次展示单合约年化、跨期年化、持仓成交和绝对基差。**仅前面的合约总表和跨期表**用低饱和蓝灰、灰紫、暖灰、无绿色的配色。后续图片、卡片、成交柱和分位表沿用用户确认的原示例配色。
- 前表用于核对收盘指数、连续档位、实际合约、期货收盘价、分红、去分红基差、年化和到期日。表内数值两位小数、天数为整数。去分红基差为 `F + G − S`。跨期用 `02−01`、`03−02`，远月减近月，按实际到期日间隔和现货年化。两腿原始合约和日期保存在 `current_tables.json`。
- 图上卡片保留名称、当前值、日变。年化曲线画01–03，00保留于当前值及统计表。单合约统计30/60/120个交易日，跨期另增180个交易日。各格列分位、年化均值及中位数，排除当天，覆盖不足留空。跨期年化图与绝对价差子图显示近六个自然月。剩余天数 `T ≥ 1` 参与年化，成交和持仓按四合约分别汇总。
- 首页按去分红年化、跨期结构、持仓成交写。年化列近月和远月均值、远月60日分位，再归并近7个交易日次月同向变化。当月到期明确写次月值，原三组证据均归档。跨期先写当前整体方向，再各选一个绝对和年化重点，优先引用完整180日显著偏离。量仓先写逐品种方向再写总持仓高位。换月样本标记，不能把换档跳变描述成基本面变化。

## 已验证的结果

- 本机通过70项简报及13项桌面测试，独立复核跨期32组统计（含新增180日8组），并逐页检查了Word与PDF各11页。历史样例的半年图覆盖122个交易日。桌面回归使用项目内同卷临时目录。
- 新版样例文件夹为 `P:/project/swhy/Delta1/project/index_futures_basis/exports/recent_brief/2026-10-15/half_year_calendar_20261120_v2`。里面有 `股指基差简报.docx`、`股指基差简报.pdf` 和核对CSV/JSON。样例使用2026-10-15行情与2026-09-18分红，用于版式和统计验证。验证记录在发布工作区的 `local_artifacts/validation/2026-11-20/basis_half_year/final/verification.json`。

## 下一步做公司实测

1. 公司在原仓库根目录执行 `git pull --ff-only`，重开基差App，在「报告与记录」点「一键生成简报并打开PDF」。公司 Wind、最新本地分红 Excel 和工作自动化实际运行待现场验收。
2. 用户提供的11月20日人工改稿已用于学习总结风格，其抬头显示旧分红。收到公司重新生成的完整批次后，先看实际行情日、各品种最新行情日和分红业务日。用 `run_manifest.json` 的 `as_of`、`latest_by_root`、`market_refresh`、`dividends.snapshot_date`、`dividends.path`、`dividends.age_calendar_days` 复核。程序按 Excel 的 `Sheet1!B1` 在本地输入及看板落地缓存中选最新业务日。核对失败时保留批次和日志，结合前表、`current_tables.json`、`dividend_adjustment_audit.csv` 找到具体品种和档位。
3. 工作自动化工作台的「定时子任务」使用现有 `start_recent_brief_daily.cmd`。已有登记沿用原时间和启停，新登记默认北京时间工作日16:10。现场可运行一次并核对任务日志和 `exports/recent_brief/latest.json` 对应的新批次。正常日更需公司 Wind 已登录、工作台后台运行及本机 Python 配置可用。
4. 用户反馈版式或数值问题后，再修改对应模块。前表在 `table_layout.py`、前表配色在 `theme.py`、图片在 `card_charts.py`、文档分页在 `documents.py`、首页总结在 `narrative.py` 和 `overview.py`，都位于 `recent_brief/`。已有图替换可用「修正图片后重排Word/PDF」。
