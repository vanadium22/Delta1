# Delta1 公司统一开发约定

当前日期：2026-10-29。所有 App 的开发、验证、提交、推送和公司运行统一使用 `codex/company-apps`。看板本轮从75d9da0接续公司回传与Excel输入对账，当前状态见 [PROJECT_HANDOFF](dashboard/PROJECT_HANDOFF.md)，公司Y读取/导入与收盘折溢价已有证据，历史D、完整行业输入、IOPV/申赎及新关闭耗时仍有待办。

## 工作区与发布

- 公司 Git 根：`D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`；一次 `git pull --ff-only` 更新整个仓库，再正常重开相应应用。
- 当前统一工作区：`P:/project/swhy/Delta1/company-apps-worktree`。每轮核验 `git rev-parse --show-toplevel`、分支、worktree、status、diff及远端；已有修改先审查，保留其他工作。
- 用户持续授权本次必要实施、测试及向 `https://github.com/vanadium22/Delta1.git` 的统一分支提交推送。按精确文件清单暂存，更新交接、APP_RELEASE及COMPANY_SYNC，核验远端后报告提交号。本地验证与公司验收分开。
- 优先复用适合的当前检出。旧主目录及其他worktree可能有未提交工作，不为统一分支而强制切换或覆盖它们。不使用reset/clean、全量stage、强推，不建立各模块新开发分支。
- 远端有新提交先检查分歧，保留双方工作；不在脏工作区盲目rebase或覆盖。

## 数据与模块保护

正式源码、说明和无真实数据的模板可提交。原行情、分红、SQLite/Parquet、Excel、缓存、导出、材料、配置、凭据、诊断报告与运行依赖保留原位，不混入发布。验证输出放忽略的 `local_artifacts/validation/<任务日期>/`。

四份既有未跟踪文件不修改、不提交：`dashboard/INDICATOR_REDESIGN_ANALYSIS.md`、`dashboard/NEXT_INDICATOR_REDESIGN_PROMPT.md`、`dashboard/NEXT_PRESENTATION_APP_PROMPT.md`、`dashboard/NEXT_UI_SIMPLIFICATION_PROMPT.md`。其他模块、旧工作区、Excel和实际用户进程按各自边界保留。

新项目在本仓库下按独立模块接入：先检查嵌套Git，建立README、AGENTS、PROJECT_HANDOFF及本机忽略规则，划清源码/模板与真实材料，更新COMPANY_SYNC项目索引；不另外clone或创建模块开发分支。

## 看板当前要求

以 [dashboard/AGENTS](dashboard/AGENTS.md)、[市场口径](dashboard/APP_MARKET_OVERVIEW.md) 和 [公司测试](dashboard/APP_COMPANY_TEST.md) 为准：逐日实际合约D、四档连续20/60分位、简单去分红年化、20卡和非交易参考保留；研究32项/A02暂停且保留。默认Overview离线、实时VPN手动、写入者安全排空。

用户确认分红公盘源为 `Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`。Y:映射192.168.91.230；本轮公司drive_y.json已记录DisplayRoot为 `\\192.168.91.230\FTPServer`，仅作现场映射证据，默认仍用Y路径，不猜拼或重新映射。业务日期以Sheet1!B1为准。旧内置UNC仅作运行时迁移匹配，不能再当公司已核验地址。

## 文档与历史

当前固定入口保留，文档只写当前口径和待办。七份旧说明已按SHA归档一次，见 [归档索引](docs/archive/2026-10-29/README.md) 与MANIFEST；不要重复复制或将归档AGENTS当当前指令。历史“仅分析”“固定分红情景”“不得真实测试”等冲突段落不覆盖用户最新授权。其他模块长期口径仍读其自身AGENTS/交接。
