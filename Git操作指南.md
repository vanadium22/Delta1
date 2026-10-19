# Delta1 Git 操作指南

更新日期：2026-10-19。

所有 App 的开发、更新、提交、推送和公司运行统一使用 **`codex/company-apps`**。远端仓库为 [vanadium22/Delta1](https://github.com/vanadium22/Delta1)。在仓库根目录执行一次 Git 操作即可同步全部已提交模块，无需逐个 App 操作。

以下命令用于 PowerShell。每段按顺序执行，出现报错先处理，再继续下一条。`pull` 是下载更新；`push` 是上传本地提交，上传前须先 `commit`。

## 1. 进入项目并确认分支

公司电脑复制这一段：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git rev-parse --show-toplevel
git branch --show-current
git status
```

家里当前的统一分支工作目录复制这一段：

```powershell
Set-Location -LiteralPath 'P:\project\swhy\Delta1\company-apps-worktree'
git rev-parse --show-toplevel
git branch --show-current
git status
```

`git branch --show-current` 应显示 `codex/company-apps`。路径取决于实际电脑，目录名 `dashboard` 或 `company-apps-worktree` 不影响 Git 操作。以后家里也在统一分支工作目录继续开发；原主目录和历史工作目录内的未完成内容保留。

## 2. 日常只接收更新

先关闭正在运行的 App，进入项目根目录后复制：

```powershell
git status
git pull --ff-only
git log -1 --oneline
```

成功后重新打开 App。`Already up to date.` 表示当前分支已无新提交；`--ff-only` 会在本地与远端分歧时停止，避免自动产生合并提交。

## 3. 本地修改后提交、上传

开始修改前先完成上一节的更新。修改、验证完成后先查看差异：

```powershell
git status
git diff
```

再把**本次实际修改的文件**加入暂存区。下例适用于修改券源界面及交接说明；其他任务按 `git status` 显示的路径替换或增减文件名，新文件也需明确列出：

```powershell
git add -- "securities_lending/desktop.py" "securities_lending/PROJECT_HANDOFF.md"
git diff --cached --stat
git diff --cached
```

核对暂存区只含本次代码、测试或说明后，复制以下命令；将提交说明换成本次内容：

```powershell
git commit -m "说明本次修改"
git push origin codex/company-apps
git status
```

`git commit` 会提交暂存区内的所有文件，因此先核对暂存内容。沿用项目约定按文件清单暂存，不使用 `git add .` 或 `git add -A`；真实行情、日报、分红 Excel、缓存、导出、凭据及本机配置均不提交。普通 `push` 会拒绝覆盖远端新增提交，无需加 `--ff-only`，不使用强推。

## 4. push 被拒：远端已有新提交

如果报错包含 `non-fast-forward` 或 `fetch first`，先运行 `git status`。只有本地工作区干净、待上传提交属于自己且尚未推送时，复制：

```powershell
git pull --rebase origin codex/company-apps
```

成功后再上传：

```powershell
git push origin codex/company-apps
git status
```

如有冲突，Git 会停下。编辑并解决冲突文件后，将下面的示例路径替换为实际冲突文件，再执行：

```powershell
git add -- "实际冲突文件的路径"
git rebase --continue
```

若仍有冲突，重复处理，全部完成后再 push。需要取消本次 rebase、恢复到整理前的提交状态时执行：

```powershell
git rebase --abort
```

日常只接收更新仍使用 `git pull --ff-only`。工作区有未完成改动时先保留并处理，不用 `reset --hard`、`clean` 或强制切换清理现场。

## 5. 当前不在统一分支

已有 `codex/company-apps` 工作目录时直接进入该目录。公司如误切到旧分支，先检查 `git status`，确认没有未提交或未发布工作后再执行：

```powershell
git fetch origin
git switch codex/company-apps
git pull --ff-only
```

如果提示分支已在其他 worktree 使用，用 `git worktree list` 找到该目录并进入；不强制重复检出。历史分支保留作记录，后续所有修改都在 `codex/company-apps` 完成。
