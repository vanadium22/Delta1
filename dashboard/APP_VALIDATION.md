# 看板当前验证与公司验收边界

2026-11-10。基线365fe84dad7f377dd76be1199f5e7a7788b41464，统一codex/company-apps，批次2026-11-10-company-afternoon-feedback-and-market-sizes。精确文件见[APP_RELEASE](APP_RELEASE.json)，现场事实见[PROJECT_HANDOFF](PROJECT_HANDOFF.md)，[一键/完整手动命令](APP_COMPANY_TEST.md)。七份旧说明保留唯一SHA归档。

## 最终本地回归

**267项通过，53.505秒，无跳过，ResourceWarning作为错误。** 原247项全部重跑，加20项新反馈回归；最终在持仓缺项/价格隔离修正后完整运行，不沿用中间91/109项或首次267项的失败结果。

实际入口为忽略证据目录company_20261110_afternoon/run_tests.py，使用标准unittest加载/执行、项目内临时目录和Windows多进程main保护；完整日志full_final.txt。等价标准命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
$deltaTestTemp=Join-Path (Get-Location) 'local_artifacts/validation/company_20261110_afternoon/tmp'
New-Item -ItemType Directory -Path $deltaTestTemp -Force | Out-Null
$env:TEMP=$deltaTestTemp
$env:TMP=$deltaTestTemp
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest tests.test_app_collection tests.test_app_pipeline tests.test_company_safe_return tests.test_dividend_check_input tests.test_futures_overview tests.test_market_overview tests.test_market_overview_ui tests.test_overview_afternoon_feedback tests.test_overview_audit tests.test_overview_capabilities tests.test_overview_company_feedback tests.test_overview_data tests.test_overview_dated tests.test_overview_details tests.test_overview_etf_display tests.test_overview_final_polish tests.test_overview_percentiles tests.test_overview_resilience tests.test_overview_revision tests.test_overview_wind_evidence tests.test_overview_zero_dividends tests.test_percentile_audit tests.test_realtime_store
```

新增20项覆盖：实际viewport坐标在两尺寸点击两页面四指数、数字字号与无溢出；默认300只/15秒、仍五分钟一轮、失败/缺项下轮优先、低回包下一轮100；计算/审计冻结同一成分代次；上次完整基差/年化/20与60/F/S/D/T沿用、原始当前结果仍缺项、新价独立更新、跨进程重开、新有效值替换、换slot/到期修订不复用、T<5仍排除；ETF同日全集分母与前三+其它；四品种OI×价格×乘数、时间配对/日线回退、部分与真实0；16合约OI缺口、本地整行替换、不混价格/OI、价格先保存且不冒报重复OI进展。

原247项覆盖逐日D、源迁移/调度/导入、连续20/60/历史零占位/真实补齐、非交易参考、部分行业贡献/源时、规模历史与缺项隔离、分组显示缓存、存储/安全排空、页面比例/图例、真实PowerShell一键流程及白名单JSON ZIP。中间旧断言按用户新OI需求更新；实际发现并修复“缺OI压掉可用价格”问题，没有降低价格/映射/当前D/冲突/30秒与3秒门槛。

## 离屏图形与本机性能

1920×1080及1536×864（1080p屏125%系统缩放的逻辑尺寸）概览/指数/ETF/期货八图生成检查；中比例横/纵滚动最大值均0，20卡完整。概览去分红年化有效字号约14.24→21.13像素；125%逻辑尺寸约16.03像素，对应物理约20像素。概览合并头部/压缩留白，指数/ETF/期货卡内数字一并放大；大比例保留原字号和滚动（本次概览纵滚动245），窄屏860和小比例既有回归通过。

新双饼图、日期/总额/比值、四档名义本金及前三ETF+其它已离屏检查。期货横条加粗，文字在对应色块内、无细引导线；该横条仍是标题所写的成交分布，持仓名义金额单列新饼图。另保存新价配旧完整基差的明确“基差沿用”源时截图。全部以合成数据和明确测试标记生成，不操作生产窗口/真实VPN，不等于公司实际金额验收。

合成1850成员缓存分三类共1,504,477字节，原子保存0.0521秒；1850行/19批raw+SQLite提交0.1387秒，关闭0.0029秒，新Parquet文件0。此为本机路径检查，不承诺公司相同耗时；真实公司关闭看下面同次7.422秒。原逐股Parquet/SQLite/raw及显式归档和安全排空能力保留。

## 公司已验证与待验证

最新包20261110_131148_048_safe_132420_204_4c19bc5e.zip：110,109字节，SHA256=efafad2fbdd5036683a68d1226592dc41a1cbd7e8c006e82f0cfbca413840aa2；9JSON、runtime、Complete=true、无MissingReports，git及两份diagnosis一致365fe84。完整指反馈结构，不代表所有可选资料齐。

13:23开窗collecting与13:24关闭后来自同一App运行记录126449697e59409daf710f848ab32089。最终closed、shutdown.complete=true、waiting空，**7.422秒**，归档状态sqlite_committed。开始前20.229/76.312秒的旧记录不计本轮；73.499秒是更早旧包，最后空归档0.09秒也不是总关闭。

Wind正常任务published且warnings为空：12只ETF各60条，共720条，2026-08-10至11-09；三个月请求起点8-09，按实际交易日回包。最近两期11-06/11-09各只AUM相同为本次源结果，不是缺历史补0；只能证有日期的源披露，不推断真实基金资产每天恒定。净值/收盘对已有证据；IOPV/份额/PCF仍缺可靠定义。新图不再把重复变化作为主要信息，旧历史数据/缓存保留。

股票1798/1800（1850成分含重叠），缺000831.SZ与688798.SH；已收到股票无缺昨收或截止时陈旧。独立重算IF300/300、IH50/50、IC499/500、IM999/1000有效，部分贡献可算；214行业分类缺失仍保留。IF权重11-02，IC/IM10-30，IH官方10-30滚动至11-09且当期价格齐，不冒称官方准确昨日。原预览先固定计算时间、后读晚到快照而暂判0覆盖已定位；新代码冻结代次和截止顺序，本地回归通过，公司新预览待核验。

当前16实际合约D仍对应11-06表，20/60数值各16项；428条历史缺D零占位仍在，真实D覆盖未齐。前序33JSON包已证Y三表/64记录4版本及16实际合约同输入公式，本次runtime不冒称重新Share/Import。正确Y/B1/实际合约映射及简单年化不改；今日D不回填过去，真实历史D补入按版本重算。

用户确认中比例全卡，字体偏小由本轮调整。旧包无实际OI值，**不能直接复算新饼图真实总额**。公司新代码仍需一键验证四指数点击、字号/卡片稳定、300回包与下一轮补缺、双饼图OI/价格/乘数/日期/金额；新Overview的market_sizes和basis_display提供证据。只按当前16合约最新完成日OI/概览价格真实缺口本地优先准备DDB，不补全体成分或研究分钟。默认Overview离线、实时VPN手动、正常关闭等排空。

## 原件与发布保护

本轮编辑前冻结8,453个现存文件、365,647,987字节，包含原行情/分红/缓存/配置/凭据/Excel/运行依赖、四受保护提示词、新ZIP、七份唯一SHA归档及MANIFEST。最终发布前逐一核对大小/SHA，变化0、缺失0。前次9:24包原路径在本轮开始前已不存在，absent_before.json单独记录，不自行恢复或算成本轮丢失。APP_RELEASE.backtest对象及原序列化块原样保留。

本轮测试、JSON提取/解读、截图/性能、原件保护和发布证据仅忽略的local_artifacts/validation/company_20261110_afternoon；此前证据目录保留。真实ZIP/JSON、配置/业务数据不提交，其他模块/worktree/进程不操作。不强杀/删锁，不猜拼/重映射Y，不reset/clean/全量stage/强推。最终发布号以Git/远端和交付回复为准。
