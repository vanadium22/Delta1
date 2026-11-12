# 下一对话：公司复测与看板验收

2026-11-12，统一分支codex/company-apps，实施基线95869c2，最终运行版本以Git HEAD/远端为准。指标页数值按原行情计算更新，图像在页面激活期间每30秒重画并标图像更新时间；缺项显示原因。概览突出00–03，去掉概览上的较昨基差变化；20/60分位并列同窗均值/中位数及日期，越接近两端越高亮；概览新增四品种期限/成交/持仓，指数页新增行业权重变化，ETF页新增全部现有订阅的总览表。

490项独立完整回归通过，123.232秒（含加载），无跳过，ResourceWarning作为错误；原469项重跑，新增21项。 本地Qt截图为合成数据，不等于公司验收。

## 可复制提示词

请继续Delta1公司看板。先完整读本文件和docs/INDICATOR_PAGE_PROPOSAL.md，再读相关AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE和COMPANY_SYNC。统一工作区P:/project/swhy/Delta1/company-apps-worktree、分支codex/company-apps，核验Git/远端/worktree/status/diff并保护现有工作。

先核验我新的安全反馈包：检查Complete、两次Overview与同一运行排空、app_reports.matching_profile[].indicator_analysis的选择/当前F/S/D/T/统计/缺项及实际源时间，区分实时与带日期的收盘参考；不要把旧包当本轮已验收。核对指标Z/分位、30秒图像、四品种概览期限成交持仓、20/60同窗统计、行业权重变化及ETF总览。默认Overview诊断离线，必要实施、测试和精确提交推送授权持续；本地模拟与公司实测分开。

保留原数据、配置、凭据、Excel、其他worktree、四份受保护提示词及APP_RELEASE.backtest。DDB不暂停，沿用192.168.198.77:8904及凭据，已有jc数据隧道可达时复用；实时VPN手动。原逐日D、简单年化、连续四档20/60保持，历史缺D暂0仅派生、当前D不补0、冲突不填；32项/A02继续暂停。Overview诊断默认离线，不强杀、删锁、重映射Y、reset/clean、全量stage或强推。

## 最新已审公司包：不完整

新公司包20261111_154729_881_safe_160539_083_91d394e8.zip，8886字节，SHA256 cbb1e517a16a39a252a69690bfe0ef4f4b522dcf456df8f1f84c2834fb38c262；95869c2、7份JSON且CRC正常，但Complete=false，开窗与关闭后overview.json均缺失，缺少同次安全排空证据。两次诊断均报System.Management.Automation.RemoteException/NativeCommandError，preflight退出0；没有原始stderr，不能据此确定Z/分位为何为空、DDB状态或同次关闭完成。

本轮开发机对192.168.198.77:8904做一次3秒TCP探测，3022毫秒超时；未使用凭据、修改VPN或查询数据，只表示开发机当前不可达，不覆盖旧包中的公司端连通证据。

旧b7d5d55公司包独立证实11-10四指数和16实际期货收盘、16个20日与16个60日分位，日期为corroborated_live_session推定；DDB existing_tunnel/tcp/authenticated/query_partial，仍缺16期货OI及12 ETF收盘；同次安全关闭2.731秒。旧包不验证95869c2或本轮新页。

## 公司原入口

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900
```

按APP_COMPANY_TEST操作：必要时补一次所选窗口，待计算后保留指标页获取开窗Overview，正常关闭等排空后取关闭Overview，回传最后_safe_*.zip。脚本不替用户点击、不操作实时VPN。11-10专项可附加-ExpectedCloseDay 2026-11-10；真实最新完成日仍按源和交易日历单独核验。

四份受保护提示词不修改/提交：dashboard/INDICATOR_REDESIGN_ANALYSIS.md、NEXT_INDICATOR_REDESIGN_PROMPT.md、NEXT_PRESENTATION_APP_PROMPT.md、NEXT_UI_SIMPLIFICATION_PROMPT.md。APP_RELEASE.backtest原对象/序列化块、七份唯一SHA归档/MANIFEST保留；Y按确认年份目录与Sheet1!B1，不猜拼或重映射。
