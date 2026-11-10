# 看板当前验证与公司验收边界

2026-11-10。本轮基线c730d46，运行基线b5746c7；统一codex/company-apps。范围为新包核验、启动提速、目录整理和源码说明，精确清单见[APP_RELEASE](APP_RELEASE.json)。

## 本轮最终回归

**298项通过，73.884秒（含加载；unittest执行72.497秒），无跳过、无失败，ResourceWarning作为错误。** 原267项全部重跑，另含启动器、离线预检、安全接管和维护工具测试。专项42项/28.244秒仅属中间结果，最终以298项为准。

入口仍为标准unittest加载/执行，项目内临时目录及Windows多进程main保护。完整日志local_artifacts/validation/company_20261110_startup/full_final.txt；复用前次run_tests.py加载器，未把前次结果当本次。命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning local_artifacts/validation/company_20261110_afternoon/run_tests.py tests.test_app_collection tests.test_app_pipeline tests.test_company_safe_return tests.test_dividend_check_input tests.test_futures_overview tests.test_market_overview tests.test_market_overview_ui tests.test_overview_afternoon_feedback tests.test_overview_audit tests.test_overview_capabilities tests.test_overview_company_feedback tests.test_overview_data tests.test_overview_dated tests.test_overview_details tests.test_overview_etf_display tests.test_overview_final_polish tests.test_overview_percentiles tests.test_overview_resilience tests.test_overview_revision tests.test_overview_wind_evidence tests.test_overview_zero_dividends tests.test_percentile_audit tests.test_realtime_store tests.test_app_launcher tests.test_app_preflight tests.test_app_instance tests.test_workspace_cleanup
```

新增3项重点验证预检与App实际同PID/同导入对象、未处理异常保持安全失败阶段、不完整旧会话仍检查而已排空会话跳过CIM。既有实际PowerShell测试覆盖带中文/空格/特殊字符路径、stdout/stderr同时排空、预检失败不启动、退出码、控制台隐藏但不隐藏首个GUI；实际双Qt实例测试仍验证写入后安全接管、不强杀/删锁。

267项原回归继续覆盖逐日D/历史零占位/连续20与60、价格与OI隔离、真实viewport四指数点击、字号/比例、300分批与缺项优先、冻结代次、完整基差沿用及换slot/T<5、双饼图、Wind三个月规模、原始存储和PowerShell安全打包。公式、采集频率和暂停研究边界未改。

## 启动速度与目录核验

相同隔离空配置、真实PowerShell启动器、离屏/只读；测量从启动到首轮结果并正常退出，包含完整预检及退出开销：

| 版本 | 三次耗时（秒） | 中位（秒） |
|---|---|---:|
| 修改前 | 3.5782 / 3.3831 / 3.4736 | 3.4736 |
| 修改后 | 2.2771 / 2.1880 / 2.1732 | 2.1880 |

减少约37.0%。新版共享解释器起点至window.show返回1.39–1.46秒，首轮结果1.60–1.68秒；测量不含真实网络/完整历史/旧写入者排空。公司尚未运行新优化，不能承诺相同速度。新startup字段可在下一次安全ZIP中核验这些阶段。

仅已知旧验证目录4项、122文件/296615字节先归档并逐文件SHA核验，再移除旧副本；12个可重建看板字节码/101834字节清理。归档97155字节，净减少301294字节。其他模块/回测字节码、原运行状态与依赖不处理。路径与恢复见[整理记录](../docs/WORKSPACE_CLEANUP.md)。新增常用入口只委托原启动/复测链。

## 新公司反馈证据

包20261110_142427_690_safe_143549_135_03c08120.zip：114425字节，SHA256=1c17773aa98f36d317a53b466a7be6612b0bab329fea54393f911476c122f4aa。ZIP CRC、9JSON、IncludedFiles、runtime/Complete=true、无MissingReports、两诊断与git同b5746c7、配置SHA一致且未变化。Overview本身没有启动App、Wind、网络或VPN动作。

同一会话62ac23d34dea43e2834e4b1001f2148b开窗collecting→closed，shutdown.complete=true、waiting=[]、**6.153秒**，sqlite_committed。7.422/20.229秒均是开始前旧运行，不计本次。没有完整启动计时，不能用开窗取样反推启动速度。

32个主报价开窗样本间源时推进；成分1798/1800，300只/15秒、7批、轮目标300秒，pending=2；仍缺000831.SZ、688798.SH，没有低回包降100或缺项后来补齐的现场证据。四指数有效覆盖300/50/499/999，214行业分类仍缺、旧权重日期保留。

两份Overview共32条期货名义本金输入按Decimal独立复算，16个实际合约各有真实OI与价格，IF/IH300、IC/IM200、计一次。全部为2026-11-09同日完成日线，ETF全集分母、前三+其它、四档总额及比值一致。金额汇总见交接；不冒称11-10实时OI。两次各16档F/S/D/T年化复算一致；20/60各16项，但历史D零占位428、当前D11-06仍保留。ETF历史仍12只×60=720条。

用户“其余ok”记为现场使用反馈；JSON仅记medium偏好、数值和计算预览，不提供实际点击轨迹/截图。两次basis_display都未触发，故不把该包当沿用路径的独立实证。12只ETF标准历史层ValueError提示保留，同日NAV/close及规模仍可用；源端是否缺数据未重新联网测试。本轮没有Share/Import，不冒称重新公盘验收。

## 原件与发布保护

编辑前冻结8453个现存文件、365652303字节：原行情/分红/缓存/配置/凭据/Excel/运行依赖、四受保护提示词、新ZIP、七份唯一SHA归档和MANIFEST。前次13:11 ZIP原路径在开始前已不存在，absent_before.json单列；不恢复、不算本轮丢失。APP_RELEASE.backtest对象及原序列化块保留。最终核对见本轮protected_after.json。

原ZIP/JSON/性能记录/归档清单只留本机忽略目录，不进入Git。无可见测试窗口、真实行情源/VPN/Y操作；研究32/A02和其他模块/worktree保留。最终提交按精确白名单，远端核验后报告。

补充Windows锁/进程识别9项通过，1.195秒，包含新app_launch命令行身份及隐私白名单；最初沙箱中两项Restart Manager读取被拒绝，已在获准沙箱外复测全部通过。新增VBS常用入口已实际离屏/只读启动至安全关闭，原合成配置未变，启动时序也已通过Overview白名单读取。
