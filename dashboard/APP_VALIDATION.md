# 看板当前验证与公司验收边界

2026-11-10。基线12f34f1ba7e94776d177344692cdbe56f16f652f，统一分支codex/company-apps。当前变更见 [APP_RELEASE](APP_RELEASE.json)，现场证据见 [PROJECT_HANDOFF](PROJECT_HANDOFF.md)，公司完整命令见 [APP_COMPANY_TEST](APP_COMPANY_TEST.md)。原七份说明只保留 [唯一归档](../docs/archive/2026-10-29/README.md)。

## 最终本地回归

**230项通过，46.355秒，无跳过，ResourceWarning作为错误。**

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
$env:TEMP='P:/project/swhy/Delta1/company-apps-worktree/local_artifacts/validation/company_20261110/tmp'
$env:TMP=$env:TEMP
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest tests.test_overview_etf_display tests.test_overview_zero_dividends tests.test_overview_resilience tests.test_company_safe_return tests.test_market_overview tests.test_market_overview_ui tests.test_futures_overview tests.test_overview_audit tests.test_overview_details tests.test_overview_revision tests.test_overview_company_feedback tests.test_overview_capabilities tests.test_overview_data tests.test_overview_dated tests.test_overview_percentiles tests.test_overview_wind_evidence tests.test_dividend_check_input tests.test_app_pipeline tests.test_app_collection tests.test_realtime_store tests.test_percentile_audit
```

20项新增回归覆盖：16个连续档位每天一条年化、明确0与缺失0区分、补真实历史D后派生缓存版本替换、今日新D不回填旧日、冲突/缺价/映射/当前D仍阻断、独立等值半权分位、真实覆盖与估算可计算分开；有效盘中值优先（含0）、带日收盘主位回退、旧值不假称昨日、当前前三只按代码匹配两期AUM（含前期第四名）、一期不伪造0、未来/损坏档案隔离、同时点规模冲突、归档预算与代次缓存、页面三只规模/数据突出/最新D日期/数值无估后缀。

重跑分红Y默认迁移/调度重查、SourceDirectory/InputFile/B1/原件审计、连续20/60/非交易、行情质量门槛、鲁棒性、主/成分采集、关闭排空、原标准存储和6种真实PowerShell安全ZIP场景。首次历史阶段55项通过；追加ETF前219项、ETF针对性65项以及首轮230项均通过，最终补充AUM读取预算导出断言后再次以上述230项完整重跑。不能用中间数字代替最终结果。命令参数拒绝测试的usage输出属于预期用例。

## 页面离屏检查

1580/860宽窄概览与ETF页面均生成并查看。概览顶部最新分红表日、卡片实际来源日可见；年化与分位数值无“估”后缀，补零信息在悬浮/诊断。ETF主位收盘溢价和日期、加重的规模/占比/买卖价差、仅前三只规模变化显示正常；窄屏重排及滚动，无文字裁切。使用明确标为界面测试的合成数据，未启动可见生产App或操作VPN。

## 公司33份JSON核验

源ZIP 201,026字节，SHA827b9a1feddd74a88873071b5a0f6ab2a06cc1bd118cf0a06e82abb13d5acc4b，full/Complete=true/无MissingReports；git及8个diagnosis均12f34f1。Y Share完整验证B1为10-27/10-30/11-06三表，本地64条/4文件版本（含原09-18）；Import新增0/unchanged4为已缓存，错误为空，配置保留。默认仍用已核验Y路径，不重映射。

16个当前D均取11-06表，对应实际合约逐个相同；9:36实时16行按各自F/S/D/T独立复算最大误差8.8818e-16个百分点。用户随后表示可能比较了旧分红表，仍在自查；未发现当前公式或映射问题。9:28盘前用11-09收盘参考，不能与9:36实时输入混比。

9:36时20日16档完整，60日16档仅缺历史D：00各20日、01/02/03各29日，共428条，价格/映射缺0。新代码可用历史零占位计算，仍须公司更新后检查新分位；真实D覆盖不能因估算可算就宣称齐全。ETF份额/净申赎/PCF及IOPV仍缺已核验定义，规模变化只算真实两期AUM，含净值涨跌影响，有一期则继续缺项。

同一App报告路径从开窗collecting到最终closed/shutdown.complete=true/等待者空，关闭73.499秒；9:36归档1408/1802、已耗51.639秒，最后一轮空归档0.09秒不代表总关闭时间。安全排空已确认，现场性能仍待后续。关闭后陈旧缓存不能反推开窗行情中断。

## 原件与其他工作保护

本轮8,453个文件、365,738,904字节在编辑前记录大小/SHA，含旧行情/缓存/配置/凭据/Excel/依赖、四受保护提示词、原ZIP和七份唯一归档。发布前逐文件复核。APP_RELEASE.backtest值及其原序列化块原样保留，无回测/因子/CTA/32/A02源码修改；其他工作区和进程未操作。

证据、回传解包、测试、截图及发布核验仅在忽略的local_artifacts/validation/company_20261110，不提交原ZIP/真实JSON/数据。默认Overview离线，实时VPN手动，DDB只补真实价格缺口，不强杀写入者、不删锁。既有210/98/55等为前序批次历史结果。
