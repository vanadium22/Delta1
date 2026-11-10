# 下一对话：公司分红与ETF显示复测

2026-11-10。先完整读本文件，再读根/dashboard AGENTS、PROJECT_HANDOFF、APP_COMPANY_TEST、APP_VALIDATION、APP_MARKET_OVERVIEW、APP_RELEASE和COMPANY_SYNC。工作区P:/project/swhy/Delta1/company-apps-worktree，统一分支codex/company-apps，基线12f34f1，实际新提交看Git/远端及交付回复。本轮批次2026-11-10-company-dividend-history-and-etf-display。

## 可复制接续提示词

请继续Delta1公司看板。必要实施、测试和精确清单提交推送授权持续；先核验最新分支/worktree/status/diff/远端，保留并行工作、其他模块及四份受保护提示词，不从旧版本重做，不reset/clean/全量stage/强推。

最新完整公司包20261110_092411_072_safe_094017_545_23667ca4.zip为33份JSON、full/Complete=true、无MissingReports，HEAD及8份diagnosis=12f34f1。Y Share complete，匹配B1=10-27/10-30/11-06三表；库64条/4版本含旧本地09-18，本次Import新增0/unchanged4是内容已在库。最新源11-06，未发现11-09/10文件。16当前D源合同与卡片实际合同全一致，均来自SHA09c72b6a56b57a5e18b2f40a91ecf0d54e2341f0f483900d9961f2500d8f62b2；9:36的16实时年化独立复算吻合。用户补充可能比较了旧分红表，仍在自查，不盲改当前公式或映射。

本轮用户新要求覆盖旧历史严格缺D门槛：00/01/02/03每交易日一个收盘年化，历史确实无可用D暂0并标估算，慢慢补齐。当前100*(F-S+D)/S*365/T不变，当前D不补0，价格/映射缺失与真实D冲突仍阻断，当前定价日排除、T<5规则排除、等值半权。原有明确0/有来源前序继承优先。派生历史占位不写records.sqlite；历史旧日真实表导入后按修订键重算占位，今天新D不回填旧日，旧缓存版本保留。原独立App/Excel、32/A02和回测因子/CTA/执行口径不变。

UI分位数值不放“估”，补零信息保留于悬浮和诊断；窗口zero_dividend_count/dates/rows和estimated留审计；dividend_observations_complete与数值complete分开，Local.history_dividends_complete仍反映真实覆盖。卡片显示当前D/来源表日，旧于定价日标沿用。9:36原20日16档完整，60日16档均只缺D，00各20日、其余各29日，共428条，缺价/映射0；新估算逻辑预期可算，但公司新数字仍需更新后Overview，不能用本地测试冒验收。

同运行9:36开窗与9:40关闭后已完整回传，最终closed/shutdown.complete=true/等待者空，耗时73.499秒。最后一次空归档0.09秒不等于全部耗时；9:36归档1408/1802、已用51.639秒。安全关闭确认，现场性能仍待后续，不拿本机合成2.489秒替代。名单齐，214未分类；权重日期仍旧，不臆造准确昨日权重。Wind Connect/ETFs/Nav complete、Indices partial，排名日11-09；IOPV/份额/PCF仍需已核验字段/单位/带日定义。

230项回归通过（46.355秒，无跳过，ResourceWarning作为错误），包括新历史补零/回补/审计/标记和既有Y迁移/导入/连续分位/排空/安全打包；1580/860卡片离屏已看。公司按APP_COMPANY_TEST第1/4/5节runtime更新→正常开窗Overview→正常关闭等排空→关闭后Overview→安全JSON ZIP。OutputDirectory直接保存本轮，packer检查记录时间/HEAD/配置与同一report_path，Complete/MissingReports不冒报。不向旧git.json目录混新HEAD。Full数据阶段按需。

正确源仍Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，年份目录匹配xlsx、业务日以B1。公司DisplayRoot为\\192.168.91.230\FTPServer，仅证据，不重映射或猜拼。旧内置默认运行时迁移、自定义/空白/原配置保留、09:00/15:30有界同步和SourceDirectory/InputFile语义保留。默认Overview离线，实时VPN手动，DDB仅实际价格缺口；不因HTTP失败切DDB，不因缺历史D重复下价。

原数据/缓存/配置/凭据/Excel、其他工作及四提示词不动。APP_RELEASE.backtest字段原样保留，本轮无研究文件改动。七份旧说明与MANIFEST仍唯一SHA归档，不复制旧说明。证据在忽略的local_artifacts/validation/company_20261110。没有公司新估算报告时，只确认旧代码本次源和映射已核验，新分位仍待真实回传。

## 用户后续ETF与显示要求已实施

数值旁不放“估”，占位标记仅保留于悬浮与诊断；概览顶部与期货卡直接显示最新/实际分红表日期。ETF主位优先有效盘中折溢价，无则显示带日收盘折溢价；日期等于准确昨日时才叫昨日。规模/同指数占比/买卖价差加重，原IOPV、盘中premium及轨迹保持真实含义。

份额/净申赎数据尚无可靠定义，改为当前展示三只ETF的两期已披露规模变化，按代码匹配当前三只，列各自前期/本期日期和CNY/百分比变化，不显示全体ETF申购合计。规模变化含净值涨跌，不标份额或净申赎；仅一期明确待前期规模。历史只读现有参考archive，最多64文件/32MiB、单文件4MiB，冻结到当前资料取得时刻、排除未来档案、冲突不任意选值，有界结果/缓存代次有诊断，不猜字段、不新开接口。

包含ETF新增11项在内，最终230项完整回归通过（46.355秒，无跳过，ResourceWarning作为错误）。前219项为追加ETF前的中间验证，不能充当最终结果；65项ETF/页面针对性检查也通过。1580/860概览与ETF页面已离屏查看，当前截图数值无“估”，收盘溢价/来源日、突出数据与三只规模变化可见；小屏滚动重排保持。
