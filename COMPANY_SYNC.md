# 公司统一更新与发布

所有应用、开发与公司运行统一使用 `codex/company-apps`。公司在原 Git 根目录一次 `git pull --ff-only` 更新全部已发布模块；原配置、凭据、数据和未完成工作保持原位。

## 当前模块

| 模块 | 职责 | 交接 |
|---|---|---|
| dashboard | 蓝白市场概览、数据编排；研究页暂停，32项源码及Excel保留 | [看板交接](dashboard/PROJECT_HANDOFF.md) |
| dashboard/backtest | 独立股指期货/合成现货大表回测桌面、实际开平仓读取接口 | [回测交接](dashboard/backtest/PROJECT_HANDOFF.md) |
| securities_lending | 券源下载、查询、行业与金额筛选 | [券源交接](securities_lending/PROJECT_HANDOFF.md) |
| script_making | 交易前日报查询、人工簿记和日报管理；兼容既有统计自动任务 | [日报交接](script_making/PROJECT_HANDOFF.md) |
| statistics_app | 独立统计桌面入口，复用原统计实现和数据 | [统计交接](statistics_app/PROJECT_HANDOFF.md) |
| index_futures_basis | 独立基差、分红、期限结构及报告 | [基差交接](index_futures_basis/PROJECT_HANDOFF.md) |
| index_strategy | 历史 / 实时采集与兼容桌面工具 | [采集接口](index_strategy/instant_dld/README.md) |
| shared_data | 公共目录、数据登记与原有迁移 | [公共数据说明](SHARED_DATA.md) |

## 最近发布

- 2026-11-12行业变化补全，基线a628472：完整历史优先，缺项时展示部分配对或基于真实权重与行情的估算，显式样本和基准日期。510项完整回归通过，130.731秒（含加载），无跳过，ResourceWarning作为错误；较上版新增14项。 公司a628472包确认约30秒定时重绘、DDB隧道认证、同次关闭7.247秒；新图公司验收待更新。[复测](dashboard/APP_COMPANY_TEST.md)、[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。


- 2026-11-12公司复测与同屏概览，基线da50685：四品种卡图同屏、ETF表配色放大、指标末点加大，安全记录定时绘图与行业权重可比原因。496项独立完整回归通过，136.744秒（含加载），无跳过，ResourceWarning作为错误；原490项重跑，新增6项。 公司da50685包完整，IC03实时单时点五组Z/分位有值且公式复算一致；DDB复用隧道并认证、查询部分完成，同次关闭3.355秒。连续30秒重绘与IC/IM上次权重缺失确因需新报告；[复测](dashboard/APP_COMPANY_TEST.md)、[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。


- 2026-11-12概览与指标刷新，基线95869c2：30秒绘图、缺项解释与安全盘后回退，20/60同窗均值中位数及两端高亮，概览四品种期限/成交/持仓、行业权重变化和ETF总览。490项独立完整回归通过，123.232秒（含加载），无跳过，ResourceWarning作为错误；原469项重跑，新增21项。 最新95869c2公司包两份Overview缺失，不能判断新页Z/分位或同次安全关闭；本轮诊断安全修复与新界面待[公司复测](dashboard/APP_COMPANY_TEST.md)。[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。


- 2026-11-11正式指标分析页，基线39760f0：一品种/四图、可调t_w/t_z、均值中位数虚线跨图、跨期同日S分母；逐日合约/D/T和图外历史、版本LRU、冻结快照及所选品种有界日线维护接入，原20/60与32/A02暂停保持。469项独立完整回归通过，105.841秒（含加载），无跳过，ResourceWarning作为错误；原438项全部重跑，新增31项指标页回归。 100%/125%三尺寸离屏截图核验，1536×864/125%四图无滚动。b7新公司包9JSON完整，11-10四指数+16期货昨收及原20/60恢复，DDB新端点复用隧道并认证查询、仍缺16 OI/12ETF close，同次关闭2.731秒。新页公司现场仍待[复测](dashboard/APP_COMPANY_TEST.md)；[实现](dashboard/docs/INDICATOR_PAGE_PROPOSAL.md)、[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。


- 2026-11-11指标页方案与接续交接：运行源码仍为已推送b7d5d55，本轮仅文档/模拟示意，没有运行代码变更或新公司验收。新增一品种可切换的基差两图＋03−02/02−01跨期两图；四项统计统一t_z，均值/中位数虚线跨t_w，跨期分母同日指数S已获用户确认。正式页尚未实现，32/A02继续暂停；DDB不暂停，HTTP会话推定/192.168.198.77:8904及11-10/原20与60仍待新安全包。[分析](dashboard/docs/INDICATOR_PAGE_PROPOSAL.md)、[新对话提示词](dashboard/docs/NEXT_COMPANY_RETEST_PROMPT.md)、[交接](dashboard/PROJECT_HANDOFF.md)。

- 2026-11-11 HTTP连续会话核验，基线596839d：HTTP缺显式交易日时，仅在连续交易时段用两次已归档行情交叉核验：同实际代码/稳定昨收、真实市场字段变化、源时钟随接收时间推进且新鲜；通过后按交易日历补准确前一日close，并明确标注corroborated_live_session/日期推定，不能声称交易所认证日期。盘前/午休/盘后、静止或陈旧快照、冲突日期及换日/换时段证据不放行。 用户最新要求DDB不暂停，继续原自动数据VPN/历史补齐；已手动连接且新地址192.168.198.77:8904可达时复用现有隧道，不重复登录。实时VPN仍手动，原DDB/VPN配置、账户密码和原文件不改。 438项独立完整回归通过，103.831秒（含加载），无跳过、ResourceWarning作为错误；原420项重跑，新增18项连续会话证据、日期边界、缓存重算与DDB隧道复用验证。 公司596839d包已证HTTP20个标的全因source_trade_date_missing补入0，DDB停route/waiting_vpn/login，11-10四指数+16期货收盘缺失。本轮新会话推定方案与用户修复后的DDB连接仍待新公司包，不以本地模拟代替源端验收。 [公司复测](dashboard/APP_COMPANY_TEST.md)、[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。

- 2026-11-11 HTTP昨收优先，基线30937eb：本地日线优先，再用HTTP yesterdayClosePrice补源交易日的准确上一交易日，重新核验缺口后DDB仅补剩余历史收盘及最近完成日OI。HTTP必须带明确且一致的tradeDate/tradingDate/tradingDay、匹配实际securityId，并核验两日挂牌/到期和交易日历；只有时分秒或盘前旧快照不入日线。盘后昨收仍写前一交易日，不写当天；昨结算/当前价/当前OI不代替昨日数据。 420项独立回归通过，117.339秒（含加载），无跳过、ResourceWarning作为错误；原395项重跑，新增25项HTTP昨收、日期/合约/路由与页面缓存回归。 公司真实HTTP是否提供可认证交易日、11-10两腿收盘、全部四档20/60分位和新DDB端点仍待新安全反馈包；不把本地合成测试当公司已补齐。 [公司复测](dashboard/APP_COMPANY_TEST.md)、[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。

- 2026-11-11追加，基线b1d1f44：用户澄清为期货年化分位“缺收盘”。DDB有效收盘先保存、缺OI独立补；相同价格不重复计进展/归档。独立校验错误保留安全明细后继续其他有界任务，网络/SDK失败仍停止；分位悬浮与更新页显示具体缺项，收盘/持仓待补分列。395项完整回归通过，110.116秒（含加载），无跳过、ResourceWarning作为错误；原388项全部重跑，新增7项价格/OI隔离、分位恢复、批次隔离和缺口解释回归。 同一模拟回包复现旧版丢收盘，新版20/60恢复且OI仍缺；实际公司根因/新源11-10待反馈。[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。

- 2026-11-11看板DDB与更新页，基线d4c2b9b：App使用发布端点192.168.198.77:8904（显式App设置优先），数据网络/会话一致，原账号密码/TLS文件不重写。更新页整体滚动、分组、40像素输入框；概览/设置区分价格日、DDB目标及Y盘分红日，诊断导出维护阶段和目标。388项回归通过。本机3秒直连超时、未查询11-10，不作公司失败证据；公司更新后按[测试步骤](dashboard/APP_COMPANY_TEST.md)核验。原数据/配置/Excel/四提示词/唯一归档保护，公式和32/A02暂停保持。[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)。

- 2026-11-10看板启动提速/整理，基线c730d46：新b5746c7公司包9JSON完整，同次安全关闭6.153秒；16档OI×价格×乘数及双饼图金额复算一致，来源11-09日线，300分批已运行。用户确认其余ok后，完整预检/GUI改同解释器复用导入，已排空旧会话跳过CIM，保留失败和写入者安全接管；增加启动时序，新增[常用入口](dashboard/常用入口/README.md)。本机隔离三次中位3.474→2.188秒，298项回归通过，公司新启动仍待测。122旧验证文件核验归档、12可重建字节码清理；原数据/配置/四提示词/唯一归档保留。采集参数未改，补正正常App时段外60秒有限快照与默认Overview离线的区别。[交接](dashboard/PROJECT_HANDOFF.md)、[验证](dashboard/APP_VALIDATION.md)、[源码采集说明](dashboard/APP_MARKET_OVERVIEW.md#按源码核对的采集流程)。

- 2026-11-10看板新对话交接，运行源码已发布b5746c7并核验远端，267项回归属于该次运行修复。本次仅更新[接续提示词](dashboard/docs/NEXT_COMPANY_RETEST_PROMPT.md)及交接：新对话先收新反馈包，再结合用户新想法；补全当前主HTTP3秒/成分300只分批每轮约5分钟、低回包后续轮100、HTTP昨收、Wind/Y/DDB分工及持续缓存/安全排空说明。采集参数/接口/数据未改，未启动新采集或冒称新公司验收；新功能真实金额/交互等新包。

- 2026-11-10公司下午反馈，基线365fe84：9份runtime JSON确认12只ETF×60条三个月规模、1798/1800股票报价、同次安全关闭7.422秒；214分类及428历史D零占位仍缺真实来源。修复四指数真实缩放点击；300只/15秒、仍5分钟轮询，失败/缺项优先、低回包下轮100；冻结成分代次。中比例全卡并增大数字，期货横条加粗/文字内嵌；当前配对或派生暂缺时显示层沿用上次完整基差/年化/分位和源时、现价独立更新，raw仍严格。ETF下半页改为同日完整前三+其它和四实际期货持仓名义本金双饼图，OI×价格×乘数（IF/IH300、IC/IM200），不以成交量/伪0替代；仅当前16合约最近完成日OI真实缺口本地优先，价格独立保存，旧历史/数据不动。267项/53.505秒最终回归通过，新图实际金额及新交互待[一键复测](dashboard/company_retest.cmd)反馈；见[验证](dashboard/APP_VALIDATION.md)、[交接](dashboard/PROJECT_HANDOFF.md)。

- 2026-11-10看板最终显示收尾，基线1b621fc：部分成分剔除缺项计算行业篮子/贡献、旧权重带日；100只/15秒、约5分钟独立轮询，每批raw/SQLite及分类显示缓存持久化，默认不补全部成分DDB日线/不自动逐股Parquet导出，原归档保留。ETF数字重点、现有Wind字段补三个月规模曲线/真实相邻两期变化，缺历史不伪造0，占比维持同日全集分母。期货图例对色，默认中比例1080p全卡可见，大可滚动/小更紧凑。新增[一键复测CMD](dashboard/company_retest.cmd)串起更新、开窗、正常关闭、关闭后Overview和安全JSON ZIP。最终本地结果见[验证](dashboard/APP_VALIDATION.md)，公司实际历史与新关闭耗时待最后反馈；当前年化/逐日D/连续20与60分位及32/A02边界保留。


- 2026-11-10公司看板，基线12f34f1：33份公司JSON确认Y三表/最新11-06、16合约D映射及计算一致，同一运行安全关闭73.499秒。按用户新要求历史缺D暂0，补旧历史D后按版本重算；当前D/缺价/映射/冲突门槛保留。顶部显示分红表日，数字去“估”，悬浮/诊断保留补零信息。ETF无盘中值时主位显示带日收盘溢价，规模/占比/价差突出，下方只比较当前三只真实两期规模，含日期且不标份额/净申赎。有界本地归档读取，无新增接口。230项最终回归通过，新版公司UI/分位仍待更新复测；[交接](dashboard/PROJECT_HANDOFF.md)、[命令](dashboard/APP_COMPANY_TEST.md)。

- 2026-11-09开仓时点对照：用户授权0.5退出策略增加entry_timing=signal_close，默认仍next_observation；仅开仓当日close，阈值退出下一有效观测，到期同日双平。沿用保存因子和原账户逻辑，8账户独立重跑及199笔同日信号/成交、两腿账务/实际价格核验通过，旧口径40原生账本完全一致，170项回归与Ruff通过。新Excel分列信号/成交/回撤分位，两口径各一页签，无引用和表下说明；真实结果本机外置不入Git，DDB/VPN暂停、Z未访问，公司现场待运行。[参数调用](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-05新对话交接留存：仅持有到期放大报告的说明/模板版本007d49b与本机交付、核验证据已记录在[回测交接](dashboard/backtest/PROJECT_HANDOFF.md)，附可复制的新对话提示词。下一轮主题为跨期价格差反转，具体问题待用户说明；不预设沿用旧参数，不启动新回测、调参或获取。本轮只更新交接与发布说明，真实结果保留原位。

- 2026-11-05仅到期放大报告接续6d789bf：用户删除0.5退出，仅保留01-02/02-03、同账户低分位多/高分位空、四品种共8账户，100%保证金及其他参数不变。复用既有到期结果，因子/CTA/执行0次重跑；六页每跨期三页（数值/2×2分布、整页历史、收益回撤/案例），图表空间约2-3倍。24PNG/22CSV/3HTML和PDF本机外置，22CSV对应行完全一致，104原生PDF单元格、报价/p/持仓/回撤标记及ZIP校验通过。模板tune固定expiry、2配置/8账户，旧比较归档；DDB/VPN暂停、Z未访问，公司现场待运行。[当前调用](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-05用户澄清后的跨期四种情况：同一账户低分位做多、高分位做空；仅到期/0.5两种退出×01-02/02-03，四品种独立共16账户。保存因子复用0次主要计算，16账户单独重跑/前缀/账务核验；到期8账户的五份原生账本与旧PDF对应结果完全一致。6页PDF恢复指定v7样式，并按追加要求不同退出分别成页：前4页每情况一页数值/分布/案例/收益回撤，后2页各一种退出的全历史点差/p/持仓。前版单尾32保留为未采用比较；模板tune为4配置/16账户。真实结果不入Git，DDB/VPN暂停、Z未访问，公司现场待运行。[当前调用](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-05前版未采用的单尾比较：此前将低分位仅做多、高分位仅做空拆开，分别比较回到0.5与持有到期；两通道、四品种共32独立账户，双腿100%保证金。复用保存因子，32账户单独重跑、前缀/账务及355笔方向与分位核验；167项离线回归和Ruff通过，零交易账户返回带列名的空结果。图中空仓显示连续通道，持仓显示锁定pair，去掉叠加灰线，价格是原始点差、信号p来自年化价差；6页PDF与78图/18CSV外置。用户澄清后改用上方同账户双向16账户，不将单尾结果相加。真实结果不入Git，DDB/VPN暂停、Z未访问；公司现场待运行。[口径与命令](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-05跨期曲线颜色纠正接续07d9861：每笔实际开仓至平仓整段按最终扣费后净PnL，盈利红、亏损绿，未平仓按期末净浮盈亏，连续参照/空仓灰色；点差/p、单笔放大、账户曲线及离线交互统一，蓝/紫状态带仅表多空。6页PDF、32PNG/30CSV另存，新增逐笔颜色基准CSV；115笔逐腿/费用/颜色、保存报价/p和图形逐笔核对，原29CSV及545项旧文件SHA不变。本轮无因子/CTA/执行重算，真实产物不入Git。[口径](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-05跨期报告排版接续86b53de：第2/5页整页放大点差/分位/持仓图，去重复说明，保留实际多空与日期；点差绘图区约宽19%、高47%。PDF仍6页，其他四页内容及渲染像素相同，29CSV不变；新页/嵌图/原生表/全部链接及包CRC/SHA已核验。仅说明更新入Git，真实报告与数据仍本机忽略，因子/CTA/执行未重算。[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-04跨期报告接续928d16a：用户确认四品种2×2全历史版式后，点差下方补入同轴保存原始p及实际持仓，0.9/0.1与信号/成交/退出p明确区分。已完成6页A3横向PDF，首页前置全部8账户收益/年化CAGR/最大回撤日期/Sharpe与总结，收益分布含各自胜率及盈利/亏损均值，曲线后置；32PNG/29CSV/8笔放大案例外置。原生表逐格对账、6页逐页渲染、离线交互/原生持仓/保存p及包CRC/SHA核验通过，403项旧产物SHA保持。沿用100%账户，本轮因子/CTA/执行均0次重算；真实报告/数据/配置不入Git，旧报告保留，DDB/VPN暂停，Z未访问。[口径](dashboard/backtest/CALENDAR_REVERSAL.md)、[公司调用](dashboard/backtest/COMPANY_BACKTEST_TEST.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-04跨期图表接续ad0e4c0：大回撤pair放大，直接写明每腿买卖实际代码及手数、价差上涨时盈亏；新增整笔/回撤段专表，分列日期、点差变化、实际pair起止p、原信号p及期间毛净PnL/新增费用。连续图换档处断线，逐日拆解旧pair变动与换pair差异，单品种详图附信号/成交/前高/谷底/平仓节点。独立对账区间表、逐日两腿及全部跳变等式；保留100%账户、原胜率/收益及旧报告，先示例、确认后PDF。DDB/VPN暂停，Z未访问。[口径](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-04跨期图表接续0553502：保持100%保证金8账户数值，红涨绿跌；每通道四品种分别选择单笔持仓峰谷回撤最大案例，在全历史近减远点差上高亮实际pair及持仓/峰谷区间。新增实际成交后持仓状态带和样本末是否持仓，离线交互可查方向、代码与手数。逐日对账全部历史价格/原引擎持仓、独立重建逐笔PnL与案例排名，旧因子/结果/报告SHA不变。本轮仅更新PNG/HTML/CSV预览，待用户确认再做PDF；不重跑因子/CTA/账户，不访问Z/DDB/VPN。[口径](dashboard/backtest/CALENDAR_REVERSAL.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-04跨期100%保证金接续c62e1d5：01-02/02-03 × 四品种、原始q_open=.9持有到期，8账户改为双腿各100%保证金，原引擎重算手数/费用/权益；原因子复用0次计算，旧20%及旧PDF保留。收益数值与分布合并、明确年化/非年化，回撤详图标多空方向，原始点差与带方向含费净盈亏点数分上下显示。164回归及保证金/因子复用复测、8账户单独重跑/前缀/账务对账通过，Ruff通过。仍先PNG/HTML示例，用户确认后做PDF；真实数据/配置/结果不入Git，DDB/VPN暂停、Z未访问。[说明](dashboard/backtest/CALENDAR_REVERSAL.md)、[公司步骤](dashboard/backtest/COMPANY_BACKTEST_TEST.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-04相邻跨期接续e8915e8：当前01-02/02-03 × 四品种，仅原始q_open=.9持有到期，8独立账户。因子显式声明channels，CTA只查已保存通道；新增矩阵--q-open/--exits，旧48方案兼容保留。8账户独立重跑、前缀/重读/账务核对和163项回归通过，engine/api不改。先交收益/回撤/Sharpe数值表、后置曲线及最差两笔实际价差PNG/HTML预览，待用户确认再做PDF；真实数据/配置/结果不入Git，DDB/VPN暂停、Z未访问。[调用说明](dashboard/backtest/CALENDAR_REVERSAL.md)、[公司步骤](dashboard/backtest/COMPANY_BACKTEST_TEST.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-03跨期专项接续212d95f：01-03/02-03 × 四品种 × 原始q_open=.8/.9 × 到期/q_close=.6/.4共48独立账户，双腿20%保证金。因子保存旧实际pair相对入场通道前60日分布的退出p，CTA只查表，原执行引擎不改；逐笔入场保证金收益、两腿费用/PnL和回撤日期对账，48账户单独重跑及因子前缀/重读一致。总结PDF限6页，完整CSV/HTML/PNG本机外置；数据/配置/结果不入Git，DDB/VPN暂停，本轮未访问Z。见[调用与调参](dashboard/backtest/CALENDAR_REVERSAL.md)、[公司步骤](dashboard/backtest/COMPANY_BACKTEST_TEST.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-03研究报告/公司复现接续d63e670：本机42页PDF首页为总结图，含16组曲线、实际pair两腿、跨期及396行归因附录；公司数据ZIP带7份原SHA快照、离线报告、配置准备脚本及逐文件清单，真实产物不入Git。公司首次按同数据计算本机因子，后续CTA复用；四配置计划1/16/32/4及795日/172参考读取通过，原40个输入/因子SHA不变。PDF逐页渲染和包SHA核验通过，无引擎修改、无Z/DDB/VPN操作。[公司获取与调参步骤](dashboard/backtest/COMPANY_BACKTEST_TEST.md)，公司现场仍待运行。

- 2026-11-03仅多期货研究接续`b99094b`：新增期现CTA的allowed_future_side=long，仅低尾反转做多实际期货/空指数并持有到期；默认both保留旧双向组，跨期不变。slot_study复用已存合并因子0次计算，原始连续/实际因子不变；新报告/桌面曲线用收益率%，腿/pair按所属账户初始资金计算贡献。150项回归、Ruff、四页1080p/4K及216组交互通过，786个实际pair百分比纵轴及合计/两腿贡献线已核验。新18case/72账户全部完成，跨期权益/持仓/成交与旧组完全相同，40个输入/因子文件SHA未变。真实配置/结果仅本机，DDB/VPN暂停，Z源未操作；[规则和调用](dashboard/backtest/FIXED_SLOT_STUDY.md)、[模板](dashboard/backtest/long_future.config.example.json)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-03标准调参接续 `1fdcac5`：兼容目标明确为当前Delta1，workflow tune直接复用原因子→CTA→执行框架；四段配置增加可选grid/cases/max_runs，可预览、自动缓存因子/不变CTA，并保存每组有效配置及原生回测结果。桌面保留批次配置，因子参数变化后禁止误用旧因子跑CTA。148项回归及Ruff通过，连续/实际两份因子均核验不变；8合成配置仅2次因子/4份CTA，2024起冻结因子4组真实阈值/费用配置计算0次、16账户完成，未额外全量搜索。图例及蓝历史/紫条件回归区别、跨期阈值图说明见[调参说明](dashboard/backtest/PARAMETER_TUNING.md)；[期现模板](dashboard/backtest/tuning.config.example.json)、[跨期模板](dashboard/backtest/tuning.calendar.config.example.json)。数据/结果仅本机，DDB/VPN暂停，Z源未操作。

- 2026-11-03固定档位研究接续 `e778dff`：用户确认16组独立期现账户、4组跨期，不共享资金/指数净额，固定入场档位但锁定实际代码至到期；中心化0.9/0.8保留。新slot_study/slot_report复用因子，逐品种/档位/实际合约比较历史分位与条件回归及两腿毛/净PnL、费用。用户已授权Z只读导入本地data新快照，默认仍拒绝直接Z和旧混合缓存，显式标记＋SHA清单核验；DDB/VPN暂停。新快照含2023暖启动，评估2024-01-02—2026-10-14，18case/72独立账户全部对账；141项回归、Ruff、四页恢复/1080p/4K、216组离线交互通过。真实源和结果只留本机，公司待验收。[当前口径和调用](dashboard/backtest/FIXED_SLOT_STUDY.md)、[模板](dashboard/backtest/slot.config.example.json)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-03 回测结构研究接续 `c736eb8`：01−03 用真实剩余自然日差年化，收益增加实际自然日CAGR；每品种历史期限结构条件分位回归保存原始p/q/模型诊断，CTA单独将各实际合约转成独立期现pair，同品种共享资金并保持旧pair手数。实际净指数费用/保证金及跨期两腿归因逐日对账，生成PnL/收益/具体持仓和离线交互报告。138项回归、Ruff、四页1080p/4K、144组浏览器交互通过；已有纯源区间12方案/48品种账户，真实结果仅本机。DDB/VPN继续暂停，完整2024至今和公司现场仍待后续。[结构研究与调用](dashboard/backtest/TERM_STRUCTURE.md)、[模板](dashboard/backtest/structure.config.example.json)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-02 回测框架接续 `6777c4d`：统一 DataConfig 和 Parquet/注册分片适配、路径冲突及纯来源拦截、数据版本/绝对路径/覆盖清单；因子/CTA 独立保存、重载和复用，四段配置及桌面四页完整恢复。保留原因子和固定/Z，新增连续价格/价差及01−03反转持有到期；neutral_units 保证合约等价权重与数量零和，逐腿资金核算，新默认固定保证金100%，旧明确情景保留。125项离线回归、Ruff、1080p/4K四页通过；合成4账户32条成交。DDB/VPN继续暂停，真实行情未搬动/复制，纯源覆盖仍2025-07-01—2026-10-14，公司现场待验收。[调用与示例](dashboard/backtest/WORKFLOW.md)、[数据规范](dashboard/backtest/DATA_FORMAT.md)、[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-02 回测接续 `20f526f`：新增按整数期货手数生成 200/300 反向指数单位、配对资金/费用预算、关联到期双平、逐合约独立账户及目标不变保持手数。60 日中心化分位 0.9/0.8 反向择优持有到期专项，含全部实际合约、两腿归因、因子与 PnL/回撤报告；102 项回归及 4/76 账户 1080p/4K 离屏重开通过。已知混合 Z 来源缓存拦截并隔离内部旧试跑。纯 DDB 现有覆盖仅 2025-07-01—2026-10-14，完整 2024 至今仍缺数据；只读一次性补取入口已备，网络连接审批待用户明确回复，自动增量仍后续。源码发布不含行情/真实报告，见[专项说明](dashboard/backtest/CARRY_STUDY.md)与[交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-02 回测接续 `3eaa765`：新增剩余自然日和默认 d0=0 的到期 close 强平，禁止临期新开、保留其他合约；00—03 计算面板、去分红年化/同档历史分位、固定与 Z 阈值 CTA，最终因子/目标/成交均为实际合约，桌面可生成后回测。83 项回归及 1080p/4K、真实数据链路通过；现有分红仅 16 条快照，20 日分位缺历史 D，未填零。交接和接续提示词已补齐；归档核验后清理重复验证/字节码，原数据保留。不依赖 Z 盘，DDB 自动更新后续制作；公司测试已授权、现场仍待执行，见[回测交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-11-02 回测桌面及性能完成：`dashboard/start_backtest.vbs` 独立启动。默认日频收盘风控，自动按输入精度逐报价风控，权益/持仓统一日结；日末指令次日首个共同有效价成交，分钟缺失时在真实日线 close 回退。按需行情、事件核算、分块风控及独立账户/分日读取多进程；共用资金统一结算。62 项回归、真实分钟线对账及 1080p/4K 离屏通过。本机合成稀疏核算 2.070→0.077 秒，密集 4 账户串行/4 进程 2.947→1.820 秒，不代表固定加速倍数。保留数据与成交表接口、手续费万三和总权益万一爆仓阈值；公司现场待验收，见[回测交接](dashboard/backtest/PROJECT_HANDOFF.md)。

- 2026-10-29接续75d9da0，批次 `2026-10-29-company-resilience-and-excel-reconciliation`：下午包只有3个JSON、缺Overview，现场年化/新关闭仍待验收。读取可选资料、单股坏时间和历史I/O错误按范围隔离；年化显示F/S/D/T和D来源，公式不改。两份Excel32行同输入复算一致、15合约D不同。诊断直接进入本轮目录，统一白名单打包按时间/HEAD/配置及同一运行核对，Complete/MissingReports不冒报。210项回归通过；[公司步骤](dashboard/APP_COMPANY_TEST.md)、[证据/待办](dashboard/PROJECT_HANDOFF.md)。

- 75d9da0：2026-10-29公司回传收尾，批次 `2026-10-29-company-feedback-safe-shutdown-and-evidence`，公司证据f345174：24个JSON与截图确认Y读取/导入、16档20日完整及12组ETF收盘NAV/价格；60日D缺556行、IF/IC/IM权重缺1/2/2、IOPV/申赎定义仍缺。App专用成分归档有界并行/批量登记，关闭进度与最终排空；名单/权重和快照质量诊断修正，盘中/收盘溢价标签明确。98项回归通过；1800标的本机合成归档8.884→2.489秒，不代替公司新关闭计时。默认[Runtime复测](dashboard/APP_COMPANY_TEST.md)只需新HEAD、开窗和关闭后Overview及安全JSON ZIP；[当前证据/待办](dashboard/PROJECT_HANDOFF.md)。

- 2026-10-29 日报侧栏整理为交易前查询与日报管理；统计独立为 `statistics_app` 桌面入口，原自动任务和数据位置保留。公司更新后分别通过各模块 `start.cmd` 打开，见 [日报交接](script_making/PROJECT_HANDOFF.md) 和 [统计交接](statistics_app/PROJECT_HANDOFF.md)。

- f345174：2026-10-29确认Y默认源、旧默认运行时迁移和调度重查，SourceDirectory/InputFile、B1窗口及来源审计，当前文档精简与七份唯一SHA归档。55项受影响测试通过（12.676秒）；后续公司真实回传结果以本页最新条目及看板交接为准。

| 看板已发布前序提交 | 内容 | 当时验证 |
|---|---|---|
| 69789a4 | 按需行情分析/TWAP/VWAP/图像/CSV，行业每日有界修复与ETF能力入口 | 272项；含原查询42项 |
| 1408292 | 20卡概览、同级详情、逐卡变化、统一状态、新图标/快捷方式 | 62项 |
| 67c2db6 | 逐日实际合约D、四档连续分位、非交易参考、公盘有界任务 | 229项 |

前序实现均已落地，旧“其余十项待实施”不再作为当前待办。历史测试数字不替代本轮测试或公司真实验收。原规格/说明见 [2026-10-29唯一归档](docs/archive/2026-10-29/README.md)。

- 10月28日日报人工簿记与背对候选：按同标的/所选内部交易台核对候选，多选汇总数量、日期和操作人员，保存人工双向关联及来源快照。186项合成回归、18项界面复验通过；日报常用列筛选/金额阈值/本人开仓/多值标的另有128项及30项界面复验。公司实际日报仍待使用时验证，见 [日报交接](script_making/PROJECT_HANDOFF.md)。
- `c356b65`：统一工作区分类与维护工具；本机旧验证产物压缩校验后移除，真实业务/配置/依赖保留，11项维护回归通过，见 [整理记录](docs/WORKSPACE_CLEANUP.md)。
- `638ee82`、`d2c7299`：公司历史报告的原因传播、安全Wind/ETF返回证据及收盘参考链；对应54/186项历史回归，不证明当前公司进程存活。
- `b778c88`：券源行业、库存市值范围及名称/代码组合筛选；129项券源回归通过。

## 公司更新

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git pull --ff-only
```

关闭并通过原入口重开要更新的应用。看板当前测试见 [APP_COMPANY_TEST.md](dashboard/APP_COMPANY_TEST.md)，无需迁移目录或重装 Wind。Git 出错时保留现场，按 [Git 操作指南](Git操作指南.md) 检查。

## 未来新增项目如何一起同步

在本仓库内建立独立模块，先检查嵌套 Git。维护正式源码、README、AGENTS、PROJECT_HANDOFF、可提交模板和本机忽略规则，原材料、凭据与真实数据只留本机。仍在统一分支按明确清单验证、提交、推送；不新建模块开发分支。项目清单同步更新本页与[目录索引](docs/PROJECT_STRUCTURE.md)。

## 误切开发分支后的恢复

Git 分支影响整个检出，不只影响一个模块。先核对当前目录、分支及未提交工作，再按 [Git 操作指南](Git操作指南.md) 返回适合的统一工作区；不强制切换、reset、clean 或覆盖旧工作。历史工作区及其他 worktree 继续保留。

## 历史发布与验证

更早历史流水保存在[整理前发布归档](docs/archive/2026-10-27/COMPANY_SYNC_HISTORY.md)，近期看板原文见[七份说明归档](docs/archive/2026-10-29/README.md)。旧测试数字、旧分支和旧现场结论属于对应时期，不替代当前交接和公司新回传；精确源码历史以 Git 提交为准。
