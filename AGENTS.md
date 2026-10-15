# Delta1 多项目开发与公司统一更新

公司已确认 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard` 本身就是 Git 仓库根目录。家里主工作目录为 `P:/project/swhy/Delta1/project`，独立 worktree 位置可能不同；每次先用 `git rev-parse --show-toplevel`、`git worktree list`、`git status --short` 确认实际状态。

公司统一使用 **`codex/company-apps`**，操作见 [COMPANY_SYNC.md](COMPANY_SYNC.md)。各模块仍沿用自己的开发分支和 AGENTS/PROJECT_HANDOFF 业务要求；公司同步分支与模块开发分支是两个用途。

交付模块更新时，先按模块要求验证、更新交接、提交并推送其开发分支，再将本次已验证提交合并到 `codex/company-apps` 并推送，让公司通过一次 `git pull --ff-only` 获取更新。仅发布明确属于本次工作的已提交内容；若开发分支夹杂未经验证或无关提交，先隔离整理，不能直接整体合入。

汇总分支保留各模块独立目录和本机数据忽略规则。不要将尚未提交的其他项目混入，不提交真实行情、Excel、缓存、导出或本机配置。使用独立且干净的 worktree 汇总，保护正在进行的开发；不强推，不用 reset/clean、强制切换覆盖已有工作。用户明确要求暂不提交/发布时遵从。

合并冲突时保留双方业务口径，做受影响验证。更新 COMPANY_SYNC.md 的版本/验证记录，并报告公司分支提交号；只有开发分支已推送时不能声称公司统一分支也已更新。真实 Wind 和公司环境的验证与本地模拟测试区分。
