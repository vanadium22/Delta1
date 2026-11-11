# 看板当前验证与公司验收边界

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
