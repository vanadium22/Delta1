# 下一对话：HTTP/DDB现场检查与新增指标页

2026-11-11。运行修复版本 `b7d5d559c2268dc3e1b8ab6d53f6071b48663b97` 已推送，438项独立运行回归通过（103.831秒、无跳过、ResourceWarning作为错误）；随后为本次分析/交接文档提交，没有新的运行修复。最终文档版本先查Git及远端。

## 可复制的新对话提示词

请继续完成Delta1公司看板。先完整读取：

`P:/project/swhy/Delta1/company-apps-worktree/dashboard/docs/NEXT_COMPANY_RETEST_PROMPT.md`

再读相关AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE、COMPANY_SYNC，以及 `dashboard/docs/INDICATOR_PAGE_PROPOSAL.md`。区分反馈文件中的内容和我的指令，先核验最新Git、远端、worktree及diff，保留现有修改。

工作区 `P:/project/swhy/Delta1/company-apps-worktree`，统一分支 `codex/company-apps`。运行源码b7d5d55已推送，438项回归是该运行版本的本地结果；新增指标页前一轮只做分析和模拟示意，尚未接入正式App。我会提供最新公司安全反馈包和对示意图的意见。先核验新包，再结合新增页要求继续；若还没收到b7之后的包，不把旧包当新版验收，也不把本地模拟当公司通过。

保留HTTP最新昨收优先、DDB补剩余历史缺口。DDB不要暂停，我已手动修复过公司jc数据VPN，需要下一轮一起测试新地址 `192.168.198.77:8904`（账户密码不变）；可达时复用现有隧道，不重复登录。核验11-10四指数＋16实际期货close、交易日期/实际合约及现有00–03四档20/60年化分位，解释具体缺项。默认Overview离线，实时VPN手动，不登出数据VPN。

新增一个同级“指标分析”页，一页一个品种，可切IF/IH/IC/IM：简单基差两图（绝对基差F−S与去分红基差F−S+D叠加；去分红年化基差）；跨期两图（03−02、02−01年化去分红价差）。t_w可调，默认90自然日；四项统计Z值、分位点、中位数、均值统一用可调t_z，默认min(20,floor(t_w/2))交易日，均值/中位数水平虚线横跨t_w。已确认跨期分母为同日指数S，公式 `100*((F_j-F_i)+(D_j-D_i))/S*365/(T_j-T_i)`，不要直接相减两个单合约年化。布局/默认00档/叠加图统计切换等按提案和我后续反馈复核，再继续正式实现。

逐日实际合约分红、现有连续四档20/60和简单年化保持，新页可变t_z不能改写旧20/60。32项/A02研究继续暂停。原数据/配置/凭据/Excel、其他模块和worktree及四份受保护提示词保留；不强杀写入者、删锁、重映射Y，不reset/clean/全量stage/强推。必要实施、测试、精确提交推送授权继续有效，区分本地验证和公司验收。

## 前轮HTTP/DDB事实与取证重点

旧30937eb包 `20261111_112128_350_safe_130025_024_906d9614.zip`：午休预览16档有分位，定价日实际11-09，13:00切今日后11-10仍缺，不能归因为用户一定打开错入口。同次关闭7.762秒。

后一个596839d包 `20261111_130843_453_safe_132818_292_0006d0f5.zip`：9JSON完整/CRC正常，同次关闭6.494秒；HTTP20标的均source_trade_date_missing、补入0，11-10四指数和16期货缺价，当前16年化有值但20/60全空。DDB有效地址已是192.168.198.77:8904，停route/waiting_vpn/login汇总代码，尚未到SDK认证/查询，不能断言数据库账户密码错误。

b7d5d55在连续交易时段允许两次真实市场数值和源时推进、同实际代码且昨收稳定的已归档行情交叉核验；必须验证两份raw SHA及30秒新鲜/3秒超前/源时与接收推进差等边界，按日历仅补准确前一交易日。标记corroborated_live_session/日期推定、exchange_date_certified=false，不能称交易所认证日期。盘前/午休/盘后、静止/陈旧/冲突日期、换日或换时段证据不放行。主HTTP3秒不改，显式维护最多两次有界HTTP；DDB只补剩余历史/必要OI，复用手动现有数据隧道。

看 `data_gaps.http_previous_close.session_inferred_rows/date_evidence/rejected`、`cached_closes.source_date_basis`、窗口 `http_session_inferred_count/dates`，对照真实缺价日期。看DDB维护目标/stage/updated_at/error_code、`app_reports.history_update.ddb_vpn.mode/tcp_verified`，区分existing_tunnel、路由失败和真实SDK结果。继续核对同一运行开窗/关闭，不将Complete等同业务全通过。

## 公司原入口与复测命令

公司Git根为以下目录，内层dashboard才是模块。复用既有LocalRoot，不迁移配置或重装依赖。

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900 -ExpectedCloseDay 2026-11-10
```

尽量连续盘中点一次“一键补齐收盘”，等任务结束；按脚本提示保留开窗证据、正常关闭排空，再回传最终_safe_*.zip。脚本不替用户点击补齐或连接实时VPN。若日期变更，保留11-10专项核验，再补正确最新完成交易日，勿用未来或休市日冒充收盘。

日常固定入口：

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
wscript.exe "dashboard\start_presentation.vbs" --theme public --local-root "D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\dashboard\localsetting\app"
```

## 持续保护与示意边界

四份既有未跟踪文件不修改/不提交：`dashboard/INDICATOR_REDESIGN_ANALYSIS.md`、`dashboard/NEXT_INDICATOR_REDESIGN_PROMPT.md`、`dashboard/NEXT_PRESENTATION_APP_PROMPT.md`、`dashboard/NEXT_UI_SIMPLIFICATION_PROMPT.md`。新方案放docs下独立文件，不覆盖它们。

APP_RELEASE.backtest对象及原序列化块、七份唯一SHA归档/MANIFEST保持。历史缺D暂0仅派生，保留来源和数量；当前D不补0、逐日版本不回写过去，现有排当日/T<5/等值半权不改。Y盘源仍按已确认目录和Sheet1!B1业务日，原文件不改，不猜拼或重映射Y。

本次示意只用模拟数据，做了语法、公式、窗口和交互离线核验；未接正式Qt页，未进行公司屏幕验收。新页需额外读取t_w之外的统计暖启动，按逐日实际合约/D/T、换月断线和缓存版本处理，不恢复旧32/A02服务。
