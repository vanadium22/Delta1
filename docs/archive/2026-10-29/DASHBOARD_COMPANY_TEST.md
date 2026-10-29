# 2026-10-28 第三批：公司更新后从这里验收

先正常关闭旧看板，在原公司Git根执行git pull --ff-only，原入口重开。现有同级页为“概览 | 指数 | ETF | 股指期货 | 行情分析 | 数据更新/设置”；研究32项/A02继续暂停并保留源码。前两批的逐日分红、非交易参考、20卡及新图标继续有效。

完整可复制的分红Share/Import/Local、指数/ETF只读阶段、新ETF能力CMD、字段定义文件及行情分析步骤见[公司数据能力与行情分析验收](docs/DATA_CAPABILITIES.md)。当前仍需公司Import公盘历史D并Local核验；开发机不可达不代表公司不可达。

新入口可直接运行：

```powershell
$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage Local -NoPause
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage ETF -NoPause
```

默认Local离线；显式ETF测试90秒且只读，不发布、不订阅或改VPN；无经核验IOPV/份额/PCF定义时mapping_required属真实缺输入，退出2查看JSON，不用重录凭据。正常Wind任务才会发布资料，指数缺项每日有界修复，成分行情一分钟更新。请回传capabilities.json、分红JSON，以及保持窗口运行时同次overview.json/diagnosis.json。原-WindStage及默认-Overview行为保留。

行情分析点击后才按选定标的/窗口请求，默认今日；VWAP先确认量额单位。期货仅本地日线，不能当已支持分钟/VWAP。查询、取消/关闭与缓存结果需公司实际验收。旧章节的“仅分析”“三个子页”“固定分红情景”等为历史状态，以本节和最新规格为准。

# 2026-10-28 第二批：新概览与一键快捷方式

公司正常关闭旧看板后git pull --ff-only，仍从原入口启动。现在默认“概览”为4指数＋16期货卡，指数/ETF/股指期货为右侧同级详情；每卡“去分红年化基差”下有较昨日变化，两档分位保留。左上时间是行情参考时点，不是页面重绘；详细时点可悬浮查看。行业/ETF能力和行情分析待第三批，不能以本批页面变化声称公司缺数据全解决。

在公司Git根一键生成/更新桌面入口：

```powershell
./dashboard/create_desktop_shortcut.cmd -NoPause
```

自动定位真实桌面，生成Delta1股指看板.lnk，目标dashboard/start_presentation.vbs，显式public；已有本看板LocalRoot保留，无已有链接时优先dashboard/localsetting/app。特殊配置可加-LocalRoot真实目录；不改native.json，不启动程序，不覆盖其他应用入口。新链接验证后替换原件，旧链接备份在dashboard/runtime/shortcut_backups，原图标不留额外桌面入口。新图标资产随Git发布，勿复制开发机配置。

建议验证860/1440/1920窗口、概览上下滚动、同级详情切换、四品种/空值清空，以及同一实际合约的较昨日点基差。历史D未齐按下方第一批Import后Local复核；缺D不能通过最新表回填过去来消掉。公司真实刷新与数据仍回传同次Overview+diagnosis。

# 2026-10-28 第一批：公司分红导入与非交易复测

更新后仍用原入口，先在公司根目录git pull --ff-only，LocalRoot沿用dashboard/localsetting/app。当前已实施逐日分红/历史缓存/连续分位/非交易参考；20卡等其余需求继续下一批，暂不以旧页面标题判断新数据逻辑未更新。

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Share -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Import -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -NoPause
```

Local不连接接口；Share只读公盘、临时验证，不发布；Import是明确的本地追加导入，不改公盘/源Excel/个人配置/原库。默认公盘\\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026，匹配指数基差情况_*.xlsx；内联设置可修改目录/规则/早午时刻。新库在LocalRoot/overview_dividends，raw按SHA归档，records.sqlite及derived.sqlite分别保存历史分红与派生缓存。相同内容不重复解析/复制；同名日期文件的后续版只影响生效后。正常看板也会上午/下午各自动检查，成功不重复。

请回传各次输出路径中的JSON，重点看history_dividends_complete、16档dividend_missing/mapping_missing、记录首末日期及Share错误阶段。退出2表示输入/覆盖尚未完整，不要删库或重填凭据。Share在开发机实际WinError53，不能据此断言公司路径错误。若公盘文件规则不同，先回传文件名清单并修改对应规则，不拿最新一表代替过去。

保持看板开着，在午休/盘前盘后检查期指年化和20/60：有合法缓存配对或共同收盘即显示参考，源时/价格日不推进，不冒称实时；无D仍明确分红缺项，不能造0。新数据已导入后再用原-Overview导出同次overview.json+diagnosis.json，默认仍离线。三秒主采集、一分钟成分、实时30秒/3秒不变；真实公司历史导入和持续运行仍待回传。

# 2026-10-28 下一轮测试入口说明

本轮按用户要求先分析、生成新对话提示词；没有实施新公盘同步/ETF能力入口或界面改动。现有可执行Overview、Indices、ETFs、Nav命令及公盘只读查看步骤，见[新交接的公司测试节](docs/NEXT_OVERVIEW_IMPLEMENTATION.md#现在已有的公司测试命令)。旧-Overview继续离线；Nav需已发布ETF名单。公盘/ETF净申赎/PCF/IOPV及新行情页的一键能力测试须下一对话真实实现后提供，不能以旧阶段成功当成新功能验收。

当前开发机无WindPy、公盘外部限时探测WinError53，未执行公司SDK/API测试。用户现已授权所有必要测试，可在公司运行回传。回传仍需同次diagnosis，不因旧状态文件断定当前窗口/提交；下方10月28日步骤对应35716e3运行版本，不包含本次十项新需求。

# 2026-10-28 当前公司验收

本节覆盖下方旧对数年化、研究页及全分钟补库操作。已完整读取这次4份JSON和Excel：公司是468033a，ETF规模阶段complete但published=false；指数名单已全返，权重缺项/旧日期导致原整组拒绝。新源码保留概览全部计算和20/60分位，研究页暂时暂停。

1. 正常关闭旧看板并等原任务退出，在原公司Git根目录更新一次：

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
git log -1 --oneline
$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
```

2. 仍用原dashboard/start_presentation.vbs。应只看到市场概览和数据更新/设置，不再加载三个研究页；指数、ETF、股指期货三个概览子页和20/60分位保留。期指标“实际基差 / 简单年化”，四卡仍为实际合约，计算(F-S+D)/S*365/T。当前和历史分位采用相同固定分红情景，缺D沿用前一到期合约，明确0优先，悬浮可查继承来源。
3. 如果要使用本次附表的G列，在内联设置填“概览分红Excel”为公司电脑该文件的实际路径。字段留空仍使用原分红目录，程序不会擅自改原配置或覆盖旧表。保存时先按提示等后台安全暂停，再保存。文件名虽含09-18，本次Sheet1!B1缓存日为2026-10-28；请以缓存日期/C列合约/G列点数为准，不把E列覆盖独立合约参考。
4. 保持日常Wind终端登录。新版正常流程会再尝试一次周频资料，名单不再因少量缺权重全丢；行业/股票快照需要等待下一分钟采样。ETF规模前三仍须从正常任务实际发布后才进入订阅，只读阶段成功不会发布。必要时按DDB一键补齐：仅填概览所需日线，先本地复制再按真实缺口用DDB，不下载研究分钟/秒历史或重写原深核记录。实时不等待周频Wind完成；实时VPN仍手动。
5. 连续交易保持窗口10–15分钟：主行情应按三秒请求（不代表源端必定每次改变），股票采样约60秒独立进行；切IF/IH/IC/IM、缩放/滚动、暂停/恢复及关闭应正常。源时、接收、计算和页面刷新分开，30秒/3秒规则未放宽。D缺项应列“分红缺失”，不当成价格缺口重下。最早无前序合约D时不能造值。
6. ETF新增“收盘折溢价”，只用同日未复权收盘和单位净值并显示日期；盘中IOPV仍须明确字段/映射，净申赎/PCF仍缺可靠输入。本机只用假SDK验证新nav字段链路，真实公司字段/日期及发布须核验。正常资料发布后，可显式运行只读日频净值阶段：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Nav -WindDay 2026-10-27 -NoPause
```

固定27日便于在28日对比；不发布资料、不改配置/VPN、不连接HTTP/DDB。返回nav.expected与same_day应覆盖已选规模前三；失败回传安全阶段/ErrorCode即可。此测试从已发布ETF名单选择代码，名单尚未发布时不会猜代码。盘后当天净值未披露保留旧日期，次晨可有限重试。

保持看板开着，导出当前概览：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -Overview -NoPause
```

回传同次overview.json+diagnosis.json；若跑了Nav，再加该次wind.json+diagnosis.json。默认-Overview仍不请求接口。新报告含简单年化/分红来源、分位D缺项、主请求interval_seconds=3，以及历史scope=overview_completed_closes_only、research_downloads_enabled=false。Indices即便权重未齐也可有完整名单，不能把partial误当名单0；真实公司三秒/关闭性能与行业/NAV可用性不以本机回归代替。

# 2026-10-27 14:46 / 14:55 新回传后的复测

这8份新文件已完整解析。四份同次diagnosis确认公司源码638ee82。Connect成功；Indices接口均ErrorCode=0但三组权重无效、IH行日期不符；ETF候选1310、跟踪映射匹配66且未解析0，指定10月26日规模返回ErrorCode=0但矩阵校验失败。14:55两个样本24/24报价新鲜、20个标的源时推进，16个实际合约20/60分位可计算；短样本仍不能通过10–15分钟持续运行验收。

本批修复单日多证券标准1×N矩阵被本地误拒绝的问题，同时修正WSET为紧凑日期+明确字段，增加行日期、空/无效/负权重数量、权重和及矩阵形状。指数具体原始行尚未回传，不能断言日期字符串是唯一根因；无效日期、缺权重或缺规模仍不发布。

这次Connect无需重复。保持日常Wind终端登录，正常关闭看板并等退出；在公司PowerShell复制以下命令，每项等结束后再执行下一项：

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
git log -1 --oneline
$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Indices -WindDay 2026-10-26 -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage ETFs -WindDay 2026-10-26 -NoPause
```

固定10月26日便于和本次报告比较，盘后也不会改查27日。`-WindDay`只对显式Wind只读阶段生效，拒绝未完成日、周末/假日和未知日历；不改变正常App取数日期。两次都保留各自新输出目录的wind.json和diagnosis.json。期望Indices完整300/50/500/1000及行业/基准收盘，ETFs四组各有规模前三；`published=false`正常，这两个测试不发布资料、不改配置/VPN、不连接HTTP/DDB。

失败也回传对应文件即可。新诊断的returned_dates来自SDK Times，WSET不能以它代替数据行日期；returned_row_dates、missing_row_date_count、missing_weight_count、invalid_weight_count、negative_weight_count、weight_total和matrix_rows/matrix_row_lengths才用于进一步定位。原始数据、连接异常和凭据不回传。若日期仍不符或权重仍缺，保留空项，不把ErrorCode=0当资料完整。

测试完成后通过原dashboard/start_presentation.vbs打开看板，正常流程会按更新后的任务协议重新尝试一次；可点击DDB一键补齐发布有效Wind资料及补实际缺口。只读测试的固定日期不会用于正常发布。只在原DDB目标确有缺口时连接DDB，实时VPN仍手动。保持看板开着，再运行：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -Overview -NoPause
```

回传这次overview.json+diagnosis.json，以及上述两次Wind各自一对，共3个新目录、6个JSON。默认-Overview仍不连接接口。10–15分钟主行情/分钟行业采集请在下一次连续交易时段验证；当前盘后只核对收盘参考，不以刷新时间冒充源时。IOPV、净申赎、PCF仍缺可靠输入，未用替代值填充。

# 历史：overview (3) 回传后的逐步测试

新报告14:18采样，当前16档历史20/60全部完整，独立收盘缓存待补已为0；无需按旧1120清单重新补库。24个行情最新接收停在13:03:33，历史状态于13:03:38记录closing/stopped，没有已记录请求失败；这不证明采样时窗口仍开着。Wind仍是12:53失败的历史记录，没有新阶段证据。只读诊断不会启动采集或重新查询Wind，下面把两种测试分开执行。

1. 如有旧看板，正常关闭并等它退出；保持日常Wind终端已登录。在公司打开PowerShell，复制执行：

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
git log -1 --oneline
$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
```

2. 每条等结束后再执行下一条。三个命令只读取Wind低频接口，不发布资料，不改配置或VPN；无需为了测试切换网络。

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Connect -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Indices -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage ETFs -NoPause
```

Connect检查连接，Indices检查四指数成分/权重/行业与指定已完成日基准收盘，ETFs检查同指数全集及规模。每阶段上限180秒。每次控制台会显示新报告目录；保留其中wind.json和diagnosis.json。若Connect明确报错，可先停止后两项并回传该阶段结果；连接状态null只是没有读得该状态，不能直接判断断开。各阶段published=false为正常，测试本来不发布资料。

3. 双击公司原dashboard/start_presentation.vbs打开看板，点击一次DDB一键补齐并等待结束，让正常流程发布Wind资料并补实际缺口；随后按当前网络验证并开始实时。仅Wind只读测试成功不会直接改变页面。看板仍按既有DDB按缺口自动、实时VPN手动规则运行，不额外切换实时VPN。

4. 交易时段保持看板打开观察10–15分钟，核对主行情源时间推进、行业分钟快照与覆盖、四张实际合约的20/60分位。源时间与页面刷新时间分开；陈旧/缺腿时当前年化和分位继续留空，不改30秒/3秒。连续交易是09:30–11:30、13:00–15:00，盘后只检查参考模式。

5. **保持看板开着**，回到同一个PowerShell执行：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -Overview -NoPause
```

回传三个Wind阶段各自的wind.json+diagnosis.json，以及最后概览的overview.json+diagnosis.json。共四个新输出目录，保留目录关系打包这8个JSON即可；不要只回传overview。若某阶段失败，保留失败报告即可，不重装环境、重录凭据或删缓存。默认-Overview继续不连接接口、不改VPN。

# 2026-10-27 当前验收与显式Wind分阶段只读入口

本轮已读取11:32–11:33的公司overview (2).json，属于午休；不能因两样本源时不推进判断断网。没有同次diagnosis，无法确认公司HEAD/正在使用窗口版本。WindPy已安装，具体WindError原因须看新阶段/错误码，勿重装环境或改用Oracle。16档20/60连续历史已齐，1120行只是独立缓存待补；unknown_groups=12600仍不是分钟深核完成，allow_unverified保持原值。

在原公司Git根目录更新，先执行默认离线检查：

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
./dashboard/diagnose_presentation.cmd -Overview
```

回传这次输出目录的overview.json和diagnosis.json。默认程序不连接Wind/HTTP/DDB，不改配置/VPN，不启动窗口。新字段包括真实交易阶段、缓存可本地复制/复制后仍缺、history_only历史窗口，以及page_calculation_preview（正式引擎计算预览，不证明运行UI已应用）；后台报告中的计算和页面时间仍保留原时间，不认证进程存活。预计公司午休phase=lunch、checked_in_continuous_session=false，即使checked_in_access_window=true。

需要定位Wind时，在保持日常Wind终端已登录的公司电脑**显式选择**以下阶段，每次等待结束后再进行下一项：

```powershell
./dashboard/diagnose_presentation.cmd -WindStage Connect
./dashboard/diagnose_presentation.cmd -WindStage Indices
./dashboard/diagnose_presentation.cmd -WindStage ETFs
```

每次仅读取Wind低频接口并生成独立wind.json+diagnosis.json；不发布参考快照、不修改配置/缓存/凭据、不连接HTTP/DDB或操作VPN。Connect只检查start/isconnected；Indices读取完整成分/权重、缺失行业及指定已完成日基准收盘；ETFs读取同指数候选/跟踪映射和同日规模。每阶段上限180秒，失败/超时保留最后安全调用，原SDK消息不回传。ErrorCode=0但status=invalid_response是字段/数量/日期校验未通过；连接状态null表示未读得该状态，不等于断开。profile_files_unchanged应为true，published始终false。请回传失败阶段的wind.json与同次diagnosis.json；不要回传native.json、凭据或原始连接异常。

资料实际发布仍通过重开原dashboard/start_presentation.vbs后点击DDB一键补齐。更新后的正常低频任务会重新尝试一次，此后保留每周限制；显式补齐可重试。完整四指数数量300/50/500/1000、分类、基准收盘及ETF同日全集规模齐备后再验行业贡献/规模前三；ETF两个跟踪字段互补可以补全，仍未解析的候选不能忽略。缓存先从已有有效标准历史复制，仍缺才按原政策准备DDB；别按旧1120清单手动重新下载。

页面验收仍用原蓝白入口：IF/IH/IC/IM切换后四张实际合约与00/01/02/03对应，20/60两行年化分位一致，窄宽窗口及滚动正常，清空后不残留。09:29仍显示实际已完成收盘参考；午休原源时保留且不标实时；连续交易使用30秒/3秒；暂停/关闭时源时不被重绘推进。实际源时间、接收时间、计算与页面应用分别核对。盘中主行情及行业分钟采样持续10–15分钟仍待现场，未以本机回归代替公司通过。IOPV/净申赎/PCF仍缺可靠输入。

# 2026-10-27 本轮公司只读检查与四档分位验收

用户已明确卡片继续显示实际合约，00/01/02/03只作统计档位。公司先在原Git根目录执行一次 `git pull --ff-only`，再运行：

```powershell
.\dashboard\diagnose_presentation.cmd -Overview
```

该程序只读已有配置、发布历史、参考与行情缓存，不启动看板，不连接Wind/HTTP/DDB，不操作VPN，不改设置或删除数据。完成后回传同次新输出目录的 **overview.json 和 diagnosis.json**；不要回传native.json或凭据。无需为了此检查切换或断开正在用的网络。overview.json新增data_gaps，能区分已确认的缺日/缺标的、Wind名单/规模/行业、当前期现不同步、旧扫描/版本不符，以及未配置的IOPV/申赎/PCF。旧报告没有该字段，不能代替此次检查。

本次程序尚未真实测试公司接口，报告中DDB远端供给为not_tested；“缓存待补”不等于源表没有数据。Wind名单未取得时，全部成分股缺口是待确定，不能算0。历史分钟库存只列日期/已有扫描，不冒充新完成分钟深核。

更新后重开原VBS，期指卡片仍为实际月份（如IF2703/IF2706），角标显示对应02/03。四张卡都显示20日、60日年化分位，悬浮能看有效样本数/窗口/规则排除/真实缺口；换品种后实际合约与档位必须一起切换。T<5时年化及当前分位继续留空，属于规则而非缺历史；其他缺价/缺映射不跳过。最新实时报价与实际收盘参考的边界不变。若需补历史，仍用原DDB一键补齐；本轮扩充到四档前60交易日所需收盘，优先复用可用本地标准历史，未取得历史挂牌/到期档案则明确待参考资料，不猜合约。

公司回传后再根据实际的最新提交、数据目录、WindPy环境/字段和缺口日期定位修复；本机离屏结果不当作公司实测通过。

# 2026-10-26 最新数据补齐验收（Wind终端 / WindPy）

本节覆盖下方旧Oracle依赖判断和只在盘中请求报价的说明。本机模拟与离屏通过不代表公司实测通过。

1. 在公司原Git根目录执行一次 `git pull --ff-only`，重开原 `dashboard/start_presentation.vbs`。不切分支、不重置目录或清理行情。旧看板仍按原安全退出流程接管。
2. 保持日常Wind终端登录，点击顶部 **DDB一键补齐**。本周资料有效则复用；缺失/上次失败可显式重试。先取得成分/权重、缺失行业、同指数ETF规模，再安全排空实时任务并补DDB实际缺口。只有DDB确有缺口时自动使用已有数据VPN。不要手动操作程序进程或锁文件。
3. WindPy Python与看板Python可以不同。若诊断 `wind_setup.module_available=false`，在“数据更新 / 设置 / 诊断”展开本机数据/Wind/DDB设置，只把 **WindPy Python** 指向公司原本可用的python.exe后保存，再补齐；不安装Oracle驱动、不重装Wind、不覆盖原环境。WindPy任务不带-s、不调用WSQ/WSI。
4. 核对更新页的概览收盘目标和剩余条数。当天15:10前补至准确上一交易日，15:10起可补已结束的当天。源表尚未发布/无有效记录时仍显示pending，不能据进程退出认为全部完成。继续点击补齐会跳过已有的有效日/标的；原始下载、旧缓存修订及所有原行情保留。
5. 盘中验证指数/新规模前三ETF源时间持续推进，成分快照约60秒一次，并查看权重覆盖数。缺行情、未知行业不填零；完整行业才参与排名。滚动权重标“估算”，悬浮查看官方日期与固定成分/股本假设；因子变化或缺基准价时贡献仍留空。
6. 盘前盘后点击 **更新报价** 或等待自动有限快照。卡片区分“收盘 / 快照 / 缓存”，保留完整源日期、实际取得时间和推定依据；HTTP不可达保留旧值、60秒重试且不弹盘中VPN提醒。已补同日DDB收盘后，期指基差/分位按该定价日显示“收盘参考”，不冒称实时。
7. 在原Git根目录运行 `./dashboard/diagnose_presentation.cmd -Overview`，回传新输出目录 **overview.json + diagnosis.json**。新增WindPy解释器/模块存在性、日期化收盘缓存/缺口、盘后快照时间及权重方法；诊断自身不导入WindPy、不连接HTTP/DDB、不登录Wind或改VPN。不要回传native.json、数据库密码或凭据文件。

待公司确认：Wind实际板块/标的指数/规模字段及权限，四指数完整300/50/500/1000样本、ETF规模全集和日期，DDB当前数据发布时点、10–15分钟主行情与分钟成分持续采集。现有HTTP仍未提供可核验IOPV，净申赎/每日PCF也无已核验输入，继续明确缺项；成交量、规模变化、昨净值和DDB历史折溢价字段均不冒充这些数据。

# 2026-10-26 三页预览对齐及公司报告跟进

期指现已补齐第三张预览中的四到期卡、年化期限结构、基差变化与成交分布。仍用原蓝白展示入口，不改第六版公式；缺昨日/五分钟前同步输入或完整成交时明确缺数，缺历史不遮住主价，昨日持仓不以实时零值替代。

本次报告中“规模日期晚于当前日”实为缺资料提示错误，已经修正；Wind.status=not_recorded不能当作连接失败。采样15:15但最后接收13:46，当前尚未确认所用窗口、配置或停更原因。

在原Git根目录git pull --ff-only，重开原start_presentation.vbs，看到页面后再运行：

```powershell
.\dashboard\diagnose_presentation.cmd -Overview
```

请同时回传新输出目录的overview.json和diagnosis.json。诊断新增实际配置/数据路径、各配置历史后台状态、低频调度等待原因及尝试/依赖/设置存在性；只读、不读取凭据内容、不连接HTTP或Wind、不操作VPN。盘后可检查这些状态；行情持续推进需在交易时段验证，不能将旧后台报告当成当前进程存活证明。

# 2026-10-26 指数 / ETF 新概览验收

本轮按用户已确认蓝白草图改版指数和ETF，期指及第六版公式保留。本机离屏验证不等于公司通过。

在本文件原公司Git根目录执行git pull --ff-only，重开原dashboard/start_presentation.vbs。核对：

1. 指数页四卡、行业贡献及权重、行业内个股明细显示；点指数及行业后身份一致。缩放至860/1100/1440/1920宽度并纵向滚动，无覆盖或横向截断。
2. ETF切四指数，每组最多三只规模卡。排名需完整同指数同日规模资料，显示日期；未取得时明确待核验，原代表不冒充规模第一。
3. 盘中看主卡源时间推进，行业分钟快照约60秒更新，二者与页面刷新时间独立。报价缺失显示覆盖率；权重早于准确昨日时贡献留空，不冒用周度旧权重。跨日权重滚动尚待后续实现。
4. IOPV先核验现有源；无字段/映射时待接入。缺IOPV、历史或成分行情均不拖住主价。申赎、成交额未核验的单位和日频资料不能显示假值。
5. 正常入口每周后台核验一次Wind低频资料；不自动切任何VPN，不安装或升级Wind。连接/字段/单位不齐时保留原快照并留缺数。本机此次未取到真实Wind资料，公司结果待回传。

在**原Git根目录**运行：

```powershell
.\dashboard\diagnose_presentation.cmd -Overview
```

回传输出目录的overview.json和diagnosis.json；如overview_exit_code非0，再附overview.stderr.log。此命令只读已有库/原始响应字段名及两次源时、规模/权重/覆盖/Wind状态；不发接口请求、不改VPN、不启动第二个看板，不需要为了诊断额外连接VPN。正常看板的行情连接仍按原网络可达性及手动实时VPN规则处理。两样本只用于排查，不证明10–15分钟持续运行。

# 公司展示版：第一阶段交付与现场测试

13:07公司报告已看到多个早于ETF版/接管版发布的旧App进程，网络锁文件唯一登记使用者也是旧展示版。更新后必须重开原VBS触发接管；旧进程不会因git pull更新。-Routes现可在DNS缓存为空时，用核验看板进程在行情端口的现有TCP连接查询实际所选网卡/网关，仍不发网络请求。无当前连接或读取受限时继续明确缺证据，不操作VPN。

## 2026-10-26 重复打开、ETF与公司网络检查

最新反馈为App已打开，但新窗口取得网络锁时报errno13，指数源时仍推进，ETF四卡无数值。当前修复加入安全替换同数据范围旧App、旧版正常关闭兼容、明确采集归属、ETF无观测提示和锁操作阶段。公司真实锁持有者及网络路径仍待报告；本轮不提前扩展指数/ETF概览布局。

1. 在原Git根目录执行 `git pull --ff-only`，重开原 `dashboard/start_presentation.vbs`。正常实时入口会先请求旧看板退出，等待采集/计算/写入结束后接管。慢任务可能需要等待，超时新窗口只读；Excel和其他项目不会关闭，不删锁或强杀。
2. 核对旧看板退出、顶部“本窗口持续采集”、ETF四卡报价及“行情源”时间推进。显示“读取已有行情 · 本窗口未采集”仅证明现有库有新观测，不能证明本窗口采集成功。
3. 公司网络可直接访问行情源时不需要额外连实时VPN，程序验证当前连接后直接使用。程序不自动操作实时VPN或为实时重试切回DDB。不要为了判断是否直连而主动断开正在使用的网络。
4. 核对公司实际网卡/网关与锁使用者，在原根目录运行 `.\dashboard\diagnose_presentation.cmd -Routes`。输出目录的connection.json包含所选App配置、锁文件访问/使用者、当前DNS缓存目标IP的所选路由与网卡；不发DNS/TCP/HTTP、不改路由/VPN。无法读取时明确unavailable，不推断“公司自带VPN”。公司网关内部是否使用专线/VPN仍需网管信息。

如需单独有限接口测试，先在看板暂停本轮采集，确认无历史任务，再显式使用 `diagnose_presentation.cmd -Routes -Connect`；该可选参数才会请求行情。默认及仅-Routes均不联网。诊断默认优先实际App配置，可用-LocalRoot选原配置；不重新录入或导出凭据。

## 2026-10-26 最新概览验收

本次已按用户要求新增市场概览的指数/ETF/股指期货三子页，展示入口默认public蓝白。页面、口径和数据边界见 [APP_MARKET_OVERVIEW.md](APP_MARKET_OVERVIEW.md)。下文早期“随后再优化概览”的阶段限制不适用于本次明确授权。

公司先 `git pull --ff-only`，重开原 `dashboard/start_presentation.vbs`。若点击无窗口，在原仓库根目录运行 `.\dashboard\diagnose_presentation.cmd`，保留输出目录的 `diagnosis.json`、`preflight.json` 及最新 `run-<PID>` 日志；不要重录凭据、删除锁或重置数据。

本轮重点：四指数卡片、四只代表ETF、期指品种与月份筛选；放大/缩小窗口与滚动无覆盖；源时间推进且页面时间独立；缺今日日线时最新价/源端昨收涨跌继续显示；缺IOPV仅折溢价留空，缺前20日仅分位留空。盘中手动连接实时VPN后观察10–15分钟，联合诊断中的请求、落库序号、计算和页面应用检查持续更新。缺历史仍按原规则自动DDB；实时重试不切回DDB。

当前开发机获准的四轮真实HTTP读测已收到4指数/4ETF/16期指，未改VPN、原数据或配置；此结果不代表公司电脑启动、DDB补库或长期运行通过。

本版先交付现有 App 和数据更新流程。Excel 冻结功能维护，历史源码、模板、成品、数据、分红、缓存、配置全部保留。不要结束仍在使用的 Excel 或其他采集器。本机离屏回归不能代替公司盘中实测；11:07 的有限连接成功也不能证明持续更新。

## 更新与首次依赖检查

公司这个路径本身是 Git 根目录，内部另有 `dashboard` 源码目录：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git pull --ff-only
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\dashboard\prepare_app.ps1
```

检查默认复用 `D:\conda\envs\swhy_delta1\python.exe`。显式 `SWHY_DELTA1_PYTHON` 优先，其次公司环境、仓库 `.venvs/dashboard_app`、仓库 `.venv`、已存在的本机环境、PATH。不会升级 Wind 环境。

如果报告仅缺 Qt/pyqtgraph，执行一次：

```powershell
powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File .\dashboard\prepare_app.ps1 -InstallGui
```

UI 包固定版本安装在仓库 `.deps/dashboard_native`，`--no-deps` 不升级现有数据依赖。完整新环境依赖清单为 `requirements-app.txt`，已有公司环境不应整包覆盖安装。历史 SDK 若缺失，可在 App 内指定已有的历史 Python，或由环境维护人按该清单补齐；等待 SDK 时仍能看已有数据。手动检查报告在 `dashboard/runtime/app_startup/preflight.json`；每次打开 App 的报告和日志独立保存在 `dashboard/runtime/app_startup/run-<PID>/`，无密码。没有出现主窗口时先看最新的运行目录，不会弹出安装或错误对话框。

日常双击 **`dashboard/start_presentation.vbs`**。它隐藏启动控制台，只显示 App 主窗口。命令行或现有快捷方式也可调用 `dashboard/start_presentation.cmd`。两者走同一入口，不依赖 Excel/COM 或开发版。

已修复 Windows PowerShell 将 Python/Qt/采集器的 stderr 普通提示当作致命错误、中断 App 的问题。启动器现在直接隐藏启动子进程，将普通输出和错误输出分开写入 `.log` / `.stderr.log`，不因提示日志结束 App。`run-<PID>/launcher.json` 记录启动阶段和真实退出码，Python 原生崩溃栈也尽可能保存在 stderr 日志。

如果更新后仍自行关闭，先保留最新 `run-<PID>` 目录。`launcher.json` 的 `phase=app_exited` 表示已观察到子进程退出，`exit_code` 为其真实代码；`launcher_failed` 表示启动器自身失败。`app_running` 是启动时记录，不能独立证明进程仍存活。正常日常入口没有15秒或3分钟自动关闭规则，自动退出只用于显式离屏测试参数。公司日志与下面的持续更新报告一起用于定位，不重新录入密码或删除数据试错。

## 数据与自动连接

已有 App 专用配置优先。没有专用配置时，从已验证的 `localsetting/numeric_excel/native.json` 创建一次 App 副本，保留全部公司路径；没有数字版配置的旧本机 App 继续原 `localsetting/native.json`。原配置不覆盖。DDB/VPN 凭据保留原引用，不复制密码，不迁移或重置保护方式。显式 `--local-root` 可选已有配置。

主窗口立即可操作，现有数据在计算线程加载。后台先做发布/覆盖元数据快检，再检查近期三交易日、已知缺口和已变化分片；已核验且身份未变的旧分片复用证据。初次没有新格式覆盖账本的旧历史标明“尚未深核”，不会把旧 0 缺口当新验证。完整历史逐分钟核验通过“数据更新 / 设置 / 诊断 → 完整深核”运行，可取消。

**DDB 自动、实时 VPN 手动。** 有历史缺口时，先检查 DDB 网络；网络已通直接复用，否则自动连接数据 VPN，再用已保存的数据库账号密码补到上一交易日，校验并共同发布。有进展且到期的部分批次自动续批。没有缺口不会为了检查而登录 VPN。数据库账号与 VPN 账号分别读取；前者不能代替后者。

自动数据 VPN 复用公司原 `history_vpn_config`、`history_vpn_trust`、`history_vpn_powershell` 引用；旧 App 副本未保存引用时只读查找原 `numeric_excel` 配置，不重写它。需要当前 Windows 用户可解密的 VPN 凭据、已信任的网关证书、已安装的深信服客户端和 PowerShell 7。路径可在内联设置核对。缺配置、证书不匹配、密码不可用或需要验证码/二次认证时停止自动登录并说明原因；不绕过证书、不弹旧配置向导。显式保留的 `history_vpn_mode=manual` 仍禁止自动登录，默认是 `auto`。

历史会话和登录辅助进程真正退出后，App 有限验证实时接口；若已连通，直接持续采集。若未连通，仅**交易日北京时间09:30（含）–11:30（不含）、13:00（含）–15:00（不含）**弹窗请你手动连接实时VPN，午休、盘前、盘后及休市不弹。你在 VPN 客户端手动切换后，点**“已连接，验证并开始”**；再次验证成功才开始持续采集。选择**“稍后连接（只读）”**则本轮停止自动更新，不反复提醒；之后可在主窗口点“验证并开始实时”。程序不自动退出 DDB VPN、不自动操作实时 VPN，也不会因实时重试而自动切回 DDB。实时失败不会每30秒重复弹窗，同一时段自动提醒至多一次。

“历史任务退出”不必然代表历史全部补齐；请同时看历史状态及剩余缺口。补库失败或未深核时保留原因和缓存，实时仍可按上述流程独立接入。需要继续补历史时主动点“重试历史”，新一日空闲时也会重新检查。

除获准的盘中实时VPN提醒外，设置、路径、数据库账号、进度、取消、重试、公式和诊断都在主窗口。需要更换数据库凭据时在内联设置保存一次，留空密码保留已有值。不会要求从家里复制当前用户加密的密码到公司。改设置前先停止本轮后台并等待完成。旧任务持锁时保留缓存与诊断，不删除锁、不强杀进程。

## 公司请先测试这五项

1. 只打开展示版：解释器、两类历史目录、参考文件、实时目录和分红均指向公司原路径；不需要 Excel/开发版，没有模态向导。
2. 有数据先显示，快检不阻塞主窗口；存在历史缺口且DDB网络不通时，观察“自动连接数据VPN → 认证 → 增量补库 → 校验/共同发布”，已有连接则跳过登录。诊断 `history.ddb_vpn.mode=native_login` 表示本轮自动登录，`existing_tunnel` 表示复用，`state=not_needed` 表示没必要连接；还要看历史目标、剩余缺口和发布状态，不能只凭VPN已连接判定补库完成。缺SDK、凭据不可解密、认证失败、网络不可达分别显示原因。未知/未深核不报完整。
3. 盘中历史任务退出且实时未通时，应出现手动连接提醒；手动切好VPN，点击确认后，核对 **持续采集正在运行、有效数据序号递增、源时推进、计算完成、页面已应用版本**。连续观察10–15分钟；再测试“稍后连接”后保持只读、不重复弹窗。午休/盘后不弹窗；实时已经可达则不必提示。09:29（含）至15:01（不含）的既有实时接入门控、逐行源时/质量、缺腿与同步规则保留；提醒窗口更窄。休市只能验收可用性和正确状态。
4. 测试概览/对应指数、期现/跨期/跨品种现有指标，切换合约、参数、输入 X；打开详情图像和解释/公式。切换后旧任务不覆盖新选择；计算慢时保留明确标注的上一结果，队列最多一个执行和一个最新待处理请求。
5. 断网再恢复、取消/只读、手动重试和关闭重开。关闭会等待本轮采集和历史写入正常结束；不误停其他用户任务。两个 App 可读同一库，但互斥锁只允许一个网络写入者；另一窗口明确等待并读取缓存。

## 有时间上限的诊断

窗口的“导出诊断”保存到该实例 `dashboard/runtime/app_sessions/<运行号>/report-*.json`，路径直接显示在窗口。报告包含源时/接收时间、持久化序号、缓存读取、计算开始结束、页面应用时间、队列和失败阶段，不含密码。`network_policy=auto_ddb_manual_realtime`、`history.ddb_vpn` 和 `awaiting_realtime_vpn` 记录当前流程；登录失败/取消后的 `vpn_changed=null` 表示无法确定隧道是否改变，需看客户端，不能误读为未改变。

需要观察一段时间时，在 Git 根目录运行（15 秒自动退出）：

```powershell
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.app_diagnostics --seconds 15 --output .\dashboard\runtime\company_app_15s.json
```

盘中保持 App 正常运行，执行完整15分钟诊断命令：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.app_diagnostics --seconds 900 --output .\dashboard\runtime\company_app_15min.json
```

最大15分钟，每3秒采样；诊断工具本身不会发网络请求、打开窗口、操作VPN或进程，App仍按当前模式运行。比较 `collection.data_sequence` 与 `applied.realtime_sequence`，再看 `source_times`、`cache_read`、`calculation_seconds`、`ui_applied_at`，可以区分源端陈旧、请求失败、历史占用、读错目录、计算耗时和界面回填。序号递增并不等于源行情新鲜，源日期仍按原接收日推定，质量限制继续生效。

当前状态：**待公司实测**。请先回传主要功能和持续更新反馈；等待期间只修运行/更新问题。指标重构须同时满足公司反馈、你明确继续、最新指标 doc 到位；美术细化也留到公司主要功能实测之后。
