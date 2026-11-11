# 下一对话：指标页公司复测与真实源缺项

2026-11-11，39760f0后已正式实现Qt“指标分析”，最终运行版本先核验Git/远端。469项独立完整回归通过，105.841秒（含加载），无跳过，ResourceWarning作为错误；原438项全部重跑，新增31项指标页回归。 证据local_artifacts/validation/company_20261111_indicator_page；本地截图为合成输入，不当公司新页验收。

## 可复制提示词

请继续完成Delta1公司看板。先完整读取本文件和docs/INDICATOR_PAGE_PROPOSAL.md，再读相关AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE和COMPANY_SYNC。统一工作区P:/project/swhy/Delta1/company-apps-worktree、分支codex/company-apps，核验Git/远端/worktree/status/diff，保留现有工作，最终版本以Git为准。

本轮新增指标页已经接入正式App：一品种切IF/IH/IC/IM、基差两图及03−02/02−01跨期两图；默认00档，右图不随基差档位改变。四项统计统一t_z、排定价日，均值/中位数水平虚线横跨t_w，跨期分母同日指数S。t_w默认90且10–365自然日，t_z默认min(20,floor(t_w/2))且2–120交易日，手动不随t_w覆盖。历史逐日实际合约/D/T、换月/缺项断线、图外统计暖启动与独立版本LRU；原固定20/60不改。具体公式和口径看实现文档。

先核验我提供的新安全包，不能把下面b7旧运行包当新页验收。公司新页复测应停留指标分析页，等计算后采开窗Overview、正常关闭等排空再采关闭后Overview，app_reports.matching_profile[].indicator_analysis应有当前选择及统计摘要；默认Overview不隐含联网。必要实施、测试、精确提交推送授权持续；区分本地回归和公司真实验收。

DDB不要暂停，新地址192.168.198.77:8904、账号密码/TLS沿用，已有jc数据隧道可达时复用，不重复登录。实时VPN手动。原数据/配置/凭据/Excel、其他模块/worktree和四份受保护提示词保持；逐日实际D、简单年化、四档20/60保持，历史缺D暂0仅派生、当前D不补0、真实冲突不填；32项/A02继续暂停。不强杀写入者、删锁、重映射Y，不reset/clean/全量stage/强推。

## 最新已审公司包（b7d5d55，尚无新指标页）

20261111_141737_345_safe_143604_770_d37cd87a.zip，119408字节，SHA256 4bd430f9185aba8faf62412f436898fd80bc65290397db3c5ddc417b5dc3e874。9JSON/CRC正常、Complete=true/MissingReports=[]；同f80a70e运行，14:34开窗、14:35关闭，2.731秒/complete/waiting=[]/sqlite_committed；旧5cb076e的7.623秒排除。

11-10四指数＋16实际期货close最终齐备，HTTP首轮18，IF2612/IH2706源时未推进被拒后经主采集补入；最终20行source_date_basis=corroborated_live_session、日期推定，源会话11-11，不能称交易所认证。安全包无完整双raw，不声称本轮独立检验raw SHA。页面引擎预览16年化、16个20日及16个60日分位均可用，公式同输入复算一致；历史专用continuous_annual.percentile为空仅因没传当前比较值。当前D11-06，20日暂0=0，60日暂0共412样本行，真实历史D仍缺。

DDB生效新端点，existing_tunnel/tcp_verified=true/authenticated=true/query_partial，真实补入0。最后28行计划=16期货OI+12ETF close；14:18:09任务pending_close_rows=14早于两项后续HTTP补价，不当最终价格缺口。本机15:06有界TCP探测仍超时、未认证/查询，未改VPN/配置，不覆盖公司成功证据。

## 公司原入口

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900 -ExpectedCloseDay 2026-11-10
```

更新后按APP_COMPANY_TEST验证新页，必要时点一次“补齐所选窗口”，等结束并保持该页取开窗证据，正常关闭排空后回传最后_safe_*.zip。脚本不替用户点击、不操作实时VPN。11-10专项保留，若已进入更晚完成日还需准确最新交易日；HTTP昨收只补源会话准确前一日，不能冒充当天收盘。

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
wscript.exe "dashboard\start_presentation.vbs" --theme public --local-root "D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard\dashboard\localsetting\app"
```

四份未跟踪提示词不修改/提交：dashboard/INDICATOR_REDESIGN_ANALYSIS.md、NEXT_INDICATOR_REDESIGN_PROMPT.md、NEXT_PRESENTATION_APP_PROMPT.md、NEXT_UI_SIMPLIFICATION_PROMPT.md。APP_RELEASE.backtest原对象/序列化块和七份唯一SHA归档/MANIFEST保持；Y按确认年份目录与Sheet1!B1，不猜拼或重映射。
