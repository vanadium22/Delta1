# 看板当前验证与公司验收边界

2026-11-10。本轮基线1b621fc18ee433db8ab593b325d79e2b7872755a，统一分支codex/company-apps，批次2026-11-10-company-display-resilience-and-final-retest。精确文件见[APP_RELEASE](APP_RELEASE.json)，现场证据见[PROJECT_HANDOFF](PROJECT_HANDOFF.md)，[一键/完整手动命令](APP_COMPANY_TEST.md)。七份旧说明只保留唯一SHA归档。

## 最终本地回归

**247项通过，54.683秒，无跳过，ResourceWarning作为错误。** 本轮17项新增；包含原230项受影响回归，最终在页面主题/比例修正后完整重跑，不沿用中间37/69/108项或前次230项结果。

实际入口为忽略证据目录中的run_tests.py（unittest标准加载/执行，隔离临时目录，Windows多进程有main保护）；等价标准命令如下：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
$deltaTestTemp=Join-Path (Get-Location) 'local_artifacts/validation/company_resilience_20261110/tmp'
New-Item -ItemType Directory -Path $deltaTestTemp -Force | Out-Null
$env:TEMP=$deltaTestTemp
$env:TMP=$deltaTestTemp
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest tests.test_overview_final_polish tests.test_overview_etf_display tests.test_overview_zero_dividends tests.test_overview_resilience tests.test_company_safe_return tests.test_market_overview tests.test_market_overview_ui tests.test_futures_overview tests.test_overview_audit tests.test_overview_details tests.test_overview_revision tests.test_overview_company_feedback tests.test_overview_capabilities tests.test_overview_data tests.test_overview_dated tests.test_overview_percentiles tests.test_overview_wind_evidence tests.test_dividend_check_input tests.test_app_pipeline tests.test_app_collection tests.test_realtime_store tests.test_percentile_audit
```

新增覆盖：三个月日期边界、现有Wind字段/单位/真实日期/缺值、单只坏历史保留/隔离、NAV齐而规模缺时独立有界调度、默认不补全成分DDB而显式完整模式保留、部分行业篮子与指数权重区别、滚动成分独立时效/未来值拒绝、每批先发布再下一批、HTTP失败保留旧值、无自动Parquet时raw/SQLite/原归档保留、分类显示跨进程重开/只读不写/原源时、新有效部分优先/新价不套旧基差、显示偏好不改native配置、1080p比例和条形数值、真实slot图例颜色及一键脚本真实PowerShell安全JSON ZIP。旧分红迁移/调度/导入、连续20/60、历史缺D暂0/真实补齐、非交易参考、期现30秒/3秒、排空/锁/原标准存储及6种安全包用例一并通过。

异步失败/重试测试等待实际任务调用及busy解除（两秒上限），替换原固定50毫秒假设，避免离屏布局负载引发偶发误判。中间运行暴露的旧UI文本/资料门槛断言已按用户新口径更新；未弱化时间倒置、缺真实当前D/缺价/映射或写入者排空要求。

## 离屏与本机性能

1920×1080及1536×864（对应1080p屏幕125%系统缩放逻辑尺寸）的概览/指数/ETF/期货八图已生成检查。中比例横/纵滚动范围均0，20卡完整；大比例概览纵滚动673，保留原字号；小比例也有回归覆盖。ETF数字重点、带日收盘溢价、规模三值/变化和三个月曲线可见；期货条形/色块/引导线与实际slot一致。窄屏860原有重排/交互测试通过；图表及按钮沿用蓝白主题。全部为明确标记的合成界面测试，没有可见生产窗口或真实VPN操作。

本机合成1850成员显示缓存分三类约1,458,433字节，首次原子保存0.0743秒；1850行/19批raw+SQLite提交0.1944秒，关闭0.0032秒，新Parquet文件0。旧归档未变。这里只检验本机新路径，不与公司73.499秒当作同输入加速比较，也不承诺现场相同耗时。用户原逐股Parquet、SQLite/raw及旧显式归档/安全排空能力保留。

## 公司验收边界

最新完整公司包仍为20261110_092411_072_safe_094017_545_23667ca4.zip（201,026字节、SHA827b9a1feddd74a88873071b5a0f6ab2a06cc1bd118cf0a06e82abb13d5acc4b、33JSON、HEAD12f34f1、full/Complete=true）。已证Y三表B1=10-27/10-30/11-06，64条/4版本；Import新增0/unchanged4为已缓存。16实际合约D均对应11-06表，实时F/S/D/T复算吻合。用户可能比较旧表，未盲改公式。旧20日16档完整，60日仅缺历史D428条、价格/映射0；占位可算与真实覆盖分开。

旧同次开窗→最终closed/shutdown.complete=true，关闭73.499秒；最后空归档0.09秒不是总关闭时间。214只未分类、旧权重日期保留。IOPV/份额/PCF缺定义，不由规模变化替代。

本轮Wind三个月真实覆盖/前期规模、部分行业/轮询、全卡比例、缓存恢复和新关闭耗时仍待公司一键复测新包。默认Overview离线，实际发布由正常任务完成；开窗与关闭后必须同一运行。Complete仅代表反馈结构完整，不代表所有行情/可选数据已验收。

## 原件保护

8,453文件、365,738,904字节逐一复核：大小/SHA全同，无缺失或变化，含原行情/分红/缓存/配置/凭据/Excel/依赖、四受保护提示词、原ZIP、七份唯一归档与MANIFEST。APP_RELEASE.backtest对象及原序列化块保留；其他研究/因子/CTA/回测源码、旧worktree和进程未操作。

本轮测试/截图/性能/保护/发布证据仅忽略的local_artifacts/validation/company_resilience_20261110；旧包解读在company_20261110。原ZIP、真实JSON、配置/业务数据不提交。不强杀写入者、不删锁、不重映射Y，不使用reset/clean/全量stage/强推。
