# 看板文档索引

2026-11-12四品种期限结构坐标续改，统一codex/company-apps，实施基线2acf89c，运行版本以Git HEAD/远端为准。IF/IH/IC/IM的概览和股指期货详情均共用同合约、同到期日的缺项缓存回退；旧点标沿用及源时，T<5、换档或到期修订不错误沿用。每个品种每天首次有可用点时纵轴设为最小年化减2至最大年化加2（百分点），数据在范围内波动不缩放；越界时仅向外扩展被突破的一端，后来首次出现的新档补足2个百分点余量，次日重新初始化。横轴使用已知合约期限，当日不收缩；概览与详情共用各品种范围。范围在本次看板运行期间保存，重启按当时可用点重新初始化。

543项完整回归通过，136.377秒（含加载），无跳过，ResourceWarning作为错误。 用户暂不制作分发压缩包，独立Python运行时、离线依赖、干净数据分发清单及新电脑验收继续留待后续。

以下前序记录与本轮结果不一致时，以本轮结果为准。

2026-11-12期限结构与同事配置续改，统一codex/company-apps，实施基线da2aca5，运行版本以Git HEAD/远端为准。概览及股指期货页年化曲线共用每档回退：当前有效优先，缺项沿用同实际合约、同到期日的完整F/S/D/T，空心点及“沿用”、混合时点和原源时可见；每个期现仍须3秒配对，换档/到期修订及T<5不错误沿用。无真实历史值不伪造。

537项完整回归通过，135.572秒（含加载），无跳过，ResourceWarning作为错误。 用户暂不打包：本轮未制作或发送分发ZIP，也未制作完成可搬运Python运行时或完整离线wheelhouse。后续打包需准备适用于同事机器的独立Python和依赖、经允许的数据与概览缓存，使用白名单并排除个人配置、凭据、Git历史、运行日志及备份；在干净Windows目录解压、断网启动并验证后，才可称解压即用。现有数据包按根目录定位，迁移后仅重定位其自身历史路径和看板生成的本地账户引用，不覆盖用户自定义路径。

以下前序记录与本轮结果不一致时，以本轮结果为准。

2026-11-12行业变化补全，统一codex/company-apps，实施基线a628472，最终运行版本以Git HEAD及远端为准。完整同口径历史比较优先；历史不全时按成分代码及真实权重日期配对，或在行情样本覆盖更高时按现有权重和有效成分涨跌估算。标题明确“部分成分”或“涨跌估算”，显示样本数、基准日期、缓存状态和百分点；缺项不补零、未知行业保留“待分类”。无可信权重或行情时仍显示真实缺项原因；公司新图效果待更新后验收。

510项完整回归通过，130.731秒（含加载），无跳过，ResourceWarning作为错误；较上版新增14项。 公司安全包20261112_111531_749_safe_113124_158_68fd3bf7.zip，130457字节，SHA256 1e80ae4ff4d06748b8688e90c9bfef746296063321ec7a7e2da08f6cfadd101a，运行a628472；9份JSON、CRC正常、Complete=true、MissingReports=[]。同一515050c运行正常关闭7.247秒、waiting=[]，成分sqlite_committed。两次Overview及preflight退出0、stderr为空。

以下前序记录与本次结果不一致时，以本次记录为准。

2026-11-12公司复测续改，统一codex/company-apps，实施基线da50685，最终运行版本以Git HEAD/远端为准。概览将每个指数、四个期货卡及该品种期限/成交/持仓图合为一行，1080p/125%中比例无需滚动；小窗口可滚动以保持可读。ETF总览增加蓝色表头、交替底色、涨跌/折溢价颜色并放大字号；指标图最新点加大。行业变化缺项显示可比失败原因，并在安全报告中保留每品种判断摘要；不把缺失权重伪造为零。

公司安全包20261112_100603_500_safe_103108_772_2f9c3359.zip，121515字节，SHA256 faa33f5818c8f3fbfabeeabb6a76cc0197ddbf2061d7d2ad0bcf2486fcbdcc6f，运行da50685；9份JSON/CRC正常、Complete=true/MissingReports=[]，同一f12c8a运行开窗、正常关闭3.355秒、waiting=[]，成分sqlite_committed。两次Overview与preflight均退出0、stderr为空。

496项独立完整回归通过，136.744秒（含加载），无跳过，ResourceWarning作为错误；原490项重跑，新增6项。

2026-11-12，统一分支codex/company-apps，实施基线95869c2，最终运行版本以Git HEAD/远端为准。指标页数值按原行情计算更新，图像在页面激活期间每30秒重画并标图像更新时间；缺项显示原因。概览突出00–03，去掉概览上的较昨基差变化；20/60分位并列同窗均值/中位数及日期，越接近两端越高亮；概览新增四品种期限/成交/持仓，指数页新增行业权重变化，ETF页新增全部现有订阅的总览表。

新公司包20261111_154729_881_safe_160539_083_91d394e8.zip，8886字节，SHA256 cbb1e517a16a39a252a69690bfe0ef4f4b522dcf456df8f1f84c2834fb38c262；95869c2、7份JSON且CRC正常，但Complete=false，开窗与关闭后overview.json均缺失，缺少同次安全排空证据。两次诊断均报System.Management.Automation.RemoteException/NativeCommandError，preflight退出0；没有原始stderr，不能据此确定Z/分位为何为空、DDB状态或同次关闭完成。

490项独立完整回归通过，123.232秒（含加载），无跳过，ResourceWarning作为错误；原469项重跑，新增21项。

2026-11-11，统一codex/company-apps，实施基线39760f0，最终运行版本以Git HEAD/远端为准。新增同级“指标分析”正式Qt页，一品种切换IF/IH/IC/IM，基差两图＋03−02/02−01跨期年化两图。四项统计统一可调t_z，默认min(20,floor(t_w/2))交易日；t_w默认90自然日，均值/中位数水平虚线横跨t_w，跨期分母为同日指数S。原逐日实际D、简单年化、连续四档固定20/60保持，32项/A02研究继续暂停。

新公司安全包20261111_141737_345_safe_143604_770_d37cd87a.zip已核验：b7d5d55、9份JSON/CRC完整，11-10四指数＋16实际期货close齐备，16档原20/60年化分位全部恢复；HTTP日期依据为corroborated_live_session（推定，非交易所认证）。DDB在192.168.198.77:8904复用existing_tunnel、tcp_verified=true、authenticated=true，已到query_partial；当前仍待16合约OI及12只ETF收盘。同次运行安全关闭2.731秒，waiting为空，成分sqlite_committed。

469项独立完整回归通过，105.841秒（含加载），无跳过，ResourceWarning作为错误；原438项全部重跑，新增31项指标页回归。 [指标页实现与口径](INDICATOR_PAGE_PROPOSAL.md)、[接续提示词](NEXT_COMPANY_RETEST_PROMPT.md)已更新；四份受保护旧提示词保持。

| 分类 | 文件 |
|---|---|
| 日常打开/复测 | [常用入口](../常用入口/README.md)，原脚本和桌面入口仍可使用 |
| 当前交接与下一对话 | [PROJECT_HANDOFF](../PROJECT_HANDOFF.md)、[可复制新提示词](NEXT_COMPANY_RETEST_PROMPT.md) |
| 公司完整操作 | [一键复测CMD](../company_retest.cmd)、[APP_COMPANY_TEST](../APP_COMPANY_TEST.md)：更新、Y盘/指定文件分红、行业/ETF、开窗/关闭后Overview、安全JSON ZIP |
| 发布与本地验证 | [APP_RELEASE精确文件清单](../APP_RELEASE.json)、[APP_VALIDATION](../APP_VALIDATION.md)、[统一更新](../../COMPANY_SYNC.md) |
| 当前数据口径 | [市场概览](../APP_MARKET_OVERVIEW.md)、[数据能力/字段契约/行情分析](DATA_CAPABILITIES.md)、[本地字段模板](etf_fields.example.json) |
| 使用与开发规则 | [README](../README.md)、[打开方式](../打开方式.md)、[AGENTS](../AGENTS.md) |
| 十项已实施与原始规格 | [当前实施入口](NEXT_OVERVIEW_IMPLEMENTATION.md)、[原规格唯一归档](../../docs/archive/2026-10-29/OVERVIEW_IMPLEMENTATION_SPEC.md) |
| 连接及刷新诊断 | [连接](../CONNECTION_DIAGNOSIS.md)、[刷新](../REFRESH_DIAGNOSIS.md)、[短文件名](../SHORT_FILENAMES.md) |
| 保留的研究/实现契约 | [32项第六版](../APP_INDICATORS_V6.md)、[数据契约](../data_contract/README.md)、[盘中工作区](../INTRADAY_WORKSPACE.md)、[指标实现](../INDICATOR_IMPLEMENTATION.md)、[合约对指标](../PAIR_INDICATORS.md)；研究服务暂停 |
| 冻结Excel/旧部署/方案 | [旧公司部署](../COMPANY_SETUP.md)、[数字Excel](../NUMERIC_EXCEL.md)、[旧检查单](../COMPANY_CHECKLIST.md)、[Excel提案](../EXCEL_UX_PROPOSAL.md)、[界面方案](../UI_SIMPLIFICATION.md) |
| 历史说明与哈希索引 | [2026-10-29七份唯一归档](../../docs/archive/2026-10-29/README.md)、[MANIFEST](../../docs/archive/2026-10-29/MANIFEST.json)、[更早README](../../docs/archive/2026-10-27/DASHBOARD_README.md) |

AGENTS、PROJECT_HANDOFF、APP_RELEASE、APP_COMPANY_TEST等固定入口保留。归档的ROOT_AGENTS/DASHBOARD_AGENTS不是当前指令入口；旧UNC、旧固定分红情景和阶段限制不覆盖最新用户要求。不重复制作多套旧说明。项目总体目录见 [分类索引](../../docs/PROJECT_STRUCTURE.md)。

2026-11-11：DDB端点192.168.198.77:8904与原凭据分离、更新页分组滚动、价格日/DDB目标/Y盘分红日独立显示。388项本地回归通过，新端点源端11-10与公司布局仍待现场核验；详见当前交接/验证及公司操作。
