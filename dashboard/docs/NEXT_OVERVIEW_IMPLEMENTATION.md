# 下一对话：概览、逐日分红与行情分析

更新：2026-10-28。本轮按用户要求先分析并生成提示词，**没有实施下面十项产品改动**。本文件可直接交给新对话；最后一节给出可复制的启动提示词。

## 已核验的基线与边界

- 统一工作区 `P:/project/swhy/Delta1/company-apps-worktree`，分支 `codex/company-apps`，远端 `https://github.com/vanadium22/Delta1.git`。分析开始本地/远端为 `a446bbe98f1062379bbadd906bd93511c7242beb`；期间日报任务独立发布，提交前重新核验为 `a16d0afbeae6683e596d983948ce7d3160e7a0ce`。看板最近运行修复仍为 `35716e3`。新对话必须重新检查 HEAD、远端、status、交接，不把这些哈希当成永久最新版本。
- 开始时有日报未提交修改；现已由原任务独立提交，本批未修改任何日报代码。最终盘点仅4份既有未跟踪提示词，仍不改、不提交；后续以实际 status 为准。
- 本机配置 `P:/project/swhy/Delta1/project/dashboard/localsetting/native.json`；桌面 `C:/Users/inani/Desktop/Delta1 股指看板.lnk`，实际指向统一工作区 `dashboard/start_presentation.vbs`，显式 `--theme public --local-root P:/project/swhy/Delta1/project/dashboard/localsetting`。原桌面入口目前未改。
- 公司 Git 根 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`；公司配置目录为该根下 `dashboard/localsetting/app`。公司 Python `D:/conda/envs/swhy_delta1/python.exe`，WindPy及用户site存在是此前公司报告事实；本机当前 App Python 没有 WindPy，不代表公司缺模块。
- 本轮没有新公司 overview/diagnosis，不能确认用户当前窗口提交或把本地旧库缺口当成公司现状。此前4份公司报告确认468033a、ETF规模 complete 但 published=false；四指数返回300/50/500/1000名单，缺权重1/0/2/2及旧/混合行日期。公司行业、净值和持续运行不能由本机模拟代替。
- 用户最新授权所有测试，也可提供公司测试入口；真实接口测试应有界、只读、保留安全证据，默认 `-Overview` 继续离线。实时VPN仍手动；DDB只在真实需求/缺口下按原政策使用，不为HTTP失败自动切DDB。不重装Wind/环境、不改用Oracle、不强杀写入者、不清理旧工作区。

## 这次实际分析结果

### 连续档位已存在，分红历史却未接上

`marketdata/overview_percentiles.py` 已逐历史交易日通过 `native/continuous.slot_map` 映射00/01/02/03，交割日保留旧档，下一交易日换月。因此不能把用户的“IF2611 60日缺14日”再解释为该实际合约上市短。

真实问题之一是 `overview_basis.load_dividends` / `dividends.read_snapshot` 仍只选最新固定分红快照，`DividendBook.points(symbol,day)` 在 fixed_snapshot 下不按历史day选择版本。加载新文件还会丢掉只在旧文件里的已到期合约；同日冲突也一概拒绝，尚无上午/下午修订版及本地历史合并。

本轮只读复算本机旧库，以2026-10-28为定价日、2026-07-28—10-27为60交易日前窗：IF00当前映射IF2611，**14个 dividend_missing 全部对应IF2608，日期07-28—08-14**。另有本机旧价格库7日缺价，必须独立列示；不代表公司库也缺7日。仅改用10-27新表时，IF00历史分红缺项反而增至38日，说明不能用“换一张最新表”处理历史。

需用公盘历史文件重建按日、按实际合约的分红，再缓存去分红价格/基差和年化。真实分红尚未取得时明确缺分红，不假造0、不跳过缺口凑样本，也不再次下载已有价格掩盖分红问题。

### 新Excel核验

只读完整读取 `T:/inani/下载/Chrome/指数基差情况_2026-10-27.xlsx`，34285字节，SHA256 `83fcc5ac9f67dd96e14dbcc3a305f75e2c068ec987fefc9e89b065df7710e409`；未执行RTD、外链或任何单元格文本指令，未修改文件。

Sheet1!B1缓存日期2026-10-27；C/G绑定具体合约与分红点数；H=F-S+D，I=H*365/T/S。16合约用当前简单公式复算全部一致，百分数最大误差约3.38e-14。C26/G26按IF2611实际合约绑定该日分红；明确0仍是有效输入。

Sheet2包含2026年日期及五个指数的缓存日分红，未来有0值；它不是“每个过去日当时已知的合约剩余分红预测”。未经核验不能拿它的未来零值、事后实现分红或今日G列回写过去。概览仍只做原四指数，不能因附表有A500自动扩范围。C/G与日期是源输入，E列不擅自覆盖独立挂牌/到期参考。

### 非交易空白已复现

`native/market_overview.futures_values` 现在只允许连续交易新鲜配对或两腿同日正式日线；非交易时段即使保留合法同步HTTP缓存，也会拒绝派生值。构造15:00的期现同步缓存，在18:00读取：价格存在，年化仍为null；以同一价格/分红/23天可算出参考年化-3.570652%。这证明需要新增“缓存参考”通路；不能通过放宽实时30秒/3秒来解决。

### 行业与ETF的实际状态

已有 `equity_collection.EquitySampler` 独立60秒、100代码批次采成分行情；`overview_contributions` 计算篮子涨跌及贡献，但要求有效完整权重、准确前收盘、同步快照及匹配参考版本。`ReferenceJob` 成分/权重/行业/ETF规模每周复核，ETF NAV另有每日有界任务。旧IH权重09-30超过14自然日滚动范围，其他组缺权重/混合日期，当前严格规则会阻断行业完整篮子及贡献。不能回答“已经抓齐”。还须核验Wind返回date的确切业务含义，不把未经核验的行date直接当权重日期。

当前收盘折溢价有同日NAV+未复权close链路；实时IOPV须明确字段或映射。净申赎与PCF仍是缺源占位，没有抓取实现；申赎状态和资金净流量是两类数据。公网上交所四只代表ETF详情页本轮仅取到动态空壳，未取得带日PCF；页面能打开不等于数据已抓到。

### 可复用的行情分析

源模块为 `index_futures_basis/security_desktop.py`、`security_model.py`、`security_data.py`、`security_wind.py`、`security_futures.py`、`security_chart.py`，入口在独立App `desktop.py` 的“行情分析”。有代码名称核验、日线/分钟/最新单值、字段选择、缓存补缺、绘图、CSV及TWAP/VWAP。

股票/ETF/指数可按既有能力查询；股指期货当前**仅本地日线**，拒绝分钟和最新值，VWAP当前只支持股票/ETF。TWAP是等间隔有效分钟收盘均值近似；VWAP需量额成对有效、量>0且单位已确认，指数成交量额不能直接算指数点位VWAP。期货VWAP如要增加须另核验合约乘数、量额定义及来源，不能照搬股票公式。

本轮38项行情查询及离屏Qt测试通过（6.834秒）。另一次包含本地期货的42项组合出现3个Windows临时SQLite清理错误，位置在既有Store连接生命周期；仍有unclosed database警告，未修改原App。搬迁时应处理自有连接关闭并复验，不能宣称42项全通过或把警告归因公司数据。

## 十项执行规格（用户已确认）

### 1. 分位继续按四档连续合约；分红改成日期版本

四张实际合约卡不换成连续代码；每卡对应当前00/01/02/03的逐日真实合约历史，20/60交易日同时显示。仍用 `100*(F-S+D)/S*365/T`，排除当前定价日，已知T<5单列规则排除；真实缺价/映射/分红不能跳过。不要改为向前追溯直到凑满20/60有效样本。

D主键必须包含实际合约与业务生效日期/时刻，当前日新版本只影响生效后的计算。优先取该实际合约在定价时点以前最近有效版本；没有该合约时，才按原用户要求继承同品种更早到期合约在该时点已知的分红。不能用未来新版本回填过去，也不能借后到期合约倒填以前合约。明确0优先，继承来源可追溯。

建议实现独立追加式分红库与历史派生缓存：

- 配置可新增 `overview_dividend_source_dir`、文件匹配规则、AM/PM检查时间；原显式 `overview_dividend_file` 与旧本地目录仍兼容，新增配置不能静默覆盖原个人设置。
- 公盘只读，当前推荐源 `\\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`。本机隔离根建议 `<local_root>/overview_dividends/`：raw按SHA保留输入版本，SQLite或分区文件保存标准记录，派生缓存单独存；实际业务数据不进Git。
- 记录 `contract_id, effective_date/effective_from, points, source_business_date, source_published_at, first_seen_at, file_sha256, parser_version, source_kind, inherited_from`。区分业务日/发布时间/本地导入时间；不能用文件mtime或首次下载时间假装早已知道数据。
- 新源推荐命名 `指数基差情况_YYYY-MM-DD_HHMM.xlsx`，兼容已存在 `指数基差情况_YYYY-MM-DD.xlsx` 及同名覆盖；以经核验的表内日期和命名元数据校验，不只信文件名。只有日期的老文件保留日期精度，不能伪造上午/下午发布时间或声称支持逐笔时点回测。同日冲突要支持有序修订，次序不能确定时明确提示。
- 先一次性按60窗口所需日期导入公盘历史归档，之后只增量；一年跨界可配置/遍历相邻年份的必要范围。没有旧日分红时如实列缺项并准备公司定向核验，不能以今天单表替代全部历史。
- 历史缓存键包括交易日、连续档位、实际合约、期/现价格版本、到期日、当时D记录版本、公式版本；保存F、S、T、D、F+D、F-S+D、年化及来源。今天D更新不能使所有旧日套用今天D重算。合法价格修订有独立版本，不能默默擦掉原证据。

### 2. 期货卡片

把“简单年化”统一改为“去分红年化基差”。每张实际合约卡在这行下显示“较昨日基差变化”，单位点，按 `(F_t-S_t+D_t) - (F_prev-S_prev+D_prev)`；同一实际合约，准确上一交易日，D_prev必须是上一日当时有效版本，不拿今天新D回算昨天，也不拿昨结算替代昨收。现有仅近月汇总的字段不能直接复用成四卡相同数值。5分钟变化若跨分红更新，也用各时点D。

### 3. 时间与状态

共用左上角一处简洁状态栏，主要显示最新有效数据更新时间/参考日期，正在获取Wind或DDB时加简短状态。移除各卡片重复源时和冗长说明，详细时点放悬浮或诊断。内部仍严格保存源时、接收、计算、页面应用四类时间；页面定时重绘不能使“最新数据”时间自动前进，部分陈旧不能由最新一条掩盖。

### 4. 图标与快捷方式

重新制作蓝白清晰图标，保存可跟踪源资产及含16/32/48/256尺寸的ICO；窗口、任务栏和桌面使用统一标识。新增公司一键 `dashboard/create_desktop_shortcut.cmd`（及必要PS脚本），基于脚本自身位置、Windows真实桌面目录，指向 `start_presentation.vbs`，显式public，并兼容LocalRoot含中文/空格/UNC。

本机授权替换原“Delta1 股指看板.lnk”；先生成并核验新快捷方式，再移除/替换该看板旧入口。不要误删独立“Delta1 股指基差”App或其他桌面文件；旧ICO先核验引用。`index_futures_basis/create_desktop_shortcut.*` 可参考，不能直接拿其start.cmd/图标覆盖看板。当前 `native/branding.py` 指向 `dashboard/assets/research.ico`，须一并核对。

### 5. 顶层页面结构

默认“概览”显示 **4指数＋4×4实际期货卡**，共20卡，四品种同时可见。现在三个子页上移，与概览同级排在右侧：`概览 | 指数 | ETF | 股指期货 | 行情分析 | 数据更新/设置`。保留指数/ETF/期指详细页。大字、清晰，窄窗口重排和纵向滚动，不能为塞入20卡而把字缩小；所有16卡保留20/60分位，切页/空值/换月清空旧实体状态。

### 6. 公盘上午、下午各检查一次

时间为上海时区，可配置，建议初值09:00/15:30；后续按真实文件产生时间调整。当天启动若错过一个时段可补一次检查；不要每三秒、每次切页或每次计算访问UNC。每时段有界检查清单/元数据，大小mtime未变则不读文件，内容SHA已导入则不重复复制/解析/计算；同名覆盖但内容变化可追加新版本。检查状态跨重启持久化，失败有有限退避而非忙重试，不阻塞HTTP采集、页面或关闭。

本轮在沙箱外限时只读探测该目录返回 `FileNotFoundError/WinError 53`，没有读取到文件清单；只能说明当前开发电脑不可达，不能说明公司目录错误、权限不足或不存在。没有自动改VPN。

### 7. 非交易时间必须尽量有值

不能因HTTP抓不到就把概览年化/分位全部清空。用最近合法同步缓存参考，或最近一个两腿都有同日有效收盘的公共日期计算；保留实际价格日、对应分红版本、到期日/T及缓存标识。不混搭不同日、不同实际合约或不满足配对条件的两腿，不修改旧时间冒充实时。缓存参考独立于盘中30秒/3秒有效性；午休保留最后合法配对参考，盘前/盘后/周末/节假日同样覆盖。换月盘前须核对展示合约、档位归属日与价格定价日，不能因索引错配误清空。

真实没有任何有效价格或D时仍需明确输入缺项，不能为了“必显示”造数据；缺D可以显示原始价格/点基差并说明，不能拿未去分红分位冒充去分红分位。

### 8. 行业贡献取数与更新

先核验正式资料是否published、四组名单/行业覆盖、权重值及真实参考日期、全成分一分钟采样覆盖、准确昨收及参考版本。逐个解释“篮子涨跌”和“贡献点数”缺哪个输入，不再只有占位文字。

成分/权重/行业继续定期更新：保留至少周度完整复核和显式刷新，权重日常仅在全成分锚价/前收盘可用、假设可接受时滚动估算并标记；缺/过旧权重需有有界修复路径，不能本周失败就无期限空白。真实官方日权重如接口可得，优先核验采用，禁止凭字段名猜含义。有效数据每分钟计算行业贡献，榜单与成分使用同一周期；不能部分股票重归一化冒充完整行业。

### 9. ETF能力实测

区分四项分别验证：盘中IOPV与同步折溢价、同日收盘NAV折溢价、净申赎份额/金额、PCF申购赎回状态。先复用现有HTTP明确字段/映射及已登录WindPy；低频份额/NAV/PCF不加到三秒轮询。IOPV候选字段只能依据官方字段定义/公司Wind代码生成器或经核验的映射测试，不把reference猜作IOPV，不按ETF代码＋1盲猜。

准备独立显式只读“数据能力测试”入口，按字段/阶段有界请求，导出安全的日期、字段、样本数、ErrorCode、连接前后状态、覆盖与非空数量；不发布到正式缓存、不输出凭据或原始异常秘密。默认-Overview保持离线。新测试参数必须真实实现并验证后再写可运行命令，不能让用户运行尚不存在的-WindStage。

收盘折溢价用同日未复权close/NAV；净申赎需已核验基金份额、必要单位/拆分和同日NAV，不能用成交量或规模变化替代资金流；估算必须标记。PCF优先基金管理人/交易所正式带日数据并保留来源；公开页面可达不算解析成功。Wind实时订阅仍不常驻；确需一次性IOPV能力探测可在用户此次测试授权下显式执行，不擅自把它变成后台Wind实时轮询。

### 10. 搬入“行情分析”

从独立股指基差App复用查询/计算/缓存/数据契约，新建同风格、大字号Qt页面。输入标的、开始/结束日期时刻（默认上海时区今日）、频率及需求字段；结果图像与TWAP/VWAP卡片，原始数据/导出可从属展示。今日按已完成周期截至现在，午休不造分钟，未完成周期不算历史缺失。

不要直接嵌入原App完整Window或自动创建其报告/基差计算服务。复用SecurityService需适配DataPaths、解释器、取消、锁及安全诊断，防止与日常采集互相阻塞；手动按需WSI/WSD与概览周频Wind任务是不同用途，不因研究页暂停禁掉用户此项查询，也不因此重启32项研究服务。

保留NaN剔除、有效样本数、量额配对、单位确认、指数VWAP不适用、股指期货仅本地日线的现有边界。若扩展期货分钟/TWAP/VWAP，先实测源与合约乘数再实现，不能声称原模块已支持。修复/隔离已发现SQLite连接不及时释放问题，自有线程/读进程正常取消排空，原独立App及报告结果保留。

## 实施顺序与验收

先做逐日分红库/历史派生缓存＋连续分位＋非交易回退，再做20卡/平级页面/卡片文字/统一状态栏；接着公司数据能力实测及行业/ETF修复、按需行情分析、图标/快捷方式。按可验证批次提交推送，不再把“本地单元通过”写成公司取数成功。

必须覆盖：新D更新前后边界（上午/下午/跨日）、同名文件改版与同SHA零重复读取、明确0/前序合约继承/禁止未来版本、已到期合约历史保留；IF/IH/IC/IM四档20/60窗口/换月/当前日排除/T<5/真实缺价分类；非交易缓存与正式收盘、跨日和错腿拒绝、换月盘前；每卡准确昨日点基差变化；20卡与同级页缩放/滚动/切页/空值清空；分钟行业/权重版本/缺值；ETF各字段有错码/日期和独立状态；查询TWAP/VWAP手算、单位、当日未完成周期、缓存复用、SQLite关闭及安全取消；快捷方式目标/参数/图标核验。保持三秒主行情、60秒成分、30秒/3秒质量门槛。

只改概览及新增手动行情页，32项研究核心/A02暂停且源码保留。日常历史仍只补概览日线，不恢复研究秒/分钟历史全库下载；手动行情分析仅按用户所选标的/窗口请求并缓存。已有数据先复用。原行情、分红、缓存、个人配置、凭据、Excel、四提示词及其他未完成工作保留。

发布仍按APP_RELEASE明确白名单，更新交接/验证/公司步骤，精确暂存、提交、推送codex/company-apps并核验远端。不改其他模块业务，不全量stage、不强推、不reset/clean。每批说明实际修复、测试结果、公司尚需确认事项。

## 现在已有的公司测试命令

这些命令已存在；不验证尚未实现的逐日公盘接口或ETF净申赎/PCF/IOPV新能力。

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git status --short --branch
git log -1 --oneline
$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -Overview -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Indices -WindDay 2026-10-27 -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage ETFs -WindDay 2026-10-27 -NoPause
```

保持日常Wind终端登录；阶段只读不发布，所以published=false正常。若已有正式发布ETF名单，再跑：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Nav -WindDay 2026-10-27 -NoPause
```

保持正常看板开着取Overview，回传同次overview.json＋diagnosis.json；各Wind阶段回传同次wind.json＋diagnosis.json。不得把旧后台状态文件当现在进程存活证据。

公司可先只读查看公盘最近文件名/大小/时间，勿改文件：

```powershell
$deltaDividendShare = '\\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
Get-ChildItem -LiteralPath $deltaDividendShare -File -Filter '*.xlsx' |
    Sort-Object Name | Select-Object -Last 8 Name,Length,LastWriteTime
```

新对话实现后另提供一键公盘/历史D/ETF能力分阶段入口及安全报告；当前不要把示例参数当成已发布功能。

## 本机证据与外部来源

本机只读提取、实际缓存复算、限时公盘探测、构造非交易反例与38项测试日志仅在忽略目录 `local_artifacts/validation/next_overview_20261028/`；未把真实Excel/原始报告/缓存写入Git。受保护输入和原入口应在交付前再验哈希。

- [深交所ETF交易说明](https://investor.szse.cn/warning/activities/fundIntroduction/t20210104_584079.html)：IOPV与成交价比较的折溢价概念；不能由昨日NAV替代盘中IOPV。旧说明不等于当前公司字段覆盖或频率实测。
- [上交所510300申购赎回清单详情入口](https://www.sse.com.cn/disclosure/fund/etflist/detail.shtml?fundid=510300)：本轮与510050/510500/512100页面只取得静态空壳，未证明指定日PCF已解析。
- [深交所ETF数据交换技术说明](https://www.szse.cn/marketServices/technicalservice/history/P020180328468135161873.pdf)：PCF、IOPV清单与申赎成交回报是不同数据，旧接口说明仅供理解，不当作当前公开API或公司权限保证。

## 新对话执行提示词（复制本节即可）

请继续修复Delta1蓝白公司看板，直接完成代码、验证、提交推送。先完整读取本文件 `P:/project/swhy/Delta1/company-apps-worktree/dashboard/docs/NEXT_OVERVIEW_IMPLEMENTATION.md` 的十项执行规格及实际分析证据，并读根目录/看板AGENTS、PROJECT_HANDOFF、APP_MARKET_OVERVIEW、APP_VALIDATION、APP_COMPANY_TEST和APP_RELEASE。重新核验HEAD/远端/status，公司统一分支codex/company-apps；不沿用旧固定分红情景或短合约历史不足结论。

本轮优先：日期＋实际合约的分红版本及公盘AM/PM增量同步、冻结去分红历史缓存、四档连续20/60分位和非交易缓存参考；随后20卡概览与同级指数/ETF/期指页、每卡去分红年化基差及较昨日变化、简洁统一状态栏、新图标和公司一键快捷方式、行业贡献/ETF真实能力测试与修复，以及复用独立股指基差App的行情分析页（图像、TWAP/VWAP）。研究32项/A02继续暂停且保留，手动行情查询按需取数，不恢复全库分钟/秒历史补库。

分红公盘为 `\\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`；新源 `T:/inani/下载/Chrome/指数基差情况_2026-10-27.xlsx`。按每个历史日当时的D计算，新分红不回写旧日；明确0保留，必要时按同品种更早到期合约继承当时已知D。当前代码虽已连续映射，却只读最新分红表，本机已复现IF2608历史D缺14日。不能假造0或跳过缺口以消掉提示。

我已授权所有必要测试，也可以在公司电脑运行你提供的分阶段入口并回传。请主动做有界只读实测；当前开发电脑无WindPy且公盘不可达时，不重装环境或猜接口可用，准备可复制公司测试。默认-Overview保持离线，实时VPN由我手动连接。所有新接口、单位、时间和覆盖以实际证据为准，安全错误链保留阶段/ErrorCode而不导出秘密。

保护原数据、Excel、缓存、配置、凭据、其他工作与四份旧提示词。精确清单提交推送统一分支并核验远端；离屏检查大字蓝白UI、滚动缩放切页、空值清空、安全关闭及原桌面入口。按本文件验收项逐批落实，不只再给方案。
