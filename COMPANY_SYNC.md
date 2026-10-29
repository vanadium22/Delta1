# 公司统一更新与发布

所有应用、开发与公司运行统一使用 `codex/company-apps`。公司在原 Git 根目录一次 `git pull --ff-only` 更新全部已发布模块；原配置、凭据、数据和未完成工作保持原位。

## 当前模块

| 模块 | 职责 | 交接 |
|---|---|---|
| dashboard | 蓝白市场概览、数据编排；研究页暂停，32项源码及Excel保留 | [看板交接](dashboard/PROJECT_HANDOFF.md) |
| securities_lending | 券源下载、查询、行业与金额筛选 | [券源交接](securities_lending/PROJECT_HANDOFF.md) |
| script_making | 交易前日报查询、人工簿记和日报管理；兼容既有统计自动任务 | [日报交接](script_making/PROJECT_HANDOFF.md) |
| statistics_app | 独立统计桌面入口，复用原统计实现和数据 | [统计交接](statistics_app/PROJECT_HANDOFF.md) |
| index_futures_basis | 独立基差、分红、期限结构及报告 | [基差交接](index_futures_basis/PROJECT_HANDOFF.md) |
| index_strategy | 历史 / 实时采集与兼容桌面工具 | [采集接口](index_strategy/instant_dld/README.md) |
| shared_data | 公共目录、数据登记与原有迁移 | [公共数据说明](SHARED_DATA.md) |

## 最近发布

- 2026-10-29 日报侧栏整理为交易前查询与日报管理；统计独立为 `statistics_app` 桌面入口，原自动任务和数据位置保留。公司更新后分别通过各模块 `start.cmd` 打开，见 [日报交接](script_making/PROJECT_HANDOFF.md) 和 [统计交接](statistics_app/PROJECT_HANDOFF.md)。

- 2026-10-29看板收尾批次 `2026-10-29-confirmed-y-dividend-source-and-company-retest`，基线69789a4：确认Y盘默认源、旧默认运行时迁移及调度重查；SourceDirectory/InputFile显式桥接与互斥；B1业务日期筛选、来源/全库日期/16合约D审计；当前文档精简，七份旧说明保持唯一SHA归档。最终55项受影响测试通过（12.676秒，无跳过，ResourceWarning作为错误）。公司完整更新/导入/行业ETF/开窗Overview/安全JSON ZIP步骤见 [APP_COMPANY_TEST](dashboard/APP_COMPANY_TEST.md)，本地证据见 [APP_VALIDATION](dashboard/APP_VALIDATION.md)，精确清单见 [APP_RELEASE](dashboard/APP_RELEASE.json)。**公司真实Y取数、历史D覆盖、资料发布与持续页面仍待验收**。实际当前提交号由git log与远端分支核验，不用基线号冒充本轮提交。

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
