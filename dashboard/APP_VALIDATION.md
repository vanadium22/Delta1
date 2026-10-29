# 看板当前验证与公司验收边界

2026-10-29。本轮基线f345174b07d7acea469d6ba1655e8f7355792ce3，统一分支codex/company-apps。发布清单见APP_RELEASE，现场事实见 [PROJECT_HANDOFF](PROJECT_HANDOFF.md)，命令见 [APP_COMPANY_TEST](APP_COMPANY_TEST.md)。

## 本次公司证据

完整解析用户ZIP的24个JSON，逐文件记录SHA与结构；return_manifest无缺失，五个diagnosis及git.json均为f345174。原配置SHA一致，实际公司Python为D:/conda/envs/swhy_delta1/python.exe。

Y源Share complete、无错误，Import新增16条；库从16条/1版本变成32条/2版本，B1为10-27，16当前合约选到新D。目录本次只匹配1份表；20日分位16档完整，60日0档完整，历史D缺556行、真实历史日线缺价0。不能将ok=false解释为此次Y文件未读。

32主标的新鲜且两次样本源时推进，同配置有collecting/closing=false和页面应用时间；用户确认窗口开着。四组名单300/50/500/1000已知，IF/IC/IM缺1/2/2权重且行日期混合，IH权重09-30。分类缺17/2/49/148，有效涨跌覆盖300/50/500/997。股价存在不等于完整行业权重/贡献可用。

ETF四组各前三已发布；12/12同日NAV/未复权close配对、Nav只读阶段通过。用户截图显示三只IF ETF的10-28收盘折溢价−20.0/−19.8/−18.2 bp；大字空白为缺IOPV的盘中折溢价。IOPV/份额/PCF定义仍mapping_required，不制造返回或用NAV/规模/成交量替代。

用户报告正常关闭约1–2分钟。旧closing状态没有成分归档细节，不能由旧文件认定当前窗口存活，亦不能认定逐股归档是现场唯一原因；下一包需新关闭进度/最终状态。

## 最终本地回归

**98项通过，20.927秒，无跳过，ResourceWarning作为错误。**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
$env:TEMP='P:/project/swhy/Delta1/company-apps-worktree/local_artifacts/validation/company_feedback_20261029/tmp'
$env:TMP=$env:TEMP
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest tests.test_overview_company_feedback tests.test_overview_details tests.test_overview_revision tests.test_overview_capabilities tests.test_overview_audit tests.test_app_pipeline tests.test_app_collection tests.test_market_overview_ui tests.test_realtime_store
```

覆盖有界并行归档/SQLite目录提交、关闭等待写入和writer锁、标准Reader逐股Parquet一致、磁盘失败后全部自有写入者排空/SQLite重放/原件SHA不变；真实名单完整但权重缺失、慢历史期间发布新快照及晚于检查起点的质量未知；同日NAV/收盘与盘中IOPV分列、离屏卡片、关闭进度/最终closed、诊断秘密字段过滤，以及原三秒主行情/一分钟成分/原标准库采集与安全停止。

初轮97项的2项未通过分别是新测试误把WriterLock当上下文管理器、旧UI断言仍期望“折溢价”旧标签；修正测试后97项通过，再补未来快照边界后完整98项重跑通过。首次测试的ResourceWarning来自上述测试锁未显式关闭，已修正，最终日志无该警告。没有放宽质量门槛或修改业务公式。

## 隔离归档和页面检查

同机同结构1800标的合成SQLite，关闭前禁用周期归档，比较末尾排空：共享原实现8.884秒，App专用实现2.489秒，均生成1800个逐股Parquet。新实现最多4个文件写入者、每64个已完成文件批量登记；原SQLite/raw/Parquet及标准读取格式不变，原共享RealtimeStore默认行为未改。数据、文件和目录写入完成后才释放writer锁，不把写入推迟到未知未来或强杀。

上述性能仅属本机合成数据，不承诺公司同样耗时。1580/860宽窄ETF界面已离屏生成并查看，明确显示盘中空项及收盘数值/日期，无遮挡或缩字号；用户原截图不改。只有新的公司关闭报告能确认现场效果及剩余等待阶段。

当前PowerShell代码块/入口参数、安全ZIP的full/runtime完整及缺项分支、同运行开窗/完成关闭匹配、本地文档链接、JSON白名单、Python语法和Git diff均核验后发布。原7份归档及MANIFEST保持不变，其Git对象原始字节SHA继续核验，无重复归档。

## 原件保护与历史

8,445个保护文件包括先前原行情/缓存/配置/凭据/Excel/依赖、四份提示词及本次原始ZIP；发布前逐个大小/SHA复核。当前证据、测试、原件清单和性能产物仅在忽略的local_artifacts/validation/company_feedback_20261029，不提交真实JSON、原ZIP或截图。其他worktree/进程未操作。

| 前序发布 | 当时验证 |
|---|---|
| f345174 | 55项，12.676秒：Y默认迁移/导入参数/B1窗口/审计及唯一归档 |
| 69789a4 | 272项：行情分析/行业修复/ETF能力；另资源边界 |
| 1408292 | 62项：20卡/同级页/状态/图标 |
| 67c2db6 | 229项：逐日D/四档连续分位/非交易参考 |

历史测试数字不套作本轮测试或公司新关闭验收。7份旧长文只保留 [唯一归档](../docs/archive/2026-10-29/README.md)。默认Overview离线，实时VPN手动，研究32项/A02暂停保留；真实缺项继续保留。
