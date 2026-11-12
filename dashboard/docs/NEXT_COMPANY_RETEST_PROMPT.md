# 下一对话：行业权重变化补全与公司复测

2026-11-12行业变化补全，统一codex/company-apps，实施基线a628472，最终运行版本以Git HEAD及远端为准。完整同口径历史比较优先；历史不全时按成分代码及真实权重日期配对，或在行情样本覆盖更高时按现有权重和有效成分涨跌估算。标题明确“部分成分”或“涨跌估算”，显示样本数、基准日期、缓存状态和百分点；缺项不补零、未知行业保留“待分类”。无可信权重或行情时仍显示真实缺项原因；公司新图效果待更新后验收。

510项完整回归通过，130.731秒（含加载），无跳过，ResourceWarning作为错误；较上版新增14项。 本地PySide6主窗口用合成数据在1536×864逻辑像素、125%缩放离屏检查了中证500涨跌估算变化图、样本数及基准日期；同时核查860×620布局。合成截图不等于公司实际数据或公司新版本验收。

## 可复制提示词

请继续Delta1公司看板。先完整读取本文件与docs/INDICATOR_PAGE_PROPOSAL.md，再阅读AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE和COMPANY_SYNC。统一工作区P:/project/swhy/Delta1/company-apps-worktree、codex/company-apps；先核验Git、远端、worktree、status与diff。

核验我提供的最新公司安全包，同次开窗及关闭按同一report_path识别；检查index_industry_changes中IC/IM的comparison_kind、样本、日期、来源与缺口，在指数页验收变化图，区分完整历史、部分成分和涨跌估算。不将缺项补0。按需核验indicator_draw实际绘图及源时间、Z和分位，区分午休模式切换；核查DDB和同次关闭。必要实施、测试、精确提交推送授权持续，本地验证与公司验收分开。

估算公式：以真实基准权重w、同快照成分涨跌ri、同快照指数涨跌R计算w*(1+ri/100)/(1+R/100)-w，单位百分点。指数涨跌缺失时使用已覆盖成分按原权重的加权涨跌作为分母并明确标注；未匹配的成分不纳入，不伪造权重或行情，也不称官方完整变化。旧基准权重保留原日期，估算并不保证等于真实昨日权重。历史配对逐成分校验同指数、同来源、同分类口径、真实且先后的权重日期；分类变更成分排除，分类未知归入待分类。

原数据、配置、凭据、Excel、其他worktree、四份受保护提示词及APP_RELEASE.backtest原块保留；逐日D、简单年化、连续四档固定20/60规则保持，32项/A02继续暂停；默认Overview离线、DDB不暂停、实时VPN手动，不强杀写入者、删锁、重映射Y、reset/clean、全量stage或强推。

## 最新已审公司包

公司安全包20261112_111531_749_safe_113124_158_68fd3bf7.zip，130457字节，SHA256 1e80ae4ff4d06748b8688e90c9bfef746296063321ec7a7e2da08f6cfadd101a，运行a628472；9份JSON、CRC正常、Complete=true、MissingReports=[]。同一515050c运行正常关闭7.247秒、waiting=[]，成分sqlite_committed。两次Overview及preflight退出0、stderr为空。

IM02同一选择在11:30:00.911、11:30:30.922、11:31:00.911实际绘图，相隔30.011秒、29.989秒。第一帧为11-12 11:29:56盘中行情，年化Z约0.0694、分位45%；后两帧为11-11收盘参考，年化Z约0.8326、分位75%；变动跨午休定价模式，不能据此宣称连续多个盘中tick均改变Z/分位，分位也不保证每个tick都变。

本包DDB为192.168.198.77:8904，复用existing_tunnel，TCP和认证成功，query_partial、插入0；11:16维护时仍有收盘和持仓缺项记录，该记录不是最终全品种结果。DDB不暂停，实时VPN仍手动。

本包归档读取23份，IC/IM各22组中17组重复、5组上期权重不完整或不可比，是旧变化图为空的直接原因；当前权重日期10-30，500只中49只、1000只中148只缺行业分类，二者属于另行统计的分类缺项。

## 公司原入口

```bat
cd /d D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard
git pull --ff-only && call dashboard\company_retest.cmd -SampleSeconds 900
```

按需取开窗报告，正常关闭并等待排空后取关闭报告，回传最后的安全ZIP。DDB和实时VPN按既有策略，勿重映射Y或强杀进程。
