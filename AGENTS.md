# Delta1 公司统一开发约定

2026-11-11，统一codex/company-apps，基线596839d。用户授权继续修复HTTP，并明确DDB不暂停、下轮同时复测。HTTP缺显式交易日时，仅在连续交易时段用两次已归档行情交叉核验：同实际代码/稳定昨收、真实市场字段变化、源时钟随接收时间推进且新鲜；通过后按交易日历补准确前一日close，并明确标注corroborated_live_session/日期推定，不能声称交易所认证日期。盘前/午休/盘后、静止或陈旧快照、冲突日期及换日/换时段证据不放行。 用户最新要求DDB不暂停，继续原自动数据VPN/历史补齐；已手动连接且新地址192.168.198.77:8904可达时复用现有隧道，不重复登录。实时VPN仍手动，原DDB/VPN配置、账户密码和原文件不改。 438项独立完整回归通过，103.831秒（含加载），无跳过、ResourceWarning作为错误；原420项重跑，新增18项连续会话证据、日期边界、缓存重算与DDB隧道复用验证。 公司596839d包已证HTTP20个标的全因source_trade_date_missing补入0，DDB停route/waiting_vpn/login，11-10四指数+16期货收盘缺失。本轮新会话推定方案与用户修复后的DDB连接仍待新公司包，不以本地模拟代替源端验收。

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
