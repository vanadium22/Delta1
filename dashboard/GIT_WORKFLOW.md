# 对应分支拉取、推送与发布边界

仓库：`https://github.com/vanadium22/Delta1.git`。
分支：`codex/dashboard-history-release-20261019`。
功能基线：`29cc1e1`、`b518a94`。后续文档整理提交跟随同一分支。

本轮维护/诊断代码提交：`9e91d6e77fb60658ba68b0b9650663306b0bc70a`（2026-10-19），父提交 `77f716b`。该提交新增双VPN启动向导、进程退出确认、网络互斥、独立分位诊断和必要回归；新两版前端没有进入提交。本文及交接说明随后作为单独文档提交；离线包最终文档HEAD以 `git bundle list-heads` 和本机 `runtime/release_git.json` 为准。

最新决定（2026-10-19）：用户明确选择“暂不推送，只保留本地提交和离线包”。远程尚无本分支，公司现在应使用下方离线 bundle 导入流程。本文远程命令只供以后明确授权推送时使用，不代表已执行。

## 公司电脑首次获取远程分支

在现有公司仓库根目录执行；先保存本地修改和本机数据，不强制覆盖冲突。

```powershell
git status
git fetch origin
git branch --list codex/dashboard-history-release-20261019
# 尚无同名本地分支时：
git switch --track origin/codex/dashboard-history-release-20261019
# 已有同名本地分支时，改用：
# git switch codex/dashboard-history-release-20261019
# git pull --ff-only origin codex/dashboard-history-release-20261019
git log -3 --oneline
```

若远程没有本分支，说明尚未推送成功或远程权限不对，不要换成拉 main 并认定获得了本模块。若 `--ff-only` 失败，先查看分叉和本地改动，不 reset --hard / force push。

## 后续更新

```powershell
git status
git switch codex/dashboard-history-release-20261019
git pull --ff-only origin codex/dashboard-history-release-20261019
```

代码更新不传输历史数据、分红 Excel、实时库或 DDB 密码。数据包导入和公司账号设置见 [操作清单](COMPANY_CHECKLIST.md)。

## 开发电脑提交与推送

```powershell
git status
git switch codex/dashboard-history-release-20261019
# 使用实际改动文件的明确白名单，不执行 git add . / git add -A
# git add -- dashboard/某个文件.py tests/对应测试.py dashboard/某个说明.md
git diff --cached --stat
git diff --cached --check
# 审核暂存差异及敏感内容，完成相应验证后：
# git commit -m "具体修改说明"
# 仅以后获得用户对该远程的明确推送授权后执行：
# git push -u origin codex/dashboard-history-release-20261019
# git ls-remote --heads origin codex/dashboard-history-release-20261019
```

推送成功后核对远程 SHA 与 `git rev-parse HEAD` 相同。只推该分支，不改 main、不强推、不合并其他业务模块修改。

## 新展示版/开发版暂不 Git 的规则

- 当前已提交的共同看板基线保留，不为新要求回退历史提交。
- 下一轮新增展示版、开发版的页面、入口、图标和展示专用改动，暂不 add / commit / push；Excel 交付物同样不自动上传。
- 维护、计算修复和必要测试/说明可单独提交，但必须在仅含已提交代码的干净目录验证，不依赖尚未提交的界面文件。
- 若公共逻辑与前端修改位于同一文件，先拆分提交内容或模块。不能仅靠一句“没有 add 前端目录”证明隔离。
- 不把本机 Git 全局忽略规则或 skip-worktree 当作隔离方案；保留明确文件清单及当前未提交状态。
- 目前工作区还有 index_strategy/desktop、securities_lending 等其他任务修改，不属于这次提交范围。
- `data/`、`localsetting/`、`.vscode/`、`*.local.*`、`runtime/`、账号密码及其密文均不得强制添加。

## 无网络时导入离线代码包

`dashboard-code-20261019.bundle` 是基于 `003c2e3` 的增量包，公司仓库必须已有基础提交。

```powershell
git bundle verify "完整路径\dashboard-code-20261019.bundle"
# 先导入为远程跟踪样式的引用，避免直接覆盖正在使用的本地分支：
git fetch "完整路径\dashboard-code-20261019.bundle" codex/dashboard-history-release-20261019:refs/remotes/offline/dashboard-history-release-20261019
# 尚无本地分支时：
git switch -c codex/dashboard-history-release-20261019 refs/remotes/offline/dashboard-history-release-20261019
# 已有本地分支时，改用：
# git switch codex/dashboard-history-release-20261019
# git merge --ff-only refs/remotes/offline/dashboard-history-release-20261019
```

不要强制更新已有分叉的 offline 引用；先检查来源和历史。bundle 验证缺少基础提交时，先取得原工程基础历史，或等远程正式发布再 fetch。离线包不会包含本机数据或账号。

## 发布状态

本轮已本地提交维护代码 `9e91d6e`。对候选源码按Git基线加12个维护/测试白名单建立隔离目录，剥离 `current.py` 的前端窗口注入、标题/图标及冻结/展示参数，且不存在 `editions_current.py` 或 `numeric_snapshot.py`。303项回归覆盖均通过：完整运行302项，五个旧打包场景因子进程缺第三方pyqtgraph失败，补齐标准依赖位置后复测39项通过，其中含新增历史0%定位回归。沙箱本地IPC/回环限制用受控测试权限解决；没有因此改动计算口径或跳过失败场景。隔离目录使用现有第三方依赖，未引入工作区未提交应用代码。暂存内容逐文件与验证源码一致。

新两版前端、图标、入口、Excel及导出器继续保留本地，**未add、未commit、未push**。`dashboard/current.py` 仅共同启动部分已提交，前端接入参数仍为未暂存差异；完整清单见 [PHASE4_DELIVERY.md](PHASE4_DELIVERY.md)。已有其他业务模块和研究材料修改未混入。

本轮没有执行push，也没有重新尝试此前被拒绝的推送；未查询远程最新引用，不能声称远程已有本分支。代码bundle按显式分支 `codex/dashboard-history-release-20261019 ^003c2e3` 更新、核验；不使用 `--all`。公司获得共同入口和向导，不含未提交的新两版前端。历史数据zip单独保留，SHA256未变。

可在项目根目录核对：

```powershell
git show --stat 9e91d6e
git status --short
git diff -- dashboard/current.py
git bundle verify dashboard/runtime/distribution/dashboard-code-20261019.bundle
git bundle list-heads dashboard/runtime/distribution/dashboard-code-20261019.bundle
```

遇到冲突或无法快进，先执行 `git status`、`git log --oneline --left-right HEAD...refs/remotes/offline/dashboard-history-release-20261019` 和 `git diff`。保留公司未提交修改和数据，手工复核冲突或另建隔离目录处理；不要reset --hard、git clean、强推或整目录覆盖。确认冲突处理后再单独提交，不能顺手混入其他模块。

此前首次推送曾因外部仓库授权和归属未确认被自动审批阻止，未发送成功；随后用户选择暂不推送。该历史记录不是本轮发起的新审批。本机精确交付头、包哈希及保留文件清单见 `runtime/release_git.json`。
