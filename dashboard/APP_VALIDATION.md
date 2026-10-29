# 看板当前验证与公司验收边界

2026-10-29。基线75d9da034dca6ddda1e9f375517545e8bde27dc5，统一分支codex/company-apps。本轮批次2026-10-29-company-resilience-and-excel-reconciliation。文件见 [APP_RELEASE](APP_RELEASE.json)，现场事实见 [PROJECT_HANDOFF](PROJECT_HANDOFF.md)，公司命令见 [APP_COMPANY_TEST](APP_COMPANY_TEST.md)。

## 最终本地回归

**210项通过，51.206秒，无跳过，ResourceWarning作为错误。**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
$env:TEMP='P:/project/swhy/Delta1/company-apps-worktree/local_artifacts/validation/company_afternoon_20261029/tmp'
$env:TMP=$env:TEMP
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest tests.test_overview_resilience tests.test_company_safe_return tests.test_market_overview tests.test_market_overview_ui tests.test_futures_overview tests.test_overview_audit tests.test_overview_details tests.test_overview_revision tests.test_overview_company_feedback tests.test_overview_capabilities tests.test_overview_data tests.test_overview_dated tests.test_overview_percentiles tests.test_overview_wind_evidence tests.test_dividend_check_input tests.test_app_pipeline tests.test_app_collection tests.test_realtime_store tests.test_percentile_audit
```

覆盖单只坏NAV/资料容器/单指数权重损坏的隔离、跨指数ETF身份冲突拒绝、全局时间错误不救活、个别成分快照/源时损坏、历史I/O错误后其余最新价与历史保留、D变动对年化的精确影响、缺D原始点基差保留、真实页面预览F/S/D/T与来源；并重跑Y默认迁移与调度重查、导入参数/B1审计、逐日D、20/60连续分位/非交易参考、行情页面、原有关闭排空和标准存储回归。

安全回传实际执行6个隔离PowerShell场景：runtime完整、仅元数据缺项、不同App运行、错误HEAD/配置、旧runtime目录CreationTime早于本轮但diagnosis.at有效、full所有阶段完整。只收白名单JSON，native.json/原始日志不进入ZIP；完整/缺项门槛不冒报。新OutputDirectory另以隔离配置实际运行diagnose_presentation -Overview，preflight/Overview退出0，原配置不变，无网络/App启动。CMD包装入口在含空格路径实跑，参数正确传入，三JSON缺项包明确Complete=false。

首轮63项和打包6项已通过，最后上述210项完整重跑，不沿用前序98/55结果。本轮测试没有新增失败或跳过。Python/PowerShell语法、8个公司命令代码块/15次包装调用、91个本地链接、27文件精确发布清单、diff及7份归档原始字节SHA均已核验。

## Excel只读复算

两份用户原件仅通过ZIP/XML读取Sheet1缓存/公式，不启动Excel/Wind/RTD、不重算或保存工作簿。JavaScript按Excel表达式复算，随后直接调用当前应用calculate：32/32年化一致，最大误差3.375077994860476e-14个百分点；公式为100*(F-S+D)/S*365/T。

10-27文件B1=10-27、日收盘；文件名09-18的上传件B1实际10-28、RTD缓存，G列为值。15/16实际合约D不同，F/S/T也不同。新Y数据导入会改变D的选择，不能用不同日期输入认定公式错误。最近f345174→75d9da0未修改年化计算。下午包缺实际App输入，仍不能逐项断言现场差额由哪项造成。

## 公司验收仍有边界

早包24份JSON的f345174及ETF截图已确认：Y Share/Import成功、16档20日完整、12组同日NAV/收盘，截图收盘折溢价已显示。60日缺历史D556行、完整行业权重/分类、盘中IOPV/份额/PCF定义仍缺；原报告没有真实日线缺价，不能重复DDB下载掩盖缺D。

新下午包只有3个JSON，HEAD=75d9da0，return_manifest缺Overview与同运行开窗/最终关闭。不能认证新公司关闭耗时、当前年化F/S/D/T或持续页面。75d9da0的本机1800标的合成归档8.884→2.489秒仍仅是本机性能；公司此前1–2分钟关闭的剩余等待阶段需新报告。

默认Overview离线，实时VPN手动，DDB只补真实缺口，正常关闭等所有写入者排空，不强杀、不删锁。研究32项/A02与原独立App/Excel保留。

## 原件保护与历史

本轮8,446个保护文件共365,393,708字节，包括原行情/缓存/配置/凭据/Excel/依赖、四提示词及原ZIP；最终逐文件大小/SHA复核。真实原件/报告不提交。证据、Excel复算、隔离测试、保护清单和发布审计仅在忽略的local_artifacts/validation/company_afternoon_20261029。七份旧说明及MANIFEST保持 [唯一SHA归档](../docs/archive/2026-10-29/README.md)。

| 前序提交 | 对应历史验证 |
|---|---|
| 75d9da0 | 98项：成分归档/关闭进度、名单/权重与NAV诊断，宽窄ETF离屏检查 |
| f345174 | 55项：Y默认迁移/调度/导入参数/B1窗口、来源审计与文档归档 |
| 69789a4 | 272项：行情分析/行业修复/ETF能力 |
| 1408292 | 62项：20卡/同级页/状态/图标 |
| 67c2db6 | 229项：逐日D/四档连续分位/非交易参考 |

历史结果不套作本轮测试或公司真实验收。
