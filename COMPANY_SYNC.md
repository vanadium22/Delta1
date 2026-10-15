# 公司所有 App：统一更新

更新日期：2026-10-15。

公司确认的仓库根目录是 **`D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard`**，远端是 `https://github.com/vanadium22/Delta1.git`。这个目录名称不影响 Git，不用重建仓库或再套一层 dashboard。

公司统一使用 **`codex/company-apps`**，其中并列放置：

```text
dashboard/                        # 公司 Git 仓库根目录
  .git/
  index_strategy/
  securities_lending/
  index_futures_basis/
  config/
  tests/
```

本次汇总保留原提交历史，将基差分支 `008a31f` 和券单分支 `f4a51b5` 合并。index_strategy 保留已提交的 42 个文件；家里尚未提交的 index_strategy 改动、另一个实际 dashboard 子目录及 research 不在本次公司发布中。这里的“所有 App 一次更新”指公司分支已经发布的代码，Git 不会自动收集其他开发分支或未提交工作。

## 首次从当前状态切入（只做一次）

用户提供的公司状态：当前券单分支 `4219d7d`；没有已跟踪文件的本地修改；唯一未跟踪目录是刚解压的 `index_futures_basis/`。

1. 关闭正在运行的 App，在上述 dashboard 文件夹打开 PowerShell。
2. `git fetch origin` 获取远端分支。若失败先处理连接，不继续切换。
3. 把**整个**未跟踪 `index_futures_basis` 文件夹改名为 `index_futures_basis_zip_backup_日期时间`，保留其中全部文件。不要直接在未备份的解压目录上强制切换，Git 会因同名未跟踪代码而阻止覆盖。
4. 运行 `git switch codex/company-apps`，再运行 `git pull --ff-only`。只有一个 origin 远端时，Git 会从同名远端分支创建并跟踪本地分支。
5. 把备份内实际存在的 `inputs`、`input`、`data`、`exports`、`config.local.json`、`python.local.txt` 复制回新的 `index_futures_basis` 对应位置。如果设置里指向外部数据目录，保留配置和外部目录即可。旧 Python 源码不用复制回来，备份目录先保留。
6. 运行 `git branch --show-current` 应显示 `codex/company-apps`，`git status --short` 正常应为空。然后用各模块原来的启动脚本启动。

若首次操作中途失败，备份仍在原仓库内，先保留现场并提供报错，不删除目录、不用 reset/clean/强制切换。若开始操作时出现新的已跟踪代码修改，应先保留并处理修改。

## 以后日常更新

关闭 App，在这个 dashboard 目录运行：

```powershell
git pull --ff-only
```

它会一次更新公司分支中所有已发布模块。分红表、行情库、缓存、导出和本机配置由模块忽略规则保留，不需要重新下载或重新配置。若你修改了 Git 跟踪的源码且与新版本冲突，Git 会停止更新，先保留修改，不要强行覆盖。

启动方式仍是：

```powershell
.\securities_lending\start.cmd
.\index_futures_basis\start.cmd
.\index_strategy\start_app.cmd
```

旧模块说明里的开发分支同步命令仍用于开发；**公司日常运行统一停留在 codex/company-apps**。不要在公司轮流切券单/基差开发分支，否则会丢失统一版本视图。

## 后续开发与发布

券单继续在 `codex/securities-lending`、基差继续在 `codex/index-futures-basis` 开发，各自保留交接和测试。模块完成后，除推送模块分支，还要把已验证改动汇总到 `codex/company-apps`；公司才能一次 pull 获取。根目录 AGENTS.md 已记录这一流程。

继续开发的提示词可在原模块提示词末尾补充：

> 公司统一使用 codex/company-apps。完成本模块验证并推送开发分支后，请将本次已验证提交汇总、验证并推送到公司分支，更新 COMPANY_SYNC.md。保留其他模块、未提交修改和本机数据，不使用强推或 reset/clean。

## 本次验证

本次为已有提交的汇总，不修改两个 App 的业务实现。2026-10-15 在隔离工作目录实际验证：

- 基差 App 完整回归 **48 项通过，0 跳过**，耗时 16.992 秒；使用已有 bundled Python 3.12.14、PySide6 6.11.2 及原开发绘图库。
- 券单 App 完整回归 **104 项通过，0 跳过**，耗时 5.632 秒；使用本机 swhy_delta1 Python 3.13.15、PySide6 6.11.2。测试中的本机回环 HTTP 服务已正常运行。
- 两个 App 分别执行 `--demo --startup-check`，均正常退出（退出码 0）；没有访问真实 Wind 或公司共享盘。
- 合并后的 index_futures_basis 与 `008a31f` 完全一致，securities_lending 与 `f4a51b5` 完全一致，index_strategy 与原已提交版本完全一致。原开发目录的未提交工作保留。
- 公司目录、分支和解压包状态依据用户返回的检查结果。首次迁移、公司真实 Wind、公司网络与实际显示环境仍需在公司执行验证；本地回归不代表这些环境已通过。
