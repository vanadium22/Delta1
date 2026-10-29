# Delta1 公司看板当前交接

更新：2026-10-29。本轮从69789a419391e627615c03b6ac284251da3a7ab5接续现有补丁，发布批次 `2026-10-29-confirmed-y-dividend-source-and-company-retest`，统一分支 `codex/company-apps`。实际提交号以 `git log -1`、远端分支及本次交付回复为准，文件清单见APP_RELEASE.latest_update.files。公司真实源、资料发布和持续页面仍待验收。

## 本轮已完成

1. 默认分红源改为用户确认的Y路径，旧内置UNC只在运行时迁移；其他自定义源和显式空白保留，原个人配置不自动改写。设置显示有效源，调度指纹包含有效源，旧默认源当天已成功也须重新检查。
2. Local/Share/Import新增显式SourceDirectory、InputFile及CMD/PowerShell桥接：SourceDirectory仅本次Share/Import，InputFile仅Import本地指定Excel，互斥；InputFile不运行公盘同步，原文件/配置保留。
3. 来源报告包含实际扫描年份目录、匹配文件名样本、请求范围、B1业务日期、当前16合约D的生效时间/SHA/继承来源、原配置文件位置/SHA、有效与原配置目录、缓存位置。修复本地单文件日期覆盖全库日期汇总的问题。
4. 年份目录中不再按文件名日期提前排除输入。同步按解析后的Sheet1!B1筛选历史窗口，窗口外/未来业务日不自动导入；保留元数据和SHA去重，同批相同内容只解析一次。显式InputFile可追加指定历史文件，不用当前表回填旧日。
5. 七份旧说明已核验原有SHA与69789a4基线内容，未重复归档；当前AGENTS、交接、市场口径、验证和旧实施提示词精简为最新状态，固定路径和归档索引保留。
6. 公司完整步骤及仅JSON白名单ZIP统一在 [APP_COMPANY_TEST](APP_COMPANY_TEST.md)，另见 [下一对话提示词](docs/NEXT_COMPANY_RETEST_PROMPT.md)。

本轮受影响组合最终55项通过（12.676秒，无跳过，ResourceWarning作为错误），含此前未运行的调度迁移用例；初轮52项为审查前证据，旧51项和此前229/62/272项不冒充本轮最终结果。真实Windows CMD测试通过本地构造Excel，未访问公司源。完整检查、保护与脚本验证见 [APP_VALIDATION](APP_VALIDATION.md)。

## 正确源和运行位置

```text
Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026
```

Y:映射到192.168.91.230，完整UNC共享名未知，不猜拼、不重新映射。2026为年份目录，匹配指数基差情况_*.xlsx，业务日以Sheet1!B1为准。原内置UNC不等于公司已核验共享名。

| 位置 | 当前路径 |
|---|---|
| 本机统一工作区 | P:/project/swhy/Delta1/company-apps-worktree |
| 公司Git根 | D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard |
| 公司LocalRoot | 公司Git根/dashboard/localsetting/app |
| 本机原配置 | P:/project/swhy/Delta1/project/dashboard/localsetting/native.json |
| 公司入口 | dashboard/start_presentation.vbs，显式public；CMD兼容入口保留 |
| 默认新分红库 | LocalRoot/overview_dividends，实际自定义路径看audit.sources.store_directory |

开发机没有Y映射，未取得公司真实文件或新接口结果。此前旧源WinError53和本机WindPy缺模块仅是开发机历史证据，不能推断公司目录或Wind环境错误。

## 公司待验收顺序

使用 [APP_COMPANY_TEST](APP_COMPANY_TEST.md) 在同一PowerShell顺序执行：

1. 正常关闭旧看板并等写入结束，核对统一分支，git pull --ff-only，保存本轮HEAD与Y映射元数据。
2. Local(before)→Y源Share→Y源Import→Local(after)，可选InputFile指定本地下载表。看同步读取/导入证据与历史覆盖两类结果；退出2可能仅历史D未齐。
3. 显式Wind Connect/Indices/ETFs及ETF Local/能力测试；这些只读阶段不发布正式资料，IOPV/份额/PCF缺核验定义时仍为mapping_required。
4. 正常打开看板，必要时点一次DDB一键补齐，等待正常任务发布Wind资料并按真实缺口补概览日线；实时VPN手动。观察20卡、行业/ETF和分钟覆盖10–15分钟。
5. 保持窗口开着运行Nav与默认离线Overview；生成仅含白名单JSON的ZIP，记录缺失报告，回传并注明窗口/页面/关闭耗时。不得压缩LocalRoot、原始日志或业务数据。

真实公司验收需同次HEAD、Y盘读取/B1/导入、逐日历史D及16卡来源、行业权重/昨收/NAV正式发布和持续页面证据。历史资料齐备、只读测试成功或一次行情非空都不能代替这些条件。缺可靠IOPV/份额/PCF定义继续保留缺项，不宣称四项全可用。

## 已交付功能与长期边界

| 已发布批次 | 已实施 | 当时本地验证 |
|---|---|---|
| 67c2db6 | 逐日实际合约分红、连续四档20/60缓存、非交易合法配对/共同收盘参考、公盘有界任务 | 229项 |
| 1408292 | 4指数＋16期货卡、同级详情、逐卡变化、统一状态、新图标与公司快捷方式 | 62项 |
| 69789a4 | 原服务行情分析/TWAP/VWAP/图像/CSV、独立缓存/取消、行业每日有界修复及ETF能力CMD | 272项 |

当前/历史简单去分红年化为100*(F-S+D)/S*365/T；各历史日用当时D，不回写。明确0优先，缺D仅向当时已知前序到期合约继承。当前定价日排除，T<5单列，真实缺价/映射/D不跳过；价格参考日/T/D和30秒/3秒规则不变。主HTTP三秒，成分一分钟。

研究32项/A02继续暂停且源码、原独立App及Excel保留；只补概览日线，不恢复研究分钟全库。默认Overview离线，自动Wind低频，手动行情分析仅选定窗口。实时VPN手动；DDB仅实际缺口按原授权准备，不因HTTP失败切DDB。自有只读SDK/SMB可取消，正式写入者排空，不强杀、不删锁。

原行情/分红/缓存/配置/凭据/Excel、其他工作区及四份旧提示词保持；验证产物只在忽略的local_artifacts/validation。发布不用全量stage、reset/clean或强推。

## 历史索引

七份旧说明与原十项规格统一见 [2026-10-29归档](../docs/archive/2026-10-29/README.md) 及MANIFEST。旧“尚未实施/仅分析/固定分红情景/不得真实测试”等阶段描述不再用于当前操作。下一对话先读本页与 [新提示词](docs/NEXT_COMPANY_RETEST_PROMPT.md)，先审查新报告和最新Git，不从旧版本重新实现。
