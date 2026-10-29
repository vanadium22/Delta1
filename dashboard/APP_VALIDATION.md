# 看板当前本地验证与公司验收边界

2026-10-29。本轮从69789a419391e627615c03b6ac284251da3a7ab5接续已有未提交补丁；统一分支codex/company-apps。发布文件清单见 [APP_RELEASE.json](APP_RELEASE.json)，公司步骤见 [APP_COMPANY_TEST](APP_COMPANY_TEST.md)。

## 最终受影响回归

**55项通过，12.676秒，无跳过，ResourceWarning按错误处理。** 包含此前尚未运行的旧成功调度状态迁移测试；旧51项未作为最终结果。审查前52项通过后，增加B1窗口/来源汇总/设置不改配置等覆盖，最终完整重跑以下组合：

```powershell
$env:QT_QPA_PLATFORM='offscreen'
$env:DELTA1_THEME='public'
$env:TEMP='P:/project/swhy/Delta1/company-apps-worktree/local_artifacts/validation/company_test_20261029/tmp'
$env:TMP=$env:TEMP
& 'P:/code_content/anaconda/install/python.exe' -B -X utf8 -W error::ResourceWarning -m unittest tests.test_dividend_check_input tests.test_overview_dated tests.test_app_pipeline tests.test_overview_audit tests.test_overview_capabilities
```

最终日志仅在忽略目录 `local_artifacts/validation/company_test_20261029/release_tests_final.log`。参数拒绝用例的argparse错误和合成历史缺项返回2为预期断言，不是未解决失败。

覆盖包括：确认Y源/旧默认迁移、保留自定义/显式空白、必要跨年目录、旧成功状态重查、设置显示有效源但不写原配置；InputFile显式性/互斥/原件与配置保护/内容去重/跳过公盘；SourceDirectory临时覆盖与原配置目录分列；全库日期不被单个配置Excel覆盖，当前与历史D按各自定价时点选择。

新增B1反例：文件名在窗口外但表内业务日在窗口内仍导入；表内窗口外/未来日不自动导入；同批SHA重复只解析一次，元数据不变复查不再读取文件。本地构造真实.xlsx通过Windows CMD→PowerShell→Python/私有reader，验证中文空格InputFile、中文年份目录SourceDirectory、文件名01-02而B1为10-27、Share不发布及原配置未变。

原逐日分红/连续16档20与60/非交易合法配对/共同收盘/昨日D版本、派生缓存/SQLite关闭、AM/PM重启去重及采集/补齐/停止写入边界一并通过。所有页面验证离屏，实际入口测试使用隔离本地输入，没有触发真实公司Wind/HTTP/DDB或VPN。

## 文档、脚本与原件保护

当前AGENTS、交接、市场规则、验证和实施入口只保留最新状态。七份旧说明的归档字节数/SHA256及69789a4基线内容已核验，未修改归档payload或MANIFEST，新增一个索引；基线比较只正规化换行。这7份归档在.gitattributes中单独禁止Git换行转换，暂存及提交对象逐个核验原始SHA，避免公司拉取改变归档字节。原十项规格保留于OVERVIEW_IMPLEMENTATION_SPEC，旧规则不覆盖当前授权。

APP_COMPANY_TEST的7段PowerShell经Windows PowerShell解析，13次诊断脚本调用参数对照真实CMD/PS入口。108处当前文档本地链接已核验。安全打包片段用隔离目录实跑完整与缺失/无效两种场景，包含中文空格路径及混入的伪配置/原始日志/Excel反例；完整ZIP为25个JSON，异常场景21个JSON并列明缺项，不复制原始文件或修改业务目录。实际结果和清单仅在本轮忽略的验证目录。

本轮保护清单记录8,444个现存文件，365,291,740字节，覆盖原配置/数据/依赖、原Excel、四份提示词及先前保护输入；发布前逐文件复核大小/SHA，无变更或丢失。未对其他工作区或无关进程执行修改/关闭。语法、文档链接、JSON清单、git diff检查及APP_RELEASE精确文件集合核对完成后发布。

## 历史测试只作对应批次证据

| 已发布提交 | 当时范围 | 当时结果 |
|---|---|---|
| 67c2db6 | 日期版本D、四档连续分位、非交易参考、公盘有界任务 | 229项，82.431秒 |
| 1408292 | 20卡/同级详情、状态、图标/真实COM快捷方式 | 62项，33.617秒 |
| 69789a4 | 行情分析/行业有界修复/ETF能力及原查询 | 272项，56.756秒；另16项资源边界 |

本轮未重跑全部272项，不将历史数字合并或套作公司验收。旧证据原文见 [唯一归档](../docs/archive/2026-10-29/README.md)，历史日志/数据仍保留原位置。

## 尚未完成的公司验收

本机没有Y映射，未读取公司真实公盘或取得新公司接口报告。此前WinError53针对旧源，本机WindPy缺模块也不能推断公司；公司既往报告已确认WindPy存在。当前本地测试只证明代码/本地入口及隔离数据行为。

尚待公司同次HEAD、LocalRoot与解释器确认；Y源Share/Import和真实B1/SHA/16合约来源及历史D覆盖；正常任务真正发布行业/权重/ETF排名/NAV及持续60秒覆盖；运行中Overview、20卡/非交易参考、查询/取消和关闭耗时。IOPV/份额/PCF仍需可靠字段/单位/带日定义，mapping_required不冒充可用。

默认Overview离线、实时VPN手动、30秒/3秒、原数据/配置/凭据/Excel、研究32项/A02暂停且保留均继续；不因HTTP失败切DDB，不强杀写入者。
