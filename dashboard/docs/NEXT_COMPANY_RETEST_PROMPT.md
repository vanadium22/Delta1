# 下一对话：公司同屏与指标连续更新复测

2026-11-12公司复测续改，统一codex/company-apps，实施基线da50685，最终运行版本以Git HEAD/远端为准。概览将每个指数、四个期货卡及该品种期限/成交/持仓图合为一行，1080p/125%中比例无需滚动；小窗口可滚动以保持可读。ETF总览增加蓝色表头、交替底色、涨跌/折溢价颜色并放大字号；指标图最新点加大。行业变化缺项显示可比失败原因，并在安全报告中保留每品种判断摘要；不把缺失权重伪造为零。

496项独立完整回归通过，136.744秒（含加载），无跳过，ResourceWarning作为错误；原490项重跑，新增6项。 本地离屏截图为合成数据，不等于公司新版本验收。

## 可复制提示词

请继续Delta1公司看板。先完整读取本文件及docs/INDICATOR_PAGE_PROPOSAL.md，再读取相关AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE和COMPANY_SYNC。统一工作区P:/project/swhy/Delta1/company-apps-worktree、codex/company-apps；先核验Git、远端、worktree、status与diff。

先核验我提供的最新安全包，同次开窗与关闭按同一report_path识别；检查app_reports的indicator_analysis及indicator_draw.timer_draws，比较相邻实际绘图时间、选择、源时、当前值、Z及分位，不能将历史快照或定时器设置当成公司连续绘图证据。核对index_industry_changes中IC/IM的可比失败原因、日期、分类覆盖和归档计数；不将未知值补0。检查四品种概览同屏、ETF表、指标末点及DDB/关闭。必要实施、测试、精确提交推送授权持续；本地验证与公司验收分开。

DDB不暂停，原凭据和192.168.198.77:8904沿用，可达时复用已有jc数据隧道；实时VPN手动。保留原数据、配置、凭据、Excel、其他worktree、四份受保护提示词、七份唯一归档及APP_RELEASE.backtest原块；逐日实际D、简单年化、连续四档固定20/60保持，历史缺D暂0只派生、当前D不补0、冲突不填；32项/A02继续暂停。Overview默认离线，不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

## 最新已审公司包

公司安全包20261112_100603_500_safe_103108_772_2f9c3359.zip，121515字节，SHA256 faa33f5818c8f3fbfabeeabb6a76cc0197ddbf2061d7d2ad0bcf2486fcbdcc6f，运行da50685；9份JSON/CRC正常、Complete=true/MissingReports=[]，同一f12c8a运行开窗、正常关闭3.355秒、waiting=[]，成分sqlite_committed。两次Overview与preflight均退出0、stderr为空。

开窗10:27:34应用了IC 03、t_w=90/t_z=20的盘中快照，F/S/D/T源时10:27:31。绝对基差/去分红/年化/03−02/02−01的Z分别为0.2756/0.5718/0.6992/0.6894/1.0607，分位分别为60/55/65/55/90%；用包内同输入复算各公式及Z一致。两次只读采样有32个行情源时推进，但运行指标摘要只有一个时点，因此不能从本包断言Z/分位持续变化或30秒实际重绘；分位按样本排序离散，不要求每笔行情均变化。

本次DDB维护有效端点192.168.198.77:8904、existing_tunnel/tcp_verified/authenticated、query_partial，插入0；10:07维护记录待补收盘24条和期货OI 16条，不等于最终四指数与16期货都缺收盘。HTTP缓存已核验11-11四指数及16实际期货共20条，均为corroborated_live_session日期推定；页面计算预览16个年化、16个20日及16个60日分位有值。20日历史D暂0为0行，60日396样本行暂0，不能称真实历史D已全。

包内IC/IM当前权重均存在、权重日期10-30，成分中分别49/148只缺行业分类；安全包未记录上次可比权重决策或归档内容，不能证明这两项缺分类就是图不显示的原因。新版本在运行报告与离线预览中记录比较状态、当前/前次日期、来源口径、归档扫描/不兼容计数及未分类数；仅对同口径可比快照计算，保留“待分类”，无可比数据留空。

## 公司原入口

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900
```

取开窗报告前在指标分析页保持同一品种/档位至少65秒；正常关闭并等待排空后取关闭报告，回传最后的安全ZIP。DDB和实时VPN按既有策略，勿重映射Y或强杀进程。
