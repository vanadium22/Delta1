# 看板当前验证与公司验收边界

2026-11-11。基线d4c2b9b，统一codex/company-apps；范围为DDB端点、数据更新页布局、日期来源与失败阶段。精确文件见[APP_RELEASE](APP_RELEASE.json)，公司操作见[APP_COMPANY_TEST](APP_COMPANY_TEST.md)。

## 最终回归

**388项通过，103.581秒（含加载；unittest执行102.020秒），无失败、无跳过，ResourceWarning作为错误。** 前轮298项全部重跑，加入历史/凭据/VPN/数字版兼容与12项本轮回归。中间测试夹具的空history_roots及清理后Mock参数断言已修正，最终结果不沿用中间失败。

标准unittest加载器：local_artifacts/validation/company_20261111_ddb_layout/run_tests.py；完整日志full_final.txt，临时文件均在本轮tmp内。等价命令：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning local_artifacts/validation/company_20261111_ddb_layout/run_tests.py tests.test_app_collection tests.test_app_pipeline tests.test_company_safe_return tests.test_dividend_check_input tests.test_futures_overview tests.test_market_overview tests.test_market_overview_ui tests.test_overview_afternoon_feedback tests.test_overview_audit tests.test_overview_capabilities tests.test_overview_company_feedback tests.test_overview_data tests.test_overview_dated tests.test_overview_details tests.test_overview_etf_display tests.test_overview_final_polish tests.test_overview_percentiles tests.test_overview_resilience tests.test_overview_revision tests.test_overview_wind_evidence tests.test_overview_zero_dividends tests.test_percentile_audit tests.test_realtime_store tests.test_app_launcher tests.test_app_preflight tests.test_app_instance tests.test_workspace_cleanup tests.test_app_history tests.test_app_vpn tests.test_history_maintenance tests.test_history_credentials tests.test_numeric_view tests.test_numeric_vpn tests.test_overview_ddb_refresh
```

12项新增验证：发布端点和显式覆盖、原连接对象/加密文件与TLS选项保留、TCP和SDK会话使用新端点/同账号密码、11-11盘前目标11-10、同端点准备数据网络、失败不假报完整、三尺寸窗口和按钮/输入框、仅保存地址不读写凭据、无效输入不写、旧密码解密失败不覆盖、价格日与Y盘分红日区分、混合源日期不声称全部最新。

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
