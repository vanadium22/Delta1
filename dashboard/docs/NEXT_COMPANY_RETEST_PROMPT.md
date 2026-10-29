# 下一对话：公司新关闭复测与缺项输入

2026-10-29。上次发布f345174的24份公司JSON和ETF截图已完整核验；本轮批次 `2026-10-29-company-feedback-safe-shutdown-and-evidence` 接续修复安全归档/关闭与诊断，具体提交以最新Git/远端及交付回复为准。不要重做旧Y迁移或把收盘折溢价误认为仍空白。

## 可复制接续提示词

请接续Delta1公司看板，先读本文件、根及dashboard/AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE.json和COMPANY_SYNC。核验最新Git/远端/status/diff，工作区P:/project/swhy/Delta1/company-apps-worktree，统一分支codex/company-apps；保留已有改动、其他worktree与四份受保护提示词。必要修复/测试及精确清单提交推送授权继续有效，不reset/clean、全量stage或强推。

已确认的公司事实：

- 24个JSON同次HEAD=f345174，配置SHA一致，WindPy存在。Y盘Share complete、Import新增16条，库由16到32条；B1为10-27，16当前合约选到新D。默认源仍Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026；drive_y.json实录DisplayRoot为\\192.168.91.230\FTPServer，不改映射、不猜拼。
- 本次目录只匹配1份表，20日窗口16档完整，60日0档完整，历史D缺556行、日线缺价0。缺D不是价格缺口，不能以最新表回填过去或重复DDB下价。
- 300/50/500/1000成分名单齐，IF/IC/IM缺权重1/2/2且日期混合；IH权重09-30，分类缺17/2/49/148。用户只能看到IH篮子涨跌符合当前权重门槛，不把未知权重填0或归一化。真实完整权重/分类须可靠输入。
- 四组ETF各前三、价格存在，12/12同日NAV/未复权close配对及Nav阶段通过。截图IF三只收盘折溢价−20.0/−19.8/−18.2 bp、日期10-28已显示；空白为盘中折溢价，IOPV/份额/PCF仍缺已核验定义，不猜字段或用NAV/成交量/规模替代。
- 两样本32主标的新鲜且源时推进，有页面应用记录，用户确认开窗。正常关闭约1–2分钟，旧报告缺成分归档进度，不足以确认唯一耗时原因。

本轮新增App专用成分归档：最多4个文件写入者并行，文件完成后每64个批量提交SQLite目录；保留SQLite/raw/逐股Parquet及标准Reader，关闭等待全部写入，失败从已提交SQLite重放，原共享RealtimeStore默认不改。关闭新增等待阶段、归档进度、耗时及最终phase=closed/shutdown.complete。不得强杀写入者或删除锁。

诊断修正名单完整与权重可用分离；历史慢读前冻结成分快照，晚于检查起点的快照质量标未知，不能误报全体陈旧。Overview新增实际逐ETF收盘NAV/价格/溢价、页面引擎ETF预览及安全关闭证据。UI明确“盘中折溢价”，真实收盘行独立保留。

最终98项受影响回归通过（20.927秒，无跳过，ResourceWarning作为错误）；1800标的同机隔离归档8.884→2.489秒，仅本机合成数据，不承诺公司耗时或认为全部问题已解决。宽窄1580/860离屏检查已完成。原7份归档和MANIFEST保持唯一原件，不重复复制。

公司新包按APP_COMPANY_TEST默认Runtime，只需更新→正常开窗Overview→正常关闭→关闭后Overview→安全JSON ZIP；Full分红/Wind步骤保留按需。先查return_manifest.RunMode/MissingReports、新HEAD和同运行report_path，核对开窗与关闭后的shutdown.complete/elapsed_seconds、成分archive状态和等待者。关闭后缓存变旧不能反推开窗行情中断。新关闭耗时和持续页面仍待现场，不用本地性能替代。

继续保留逐日实际合约D、四档连续20/60、简单去分红年化100*(F-S+D)/S*365/T、当前定价日排除、T<5单列、真实缺价/映射/D不跳过；明确0优先，缺D仅用当时已知前序到期合约，新D不回写过去，非交易保留真实价格日/T/D。

研究32项/A02继续暂停且原独立App/Excel保留，日常只补概览日线；主HTTP三秒、成分一分钟、30秒/3秒不放宽。默认Overview离线、实时VPN手动；DDB仅实际缺口按原授权准备，HTTP失败不切DDB。原行情/分红/缓存/配置/凭据/Excel、其他工作及四提示词不动。

暂无新公司包时如实说明：Y读入/收盘溢价已确认，但60日历史D、完整行业权重/贡献、盘中IOPV/份额/PCF定义及新公司关闭耗时仍有缺项；不宣称公司全部验收。
