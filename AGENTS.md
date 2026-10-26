**2026-10-26 最新授权：按已确认草图实现指数和ETF概览，ETF按同指数基金规模前三、每周复核，行业贡献每分钟汇总。Wind仅用于低频成分、权重、行业及规模资料；现有行情源先核验IOPV，缺数明确显示。保持公司蓝白展示版，先完成外观及可取得的数据，离屏验证后提交推送统一分支；用户在公司回传测试结果。不改第六版32项、期指口径、Excel或VPN政策。当前真实资料缺口与权重日期限制见dashboard/APP_MARKET_OVERVIEW.md；不得以草图构造值冒充真实数据。**

**2026-10-23 看板范围更新：公司日常入口改为展示版 App，覆盖此前仅发布数字 Excel / App 前端 local-only 的限制。Excel 冻结维护且所有历史产物保留；本机展示/开发两版同步必要修复。先完成运行与数据更新、由用户公司主要功能实测，再考虑指标与美术。用户后续明确授权有历史缺口时按需自动连接 DDB 数据 VPN；实时 VPN 仍手动连接，仅盘中连接失败时弹出提醒。此授权覆盖此前不操作 VPN/无弹窗的对应限制，其他操作内联，不抢焦点；开发测试仍离屏且不操作真实 VPN。具体见 dashboard/AGENTS.md、dashboard/APP_COMPANY_TEST.md。**

# Delta1 多项目开发与公司统一更新

2026-10-26 后续用户明确要求：正常实时入口再次打开前，自动正常关闭同数据范围旧看板并等待其后台排空。允许安全替换活跃旧App，不强杀写入者、不删锁、不关闭Excel或其他项目；身份不明或超时则只读。先解决网络锁和ETF采集，指数/ETF概览后续优化等待用户具体反馈。操作和验证见dashboard/APP_COMPANY_TEST.md、APP_VALIDATION.md。

公司已确认 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard` 本身就是 Git 仓库根目录。家里主工作目录为 `P:/project/swhy/Delta1/project`，独立 worktree 位置可能不同；每次先用 `git rev-parse --show-toplevel`、`git worktree list`、`git status --short` 确认实际状态。

**2026-10-19 用户确认的长期约定：所有 App 的开发、更新、提交、推送及公司运行统一使用 `codex/company-apps` 一个分支。** 适用于券源 `securities_lending`、日报 `script_making`、股指基差 `index_futures_basis`、指数策略 `index_strategy`、看板及后续新增模块。不再创建、更新或推送各模块独立开发分支，也不再采用“先推开发分支、再汇总到公司分支”的流程。此要求覆盖各文档和历史交接中的旧分支约定；模块业务口径继续按各自 AGENTS/PROJECT_HANDOFF 执行。可复制命令见 [Git操作指南.md](Git操作指南.md)，发布记录见 [COMPANY_SYNC.md](COMPANY_SYNC.md)。

**用户于 2026-10-15 确认公司首次迁移及配置完成，解压包备份已删除。后续默认在公司仓库根目录执行一次 `git pull --ff-only` 更新整个项目。** 日常交付直接提供这一更新方式，无需重复迁移、下载 ZIP 或切换模块开发分支。整个项目包括公司分支内所有已发布的 Git 跟踪文件；本机配置、分红 Excel、行情库及导出继续由忽略规则保留。

交付任一模块更新时，先在 `codex/company-apps` 对应工作目录修改、验证、更新交接，再按明确文件清单提交并推送这一分支。用户已持续授权将本仓库本次验证通过的代码、测试及说明推送至 `origin`（`https://github.com/vanadium22/Delta1.git`）的 `codex/company-apps`；除用户明确要求暂不提交/推送外，无需每次重复询问。仅发布本次已验证内容，不混入其他未完成工作。公司通过一次 `git pull --ff-only` 获取全部模块更新。

用户明确要求将新项目纳入 Git 时，在本仓库根目录下按独立模块接入，并维护 COMPANY_SYNC.md 的项目清单。先检查是否有嵌套 Git 仓库，划清正式源码/说明/可提交模板与原始材料/真实数据/凭据/本机设置，建立模块忽略规则和 README、AGENTS、PROJECT_HANDOFF。Git 不跟踪空目录，至少提交实际说明文件；项目准备阶段要说明尚无可运行入口。

新模块直接在 `codex/company-apps` 下按独立目录接入，逐项检查并明确暂存文件、验证、提交和推送，核验远端的新模块和原有模块均存在。不要为普通并列模块再创建嵌套 `.git`、新开发分支或要求公司额外 clone。私有材料的本机保留方式要在交接中写清楚。

公司曾按模块旧提示词切回券单开发分支，导致基差源码退出当前检出。维护约定时必须同步检查各模块 README、COMPANY_SETUP、AGENTS 与 PROJECT_HANDOFF 的可复制提示词，全部指向 `codex/company-apps`。恢复说明只引导回到统一分支；不要清理仅剩数据的目录。

优先复用已检出 `codex/company-apps` 的现有工作目录。本机目前为 `P:/project/swhy/Delta1/company-apps-worktree`，每次以实际 Git 状态为准；主目录或旧 worktree 若存在其他未提交工作，保留现场，转到统一分支的工作目录继续。不得为满足单分支要求强制切换、删除历史分支/worktree，或覆盖旧目录中的未完成工作。

保留各模块独立目录和本机数据忽略规则。不要将尚未提交的其他项目混入，不提交真实行情、Excel、缓存、导出或本机配置。不使用 `git add .`、`git add -A` 全量暂存，不强推，不用 reset/clean 或强制切换覆盖已有工作。

远端已有新提交时先检查分歧；个人尚未推送的提交可在工作区干净时 rebase 到 `origin/codex/company-apps`，保留双方业务口径并验证受影响部分。更新 COMPANY_SYNC.md 的版本/验证记录，核验远端统一分支包含本次提交后再报告发布完成及提交号。推送受阻时如实说明。真实 Wind 和公司环境的验证与本地模拟测试区分。
