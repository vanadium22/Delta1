# 看板当前验证与公司验收边界

## 2026-11-12 概览及指标刷新

2026-11-12，统一分支codex/company-apps，实施基线95869c2，最终运行版本以Git HEAD/远端为准。指标页数值按原行情计算更新，图像在页面激活期间每30秒重画并标图像更新时间；缺项显示原因。概览突出00–03，去掉概览上的较昨基差变化；20/60分位并列同窗均值/中位数及日期，越接近两端越高亮；概览新增四品种期限/成交/持仓，指数页新增行业权重变化，ETF页新增全部现有订阅的总览表。

490项独立完整回归通过，123.232秒（含加载），无跳过，ResourceWarning作为错误；原469项重跑，新增21项。 40个去重模块，完整模块、输出与计时见local_artifacts/validation/company_20261112_overview_refresh。新增验证固定窗口样本、两端颜色、30秒快照、盘后回退与当前D、行业可比归档、四档实时/日线持仓和期限断线、ETF全订阅表、PowerShell stderr/退出码及安全JSON序列化。实际Qt主窗口125%缩放、1536×864和860×620逻辑尺寸离屏合成截图已检查，无真实行情或VPN操作；公司最新代码的真实盘中更新、Z/分位、图表数据和同次排空仍待复测。

新公司包20261111_154729_881_safe_160539_083_91d394e8.zip，8886字节，SHA256 cbb1e517a16a39a252a69690bfe0ef4f4b522dcf456df8f1f84c2834fb38c262；95869c2、7份JSON且CRC正常，但Complete=false，开窗与关闭后overview.json均缺失，缺少同次安全排空证据。两次诊断均报System.Management.Automation.RemoteException/NativeCommandError，preflight退出0；没有原始stderr，不能据此确定Z/分位为何为空、DDB状态或同次关闭完成。

本轮开发机对192.168.198.77:8904做一次3秒TCP探测，3022毫秒超时；未使用凭据、修改VPN或查询数据，只表示开发机当前不可达，不覆盖旧包中的公司端连通证据。

旧b7d5d55公司包独立证实11-10四指数和16实际期货收盘、16个20日与16个60日分位，日期为corroborated_live_session推定；DDB existing_tunnel/tcp/authenticated/query_partial，仍缺16期货OI及12 ETF收盘；同次安全关闭2.731秒。旧包不验证95869c2或本轮新页。

保护基线8457文件、365909135字节；最终SHA和回测原序列化块检查见本轮protection_result.json。

## 以下为前序验证

## 11月11日正式指标页与新公司包

实施基线39760f0，运行版本见Git HEAD。469项独立完整回归通过，105.841秒（含加载），无跳过，ResourceWarning作为错误；原438项全部重跑，新增31项指标页回归。

39模块，标准unittest加载器去重；完整模块、全文及计时见local_artifacts/validation/company_20261111_indicator_page/full_modules.json、full_final.txt、full_result.json。新增31项包括公式、窗口、图外历史、真实逐日映射/断线、缺D/冲突/缺价隔离、缓存重算、实时新鲜与三腿3秒配对、所选日线维护参数不保存配置、白名单证据及主Qt窗口/冻结快照。两项原导航断言按新增同级页更新，研究Service仍未构造。

100%/125%实际Qt主入口离屏截图各三尺寸已检查；1536×864逻辑尺寸/125%对应1920×1080像素，四图完整可见、无横纵滚动，输入框39逻辑像素。860×620单列、统计移到图下并正常滚动。测试均隔离合成输入，未打开可见测试窗口，不当公司屏幕验收。统计参考线两端等于t_w边界，线值等于t_z均值/中位数，换合约/缺项连接掩码验证通过。新模块/测试Ruff F及改动Python未定义名检查通过。

新公司安全包20261111_141737_345_safe_143604_770_d37cd87a.zip已核验：b7d5d55、9份JSON/CRC完整，11-10四指数＋16实际期货close齐备，16档原20/60年化分位全部恢复；HTTP日期依据为corroborated_live_session（推定，非交易所认证）。DDB在192.168.198.77:8904复用existing_tunnel、tcp_verified=true、authenticated=true，已到query_partial；当前仍待16合约OI及12只ETF收盘。同次运行安全关闭2.731秒，waiting为空，成分sqlite_committed。

包119408字节，SHA256 4bd430f9185aba8faf62412f436898fd80bc65290397db3c5ddc417b5dc3e874；同run_path、9JSON、Complete=true/MissingReports=[]。20缓存日期均11-10、身份匹配、source_date_basis均corroborated_live_session。维护首轮18项，两项源时未推进被拒后在主采集补齐。包没有原始双raw，因此只核验安全报告保留的推定依据，不声称独立检验了未回传raw。

开窗及关闭后页面引擎预览均16年化/16个20日/16个60日分位可用，F/S/D/T公式复算一致；原历史专用诊断的percentile为空不等于页面为空。当前D来源11-06，20日暂0为0，60日暂0共412样本行，真实旧D仍缺。最终28个计划行=16期货OI+12 ETF close；14:18:09的pending_close_rows=14早于另外两项HTTP补入，不能反推16期货当前仍缺close。7.623秒旧运行排除；本次f80a70e关闭complete、waiting=[]、2.731秒。

本机2026-11-11 15:06的新端点TCP仅3秒超时，source_query=false、vpn_changed=false、config_changed=false；没有额外登录或打印秘密，不覆盖公司已认证query_partial证据。新页真实市场及公司屏幕仍待验收。

冻结8456文件/365900249字节，四提示词、原数据/配置/凭据/Excel/依赖/ZIP和七份唯一归档按大小/SHA检查；APP_RELEASE.backtest对象及原序列化块不变，最终结果见本轮protection_result.json。真实报告/截图/探测仅本机忽略目录，不入发布。

## 前序记录

以下为b7d5d55及更早提交当时的记录，测试数量、旧包缺项和“尚未实现”仅描述对应历史阶段；当前结论以上文为准。


## 11月11日指标页方案交接（仅文档）

运行源码为b7d5d55，下面438项结果属于该版本；本次未改运行代码、未重跑或增加正式App回归。新增页仍处分析/模拟示意阶段，四项统计统一t_z、均值/中位数虚线跨t_w，跨期分母同日指数S已确认。要求见docs/INDICATOR_PAGE_PROPOSAL.md。

模拟示意的JavaScript语法、四品种合成公式、t_w/t_z与图外样本、排末日/等值半权/样本标准差/零方差，以及品种/档位/统计曲线/虚线/查看方式/保存恢复交互完成离线核验。320/736/1024三种假定容器下SVG数据坐标和标签边界检查通过；没有浏览器实际渲染或正式Qt新页验收，不能据此声称1080p公司显示通过。无真实行情或外部数据请求。证据：local_artifacts/validation/company_20261111_indicator_proposal。

本次保护按编辑前重新冻结的8455文件/365780841字节核对，APP_RELEASE.backtest原对象及原序列化块、四份未跟踪保护文件、七份唯一归档均保持；最终清单/SHA见本轮protection_result.json。HTTP/DDB和11-10、原20/60的公司复测仍待新安全包。

2026-11-11，基线596839d，统一codex/company-apps。用户要求修复HTTP，并追加DDB不暂停、下轮一起测；源文件、完整发布清单及命令见APP_RELEASE/APP_COMPANY_TEST。

## 最终回归

**438项独立完整回归通过，103.831秒（含加载），无跳过、ResourceWarning作为错误；原420项重跑，新增18项连续会话证据、日期边界、缓存重算与DDB隧道复用验证。**

标准unittest加载器，37个模块去重执行，无重复计数。完整模块清单full_modules.json、run_tests.py/full_final.txt均在local_artifacts/validation/company_20261111_http_session；离屏、隔离临时目录。针对性96项/13.103秒先通过，最终以438项完整重跑为准。Ruff对新模块/新测试的F检查，以及全部受改Python的F821/F822/F823检查通过，源码不写字节码。

## 公司已证事实

新包20261111_130843_453_safe_132818_292_0006d0f5.zip，116909字节，SHA256 7c2f6f6f2ffdd82794abd8684da089f667a7aade7e820a4e3eda0fb32ca918de：596839d、9JSON完整、CRC正常，同次开窗/关闭、排空6.494秒。HTTP20标的全部source_trade_date_missing，inserted=0/cached_closes为空；DDB有效端点192.168.198.77:8904，stage=route、waiting_vpn、汇总login码，未到SDK认证/查询。四指数+16期货缺11-10，16当前年化有值但20/60全空。login汇总代码不能直接认定VPN密码错误。用户随后说手动已可连通，需新一轮验证。

前一30937eb包9JSON完整、同次关闭7.762秒：12:58午休计算预览有16档分位，定价日实际11-09；13:00切到今日后11-10缺价仍阻断。不能把旧收盘参考或包Complete当昨日已补齐。这两包核验结果分别保留在company_20261111_previous_feedback和company_20261111_http_feedback。

## HTTP新逻辑的本地验证

真实公司接口常见的缺显式日期/createTime=updateTime=0形状，经两次市场数值和源时钟推进且昨收稳定的合成回包，首次不保存，第二次才落11-10 F/S。两个raw文件SHA留证，交易日仍标会话推定且exchange_date_certified=false。补价后20/60均50%，同一MarketOverviewEngine缓存失效后亦恢复；推定数量/日期进入窗口原因，不在数字旁加“估”。更早缺口不从HTTP倒推，当前OHLC/OI不搬到昨天。

静止内容/只改服务元数据、冻结/倒退/错误速率时钟、源时陈旧、非连续时段、明确旧日/冲突日期、坏实际身份均拒绝。跨日/跨午休及120秒过期重新积累；昨收变化需重新两次稳定，缺失/篡改第一份raw SHA不放行；损坏证据文件安全重建。最多两次请求、协作取消、显式仅源日期开关、正常原缓存不覆盖和安全白名单亦通过。

DDB未停用。集成测试在HTTP两批之后仅把残余历史/OI交DDB，原数据VPNauto仍执行；模拟新地址已可达时mode=existing_tunnel且不调用登录器，再建立DDB会话并安全关闭。原端点/凭据/SSL、VPN互斥/实时手动、32/A02暂停、公式/逐日D/四档20与60及全部前序回归保持。

本机一次有界HTTP直连复测在沙箱外超时，未读账号密码或操作VPN、未写原行情；http_probe_direct.json只有本机网络证据。此次没有新公司接受的HTTP/DDB收盘结果，不把合成证据当公司修复成功。

公司复测PowerShell另以隔离的Git/开窗/正常关闭适配器走完原打包器：9JSON、Complete=true、MissingReports为空、ZIP CRC正常，配置秘密未入包；未打开真实App或操作VPN。当前脚本提示同时核验HTTP会话推定和DDB现有隧道复用。

## 原件保护

本轮冻结8455文件/365780841字节，全部大小/SHA不变；一份前序下载ZIP在本轮编辑前已不存在，记录preexisting_absent.json。APP_RELEASE.backtest原对象及原序列化块、四受保护提示词和七份唯一SHA归档保留。 两份本轮回传ZIP也已纳入保护，完整产物只放本机忽略目录。

## 前序UI与端点证据（本轮未重复联网）

## UI实测

修改前更新页展开后的最小窗口高度1264像素，超过1080p；与用户填写框挤压现象一致。新页整体滚动、分组设置及可收起诊断，输入框40像素、行距12像素。

| 请求尺寸 | 实际尺寸 | 最小输入框高度 | 展开后垂直滚动最大值 |
|---|---|---:|---:|
| 1920×1080 | 1920×1080 | 40 | 996 |
| 1536×864 | 1536×864 | 40 | 1212 |
| 860×620 | 860×620 | 40 | 1506 |

before/after_settings_*及布局JSON保留于本轮证据目录，采用合成空配置/离屏检查，无可见窗口或真实VPN操作。原概览真实viewport点击、字号、双饼图及20卡布局回归仍通过。实际主入口另以隔离配置离屏/只读打开设置页并捕获settings_production_entry.png，安全退出且配置字节未变；公司新页需更新后现场核验。

## 新DDB地址与源端验证边界

本机实际凭据引用P:/project/swhy/project/dolphindb_data/config/connection.local.json已是192.168.198.77:8904，TLS及DPAPI配置保留，已有历史Python具备DDB SDK。这是本机配置事实，不证明公司忽略配置已改。

2026-11-11 09:36上海时间，既有数据范围互斥锁内进行有界只读验证：沙箱内TCP被10013拒绝；获准沙箱外复测为3秒TCP超时。尚未建立数据库会话或查询11-10，source_query=false、vpn_changed=false、config_changed=false。因此未验证新源11-10实际供给，不能把超时归因公司VPN或声称源端没有昨日数据。安全证据ddb_source_probe.json，不导出原异常文本或账号密码。

本地模拟证明新端点同时用于App数据网络与数据库会话、账号密码/TLS沿用原提供器，11-11盘前目标正确为11-10，失败保留旧缓存。默认Overview诊断仍离线；其connection字段是配置说明，不是连接成功证据。maintenance.matches_current_target区分旧任务，运行中history_update包含安全阶段。11-06若标“最新分红表”，来源Y盘B1；真实价格停旧日仍需公司同次报告判断原因。

## 公司既有证据与保护

最近公司包仍HEAD b5746c7、9JSON完整、同一运行安全关闭6.153秒，16档OI×价格×乘数复算一致且使用11-09日线。当前D11-06、428历史D零占位、1798/1800股票及214分类缺失不因本轮测试变成齐备。本轮没有新公司ZIP或Share/Import证据。

编辑前冻结8454文件/365652979字节，包括原行情/分红/缓存/配置/凭据/Excel/依赖、四提示词、ZIP及七份唯一SHA归档/MANIFEST；最终逐项大小/SHA一致。原DDB账号密码文件不重写；APP_RELEASE.backtest对象与原序列化块不变。真实报告、截图、探测证据仅local_artifacts/validation/company_20261111_ddb_layout，均不进入Git；其他模块/worktree保留。
