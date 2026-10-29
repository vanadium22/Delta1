# Delta1 公司看板当前交接

2026-10-29。基线为已发布75d9da034dca6ddda1e9f375517545e8bde27dc5，统一分支codex/company-apps。本轮批次 `2026-10-29-company-resilience-and-excel-reconciliation`；实际提交以Git/远端及交付回复为准，精确文件清单见APP_RELEASE.latest_update.files。必要实施、测试和提交推送授权继续有效。

## 最新回传与Excel对账

下午包20261029_131553_666_safe_135610_892.zip的SHA256为fb133dd757b9a6e23c5a0882ae294fd3f8daacf4f1b58e211adf3783127f2969，只有git.json、drive_y.json、return_manifest.json。HEAD为75d9da0；manifest明确缺Overview及同一运行的开窗/完成关闭报告。不能由此确认新关闭耗时、现场年化输入，亦不能认定用户没有执行采样；旧脚本依赖目录CreationTime也是需排除的发现问题。

只读核验此前两份分红Excel的Sheet1缓存和公式：10-27文件B1为10-27，使用Wind日收盘；09-18文件名的上传件B1实际为10-28，价格为Wind RTD缓存。15/16合约D不同，G列为数值，并不由B1或RTD价格自动证明已更新。两份共32行用当前应用calculate逐项复算，最大年化误差3.3751e-14个百分点；公式均为100*(F-S+D)/S*365/T。最近f345174至75d9da0未改此公式。真实App与Excel差额还需同一时点F/S/D/T，不盲改公式或自动导入上传Excel覆盖Y源。

## 本轮修复与验证

- 低频资料读取按完整指数/ETF分组与单只NAV隔离；坏NAV不隐藏其他ETF、行业名单或有效报价。完整篮子/排名分组仍整体校验，不把损坏成员当完整资料；跨指数ETF身份冲突仍拒绝排名。正式publish继续严格校验，读取不改原文件。
- 个别成分快照条目或源时间无效只影响对应股票；单个历史文件读错误不再中断整页，其他有效历史和最新价格保留。缺失仍明确，未知权重不填0、不归一化，30秒/3秒不放宽。
- 年化悬浮和详情可看实际F/S/D/T、定价日与分红表业务日。离线Overview的data_gaps.page_calculation_preview.futures增加两腿价格/源时、到期日/天数、D版本/生效时间/文件SHA等。预览是实际页面引擎计算，不证明运行中UI已应用。
- diagnose_presentation新增OutputDirectory，报告直接进入本轮目录的唯一diagnosis子目录。collect_company_return.ps1统一白名单打包，同时按diagnosis.at恢复旧runtime报告，不依赖文件夹CreationTime；核验时间、HEAD、LocalRoot及同一App报告路径的开窗/最终关闭，Complete/MissingReports如实报告，缺项仍可回传。

210项受影响回归通过，51.206秒，无跳过，ResourceWarning作为错误；包含6个真实PowerShell打包场景、Y迁移/导入参数、逐日D/连续分位及关闭。新OutputDirectory也用隔离配置运行真实离线Overview核验。Excel只读复算不执行Wind/RTD、不改原件。详见 [APP_VALIDATION](APP_VALIDATION.md)。

## 既有公司证据与待办

早包20261029_105858_132_safe_110614_022.zip为24个JSON，五个diagnosis及git均f345174，manifest无缺项。公司Python为D:/conda/envs/swhy_delta1/python.exe，配置SHA一致；用户确认采样开窗，旧版正常关闭约1–2分钟。

| 项目 | 已确认 | 仍待核验/输入 |
|---|---|---|
| Y分红 | Share complete，Import新增16条，库16→32，B1=10-27，当前16合约取新D | 年份目录仅匹配1份表；60日历史D缺556行，不能以新D回填旧日 |
| 连续分位 | 16档20日完整，历史日线缺价0 | 16档60日均缺历史D；不重复DDB下载价格掩盖 |
| 行情/行业 | 两次32主标的新鲜且源时推进，有页面应用时间；300/50/500/1000名单齐，涨跌覆盖300/50/500/997 | IF/IC/IM权重缺1/2/2且日期混合，IH日期09-30，分类缺17/2/49/148；完整贡献待可靠权重 |
| ETF | 四指数各前三及价格，12/12同日10-28 NAV/未复权close；截图收盘折溢价−20.0/−19.8/−18.2bp | 盘中IOPV、份额/拆分单位和带日PCF仍mapping_required，不用NAV/规模/成交量替代 |
| 安全关闭 | 75d9da0已加App专用最多4个文件写入者/批量目录登记、进度及最终closed/shutdown.complete | 本机1800标的归档8.884→2.489秒是合成数据；下午包没有Overview，新公司耗时仍未知 |

默认公盘仍 `Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`，业务日以Sheet1!B1为准。drive_y.json实际记录DisplayRoot为\\192.168.91.230\FTPServer，默认用Y，不猜拼、不重新映射。旧内置UNC运行时迁移、自定义/空白保留及SourceDirectory/InputFile语义不变。

## 公司下一步

按 [APP_COMPANY_TEST](APP_COMPANY_TEST.md) 第1、4、5节：正常关闭旧看板等后台退出→git pull --ff-only并新建本轮目录→正常开窗→保持开窗导出Overview→正常关闭等待排空→关闭后再导Overview→安全JSON ZIP。保持Wind登录、实时VPN手动。查看年化悬浮F/S/D/T及D业务日，与Excel同一时点核对。不要向旧git.json目录混入新HEAD报告。

第2节保留分红Local/Share/Import及指定InputFile命令，第3节保留行业/ETF只读阶段；需要完整源复测才选择full。真实完整权重、IOPV/份额/PCF仍须已核验定义；不猜字段。默认Overview离线不启动App/网络，预览和状态文件不代替公司持续页面验收。

## 保护与入口

本机工作区P:/project/swhy/Delta1/company-apps-worktree；公司Git根D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard，LocalRoot为其下dashboard/localsetting/app。原入口dashboard/start_presentation.vbs/public不变，原配置P:/project/swhy/Delta1/project/dashboard/localsetting/native.json。

保留逐日实际合约D、连续00/01/02/03的20/60、简单年化、当前定价日排除、T<5单列、真实缺价/映射/D不跳过、明确0优先、当时已知前序到期合约继承及非交易真实价格日/T/D。新D不回写过去。研究32项/A02暂停保留，原独立App/Excel不动。主HTTP三秒、成分一分钟，DDB仅实际历史缺口，不因HTTP失败切DDB。

不强杀写入者、不删锁、不reset/clean、全量stage或强推。原行情/缓存/配置/凭据/Excel、其他模块/worktree和四份受保护提示词保持原位。本轮8,446个保护文件逐个SHA复核；证据/日志仅在忽略的local_artifacts/validation/company_afternoon_20261029。七份旧说明仍只有 [唯一归档](../docs/archive/2026-10-29/README.md)，MANIFEST不变，不重复归档。

新对话先读 [接续提示词](docs/NEXT_COMPANY_RETEST_PROMPT.md)、本页、AGENTS、APP_COMPANY_TEST和APP_RELEASE，再核验最新Git/远端与新包。
