# 看板当前验证与公司验收边界

2026-11-11。本轮追加基线b1d1f44，统一codex/company-apps；范围为期货分位缺收盘修复，兼容前序DDB端点、数据更新页布局、日期来源与失败阶段。精确文件见[APP_RELEASE](APP_RELEASE.json)，公司操作见[APP_COMPANY_TEST](APP_COMPANY_TEST.md)。

## 最终回归

**395项完整回归通过，110.116秒（含加载），无跳过、ResourceWarning作为错误；原388项全部重跑，新增7项价格/OI隔离、分位恢复、批次隔离和缺口解释回归。** 前序端点/滚动表单/凭据及全部既有回归保持。

标准unittest加载器：local_artifacts/validation/company_20261111_percentile_closes/run_tests.py；完整日志local_artifacts/validation/company_20261111_percentile_closes/full_final.txt，临时文件均在本轮tmp内。等价命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning local_artifacts/validation/company_20261111_percentile_closes/run_tests.py tests.test_app_collection tests.test_app_pipeline tests.test_company_safe_return tests.test_dividend_check_input tests.test_futures_overview tests.test_market_overview tests.test_market_overview_ui tests.test_overview_afternoon_feedback tests.test_overview_audit tests.test_overview_capabilities tests.test_overview_company_feedback tests.test_overview_data tests.test_overview_dated tests.test_overview_details tests.test_overview_etf_display tests.test_overview_final_polish tests.test_overview_percentiles tests.test_overview_resilience tests.test_overview_revision tests.test_overview_wind_evidence tests.test_overview_zero_dividends tests.test_percentile_audit tests.test_realtime_store tests.test_app_launcher tests.test_app_preflight tests.test_app_instance tests.test_workspace_cleanup tests.test_app_history tests.test_app_vpn tests.test_history_maintenance tests.test_history_credentials tests.test_numeric_view tests.test_numeric_vpn tests.test_overview_ddb_refresh tests.test_overview_percentile_close_repair
```

12项新增验证：发布端点和显式覆盖、原连接对象/加密文件与TLS选项保留、TCP和SDK会话使用新端点/同账号密码、11-11盘前目标11-10、同端点准备数据网络、失败不假报完整、三尺寸窗口和按钮/输入框、仅保存地址不读写凭据、无效输入不写、旧密码解密失败不覆盖、价格日与Y盘分红日区分、混合源日期不声称全部最新。

## 分位缺收盘：追加复现

用户已澄清：11-06疑问实际指期货年化分位显示“缺收盘”，应核验20/60窗口的具体期货/指数收盘，不能按顶部Y盘分红日期处理。

本轮追加修复：DDB返回有效OHLC但OI缺失时仍保存收盘，持仓缺口独立保留，不假补0；相同行不重复归档或计作持仓进展。单批ValueError/KeyError/TypeError校验失败保留安全失败明细并继续其他有界任务，网络/SDK错误仍结束本轮。分位悬浮列缺失日期/标的，更新页汇总去重后的收盘缺口。

同一合成回包（IF2611.CFE、2026-11-10、有效收盘4000、OI为空），b1d1f44接受0行，修复后保留1行/收盘4000，raw均保留。独立测试从缺11-10收盘的窗口出发，补收盘后20/60均恢复数值，OI仍pending；重复相同价格返回inserted=0且不重归档，后续真实OI=0才解除持仓缺口。另验证坏ETF批次不挡后续期货日期，而连接失败仍停止后续请求。分位悬浮和更新页说明具体缺项，不调整窗口/公式或用0填价格。

7项新增测试与close_oi_reproduction.json仅本地模拟证据；公司是否缺11-10还是其他历史日、是否命中OI或批次路径，仍需新公司Overview，不能冒称公司已补齐。

首次全量复验在旧刷新队列测试的固定sleep等待上偶发提前交付；独立重查通过，随后改用事件同步确保先切换选择再释放模拟结果。最终395项已完整重跑通过，不修改业务队列或放宽原断言。

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
