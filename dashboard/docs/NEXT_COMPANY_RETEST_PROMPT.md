# 下一对话：公司真实取数与持续页面验收

交接日期：2026-10-29。本轮Y盘修正、导入参数、来源审计和文档收敛已完成，发布批次 `2026-10-29-confirmed-y-dividend-source-and-company-retest`，基线69789a4。实际发布提交以最新Git/远端及本轮交付回复为准；不要再把本轮当成“51项后尚未运行/未整理”的旧现场。公司真实取数仍未验收。

## 可复制接续提示词

请接续Delta1公司看板真实验收及回传报告分析；若发现问题，完成必要修复、测试、交接和统一分支提交推送，既有授权继续有效。

先完整读取本文件，再核验根目录及dashboard/AGENTS、dashboard/PROJECT_HANDOFF、APP_MARKET_OVERVIEW、APP_VALIDATION、APP_COMPANY_TEST、APP_RELEASE.json、COMPANY_SYNC和最新Git/远端/status/diff。工作区 `P:/project/swhy/Delta1/company-apps-worktree`，统一分支 `codex/company-apps`，远端 `https://github.com/vanadium22/Delta1.git`。公司Git根 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`，LocalRoot为其下dashboard/localsetting/app。

正确公盘源：

```text
Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026
```

Y:映射192.168.91.230，完整UNC共享名未知，不猜拼地址或重新映射。2026是年份目录，匹配指数基差情况_*.xlsx，业务日期以Sheet1!B1为准。旧内置UNC在运行时兼容到Y；自定义目录/显式空白和个人配置保留。设置显示有效源，调度指纹包含有效源，旧成功检查不能挡住迁移重查。

本轮最终55项受影响测试通过（12.676秒，无跳过，ResourceWarning作为错误），包括此前未运行的调度迁移、原配置不写、中文空格真实Windows CMD、B1错名/窗口判断、SHA/元数据去重、来源审计及原概览/采集/安全退出。此前229/62/272项是三批历史证据，不是公司验收。本机没有Y映射，未验证公司公盘或真实公司接口，不再把本机旧WinError53/缺WindPy当公司结论。

公司完整可复制步骤统一在dashboard/APP_COMPANY_TEST.md，已经包含：更新与同次HEAD/Y映射元数据；分红Local前后、Share、Import；可选InputFile；Wind Connect/Indices/ETFs；ETF Local/能力；正常开窗10–15分钟并正式发布资料；保持窗口开着跑Nav/Overview；只收白名单JSON到新目录、核验ZIP并附缺失清单。不要另写相互矛盾的旧命令。

读公司ZIP时先核对return_manifest、git.json、drive_y.json及同次diagnosis/preflight，确认HEAD/LocalRoot/解释器和窗口是否实际开着，再逐项区分：

1. 分红是否实际扫描Y年份目录、匹配/读取了哪些文件、B1业务日和SHA、inserted/unchanged及16合约实际D来源；全库日期汇总与单个配置文件来源不混淆。SourceDirectory只是本次覆盖，InputFile只允许Import且跳过公盘同步，二者互斥，不改原件/配置。
2. 同步成功和历史D完整分开。退出2/ok=false可仅因旧日缺D；今日新表不能回填所有旧日，非交易参考用实际价格日的D，不误拿当前Local选择当昨日价格日D。
3. Connect/Indices/ETFs/Nav及ETF能力是只读测试，不发布。正常看板任务是否实际发布名单/权重/行业/排名/NAV，Overview行业inputs、分钟覆盖和同日close/NAV是否齐；旧报告不能证明当前发布或持续进程。
4. IOPV/净申赎/PCF若mapping_required，是缺已核验字段/单位/带日定义，不等同本次接口失败；不得猜字段或用成交量/规模代替。公司WindPy已存在，本机缺模块不能推断公司缺模块。
5. 保持真实30秒/3秒、主HTTP三秒、成分一分钟。持续页面、非交易参考、切页/滚动、查询/取消和关闭耗时以公司同次证据判断，不能由单次非空或本地构造测试认证。

保留逐日实际合约D、连续00/01/02/03的20/60分位、简单年化100*(F-S+D)/S*365/T、当前定价日排除、T<5单列及真实缺口不跳过。明确0优先，缺D仅向当时已知前序到期合约继承，新D不回写过去；非交易冻结实际价格日/T/D，不混腿。

研究32项/A02继续暂停并保留，原独立App和Excel不动；日常只补概览日线。默认Overview离线，实时VPN手动，DDB仅实际缺口按原授权准备，不因HTTP失败切DDB；取消自有只读SDK/SMB，写入者排空，不强杀、不删锁。

原行情/分红/缓存/配置/凭据/Excel、其他工作区及四份受保护未跟踪提示词保留。用户允许本次必要实施、测试及精确清单提交推送统一分支；不reset/clean、全量stage、强推或覆盖旧工作。更新APP_RELEASE/COMPANY_SYNC及交接后核验远端，明确本地验证与公司验收。

7份旧说明已按SHA归档一次到docs/archive/2026-10-29，索引和MANIFEST已核验。ROOT_AGENTS/DASHBOARD_AGENTS是历史原文，不是当前入口；不要重复归档或沿用其中旧UNC、固定情景及“仅分析/未实施”限制。

## 接续所需文件

直接使用APP_COMPANY_TEST生成的safe ZIP：git.json、drive_y.json、分红before/share/import/after（可选downloaded）、etf_local/etf_capabilities、各阶段diagnosis/preflight/wind/overview及return_manifest。另附测试时间、取样时窗口状态、行业/ETF表现和关闭耗时；异常截图可另传。禁止收native.json、凭据、原始日志、SQLite或Excel。暂无公司新回传时，明确待验收，不制造已通过结论。
