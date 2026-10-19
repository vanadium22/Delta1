# 对应分支拉取、推送与发布边界

仓库：`https://github.com/vanadium22/Delta1.git`。
分支：`codex/dashboard-history-release-20261019`。
功能基线：`29cc1e1`、`b518a94`。后续文档整理提交跟随同一分支。

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
git push -u origin codex/dashboard-history-release-20261019
git ls-remote --heads origin codex/dashboard-history-release-20261019
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

文档整理提交 `ccc2c07` 已在本地完成，后续状态说明提交包含在更新后的离线包。

首次推送被自动审批阻止：未确认具体外部仓库授权和归属；未发送成功。随后用户明确选择暂不推送，因此本轮不再尝试推送。公司不能通过远程 pull 取得本分支，现阶段使用 `dashboard-code-20261019.bundle`；需要以后推送时须先明确授权具体目标仓库。离线包内容用 `git bundle verify` 核对，本机更新记录在 `runtime/release_git.json`。
