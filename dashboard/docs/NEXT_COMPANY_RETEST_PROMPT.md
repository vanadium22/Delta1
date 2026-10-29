# 下一对话：公司有效报告与Excel同输入对账

2026-10-29。当前批次2026-10-29-company-resilience-and-excel-reconciliation，基线75d9da0，实际新提交看Git/远端及交付回复。先读本文件全文，再读根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE和COMPANY_SYNC。

## 可复制接续提示词

请接续Delta1公司看板，工作区P:/project/swhy/Delta1/company-apps-worktree，统一分支codex/company-apps。先核验最新Git/远端、worktree、status/diff与发布清单，不从旧版重做。必要实施/测试/精确清单提交推送授权持续有效；不reset/clean、全量stage、强推，不动其他模块/worktree与四份受保护提示词。

最新下午包20261029_131553_666_safe_135610_892.zip只有git/drive_y/manifest三个JSON，HEAD=75d9da0，明确缺Overview与同运行开窗/完成关闭。不能认证新关闭时间或现场年化，也不能认定用户没采样。新OutputDirectory让diagnosis直接进入deltaReport子目录，collect_company_return.ps1按diagnosis.at兼容恢复旧runtime，不依赖目录CreationTime；检查HEAD/LocalRoot/时间、同一App report_path、Complete/MissingReports，不混旧git.json与新HEAD。公司按APP_COMPANY_TEST第1/4/5节更新、正常开窗Overview、正常关闭等排空、关闭后Overview及JSON ZIP；Full源测试保留按需。

用户问分红后年化和Excel不一致：两份用户Excel共32行按当前calculate复算全符，最大误差3.3751e-14个百分点；15/16合约D不同，F/S/T也不同。10-27表B1=10-27且日收盘，文件名09-18的上传件B1实际10-28且RTD缓存，G列为值，不因更新B1/价格就证明D更新。f345174→75d9da0未改公式。需用新Overview.data_gaps.page_calculation_preview.futures的F/S/D/T、pricing_day/at、两腿源时、D业务日/生效时间/文件SHA与Excel同输入对账，不能盲改公式或自动导入上传Excel覆盖Y源。原件只读，不执行RTD、不保存。

本轮鲁棒性：低频读取按完整指数/ETF分组、单只NAV隔离，坏可选资料不隐藏其他有效报价；正式publish保持严格，损坏成员不当完整篮子或排名。个别成分/时间和历史I/O错误仅影响对应范围，其余有效行情保留。年化悬浮/详情显示实际输入。210项受影响回归通过（51.206秒，无跳过，ResourceWarning作为错误），其中6个实际PowerShell打包场景；另有真实隔离Overview验证OutputDirectory。不得以本地测试代替公司。

前次24份JSON(f345174)和截图已确认Y Share/Import成功，新D16条、库16→32，B1=10-27；16档20日完整，60日全缺D，共556行，真实历史日线缺价0。Y源仍Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026；现场DisplayRoot为\\192.168.91.230\FTPServer，默认用Y，不猜拼或重新映射。2026为年份目录，业务日以B1；旧默认运行时迁移、自定义/空白保留及SourceDirectory/InputFile语义不变。

完整名单300/50/500/1000，IF/IC/IM缺权重1/2/2且日期混合，IH日期09-30，分类缺17/2/49/148；未知权重不补0、不归一化。四组ETF各前三/价格与12组同日10-28 NAV/close已有证据，截图收盘溢价−20.0/−19.8/−18.2bp已显示。大字空项为盘中IOPV；IOPV/份额/PCF仍须已核验字段、单位和带日定义，不猜字段，不用NAV/成交量/规模替代。

75d9da0已优化App专用成分归档：最多4个文件写入者、完成后每64个批量提交SQLite目录，保留原SQLite/raw/逐股Parquet和标准Reader，失败从已提交SQLite重放，关闭等待全部写入。进度、等待者、最终phase=closed/shutdown.complete/elapsed_seconds须新公司包确认。旧版用户关闭1–2分钟，本机1800标的8.884→2.489秒仅属合成数据，不认证现场。

继续保留逐日实际合约D、00/01/02/03连续20/60、100*(F-S+D)/S*365/T、当前定价日排除、T<5单列、真实缺价/映射/D不跳过。明确0优先，缺D只继承当时已知前序到期合约，新D不回写过去；非交易保留真实价格日/T/D及来源。研究32项/A02继续暂停且保留，原独立App/Excel不动。主HTTP三秒、成分一分钟、30秒/3秒不放宽。默认Overview离线，实时VPN手动，DDB仅实际缺口，HTTP失败不切DDB。不强杀写入者、不删锁。

原数据/缓存/配置/凭据/Excel、其他工作和四提示词不动。七份旧说明及MANIFEST仍唯一SHA归档，不再复制。证据在忽略的local_artifacts/validation/company_afternoon_20261029。暂无有效新公司报告时，如实报告Y/收盘溢价已确认，历史D/完整行业/盘中数据定义、现场年化输入和新关闭耗时仍待验收。
