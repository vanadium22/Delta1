# Delta1 公司看板当前交接

2026-11-10。基线12f34f1ba7e94776d177344692cdbe56f16f652f，统一分支codex/company-apps。本轮批次2026-11-10-company-dividend-history-and-etf-display。必要实施、测试、精确清单提交推送授权继续；最新提交看Git/远端及交付回复，文件见APP_RELEASE.latest_update.files。

## 公司本轮事实

完整读取20261110_092411_072_safe_094017_545_23667ca4.zip，SHA256=827b9a1feddd74a88873071b5a0f6ab2a06cc1bd118cf0a06e82abb13d5acc4b，201,026字节、33份JSON，full/Complete=true/MissingReports为空。git与8个diagnosis均为12f34f1，配置保留未改。9:28盘前、9:36开窗、9:40关闭后Overview属于同一App报告路径。

- Y Share complete，实际匹配并验证10-27、10-30、11-06三份表，B1日期一致；未看到11-09/10的新表。库64条/4文件版本，含原本地09-18版本；本次Import新增0、unchanged=4、无错误，表示已有相同内容，不是下载失败。
- 当前16个合约D全部来自11-06表SHA09c72b6a56b57a5e18b2f40a91ecf0d54e2341f0f483900d9961f2500d8f62b2，source_contract与卡片实际合约逐个一致，没有前序合约继承或错档。9:36的16行F/S/D/T独立复算最大误差8.8818e-16个百分点；用户补充可能用了更早的分红表比较，正在复核，未发现当前算式错误。
- 9:36历史20日16档完整；60日全部因D不齐，00各缺20日，01/02/03各缺29日，合计428条，真实日线缺价/映射缺0。9:28使用11-09收盘参考，窗口不同，缺D444条，不能混为同一窗口。
- 同一App最终phase=closed、shutdown.complete=true、等待者空，关闭73.499秒。9:36成分归档1408/1802、已耗51.639秒；最终最后一次空归档耗时0.09秒不等于全部关闭耗时。安全退出已确认，关闭性能仍待后续，不能沿用本机合成2.489秒当现场结果。
- 完整名单300/50/500/1000，仍有214只未分类；当前权重原始日期{"IF": "2026-11-02", "IH": "2026-10-30", "IC": "2026-10-30", "IM": "2026-10-30"}，不把旧权重当准确昨日。Wind Connect/ETFs/Nav complete，Indices partial；ETF排名日11-09，IOPV/份额/PCF仍需可靠定义。

## 用户新口径与本轮实施

用户明确希望用各品种00/01/02/03连续档位，每日一个年化样本，与前20/60交易日比较；历史缺分红暂0、随后补齐。此最新指令覆盖旧文档“历史缺D一律阻断”。当前算式仍100*(F-S+D)/S*365/T，当前D不补0；价格/映射缺失不跳过，真实D冲突不当缺失，T<5仍规则排除。

历史按每天实际合约重建非复权连续档位，一天一个收盘年化，当前日排除；等值半权分位=100*(小于当前个数+0.5*等于个数)/有效样本数。历史当时可用D优先（含原有明确0/有来源前序继承）；确实缺D时派生计算用0，source_kind=historical_missing_zero_estimate，绝不向records.sqlite写伪分红。窗口输出estimated、zero_dividend_count/dates/rows及dividend_observations_complete。complete仅指估算输入可计算，Local.history_dividends_complete继续报告真实覆盖，不冒报真实D齐备。

后续导入历史旧日表时，按实际修订/输入键替换相应占位并重算，旧派生缓存版本保留。今日新D不回填过去；同日冲突继续阻断。当前年化、原独立App/Excel、研究32/A02、回测因子/CTA和执行口径不受此次估算改变。

期货卡直接显示D及来源表日期，早于价格日标“沿用”；按用户最新要求数值旁不放“估”，补零天数保留于悬浮和诊断。Overview分别列估算窗口和零占位行、当前D来源/业务日/实际合约/SHA。保持原质量门槛、字体与离屏测试。

## 验证与下一步

230项受影响回归通过，46.355秒，无跳过，ResourceWarning作为错误。9项新增回归覆盖16档每日样本、真实0与缺失0区分、补旧历史D替换派生键、今日新D不重写过去、冲突/缺价/映射/当前D仍阻断、独立中位秩、离线审计与UI标记；另含分红迁移/调度/导入、既有安全打包和排空。1580/860卡片已离屏生成查看，无截断，证据见APP_VALIDATION。

公司更新后按 [APP_COMPANY_TEST](APP_COMPANY_TEST.md) 的runtime开窗/关闭后Overview及安全ZIP复测即可；已通过的Y源不必反复全量重测。此次价格齐备且缺项仅历史D，预期16个60日窗口可估算；公司新代码实际数字仍待回传，不以本地测试宣称已验收。分红表要比较同一B1/实际合约，当前最新来源仍11-06，不自动导入另一份旧Excel覆盖。

## 保护与路径

默认源Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，业务日Sheet1!B1；实际DisplayRoot为\\192.168.91.230\FTPServer，不猜拼、不重映射。09:00/15:30有界同步、SourceDirectory/InputFile语义保留。默认Overview离线，实时VPN手动；DDB仅真实价格缺口，不能为缺D重复下价。

本机P:/project/swhy/Delta1/company-apps-worktree；公司Git根D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard，LocalRoot为其下dashboard/localsetting/app。入口start_presentation.vbs/public。原配置/凭据/数据/Excel、其他模块/worktree、四受保护提示词不动；研究32/A02暂停且保留，不强杀写入者、不删锁，不reset/clean/全量stage/强推。APP_RELEASE.backtest和其他研究文件原样保留。

本轮8,453个文件、365,738,904字节在修改前冻结SHA，发布前逐个复核；原ZIP/真实报告不提交。证据仅在忽略的local_artifacts/validation/company_20261110。七份旧说明与MANIFEST仍 [唯一归档](../docs/archive/2026-10-29/README.md)，不重复制造归档。下一对话先读 [接续提示词](docs/NEXT_COMPANY_RETEST_PROMPT.md) 与本页、AGENTS、公司步骤和发布清单，再核验最新Git/远端。

## 用户后续ETF与显示要求已实施

数值旁不放“估”，占位标记仅保留于悬浮与诊断；概览顶部与期货卡直接显示最新/实际分红表日期。ETF主位优先有效盘中折溢价，无则显示带日收盘折溢价；日期等于准确昨日时才叫昨日。规模/同指数占比/买卖价差加重，原IOPV、盘中premium及轨迹保持真实含义。

份额/净申赎数据尚无可靠定义，改为当前展示三只ETF的两期已披露规模变化，按代码匹配当前三只，列各自前期/本期日期和CNY/百分比变化，不显示全体ETF申购合计。规模变化含净值涨跌，不标份额或净申赎；仅一期明确待前期规模。历史只读现有参考archive，最多64文件/32MiB、单文件4MiB，冻结到当前资料取得时刻、排除未来档案、冲突不任意选值，有界结果/缓存代次有诊断，不猜字段、不新开接口。

包含ETF新增11项在内，最终230项完整回归通过（46.355秒，无跳过，ResourceWarning作为错误）。前219项为追加ETF前的中间验证，不能充当最终结果；65项ETF/页面针对性检查也通过。1580/860概览与ETF页面已离屏查看，当前截图数值无“估”，收盘溢价/来源日、突出数据与三只规模变化可见；小屏滚动重排保持。
