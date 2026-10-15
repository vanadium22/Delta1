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

首次汇总保留原提交历史，将基差分支 `008a31f` 和券单分支 `f4a51b5` 合并，发布说明提交为 `f9dc705`。index_strategy 保留已提交的 42 个文件；家里尚未提交的 index_strategy 改动、另一个实际 dashboard 子目录及 research 不在该次公司发布中。这里的“整个项目一次更新”指公司分支中所有已发布的 Git 跟踪文件，包括各模块、公共配置模板、测试和说明；Git 不会自动收集其他开发分支或未提交工作。

## 当前状态与默认更新方式

**2026-10-15 用户确认：公司首次迁移、配置已完成，原解压包备份已删除。此后直接更新整个项目，无需再次备份解压目录、恢复数据或逐个切换模块分支。**

关闭 App，在 PowerShell 运行：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
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

券单继续在 `codex/securities-lending`、基差继续在 `codex/index-futures-basis` 开发，各自保留交接和测试。任一现有或新增模块完成后，除按模块约定推送开发分支，还要把本次已验证改动汇总、验证并推送到 `codex/company-apps`；公共说明和配置模板也通过公司分支发布。公司日常只需一次 pull。根目录 AGENTS.md 已记录这一流程。

交付时核验远端公司分支确实包含本次提交，再报告公司分支提交号和上述统一更新命令。若仅更新了开发分支，须明确说明尚未发布到公司分支。保持既有本机数据忽略规则，不提交真实数据、不混入其他未提交工作。

继续开发的提示词可在原模块提示词末尾补充：

> 公司统一使用 codex/company-apps。完成本模块验证并推送开发分支后，请将本次已验证提交汇总、验证并推送到公司分支，更新 COMPANY_SYNC.md。保留其他模块、未提交修改和本机数据，不使用强推或 reset/clean。

## 首次迁移资料（历史记录，新机器才需要）

原公司状态为券单分支 `4219d7d`，唯一未跟踪目录是刚解压的 `index_futures_basis/`；当前公司电脑已完成以下步骤，无需再执行。

1. 关闭 App，确认 Git 状态并保留本地修改。将完整解压目录改名为 `index_futures_basis_zip_backup_日期时间`。
2. 若仓库只抓取券单分支，先执行 `git config --replace-all remote.origin.fetch '+refs/heads/*:refs/remotes/origin/*'`，再执行 `git fetch origin`。曾出现 `fatal: invalid reference: codex/company-apps`，此步骤用于让普通 fetch 获取所有远端分支。
3. 在尚无本地同名分支时，执行 `git switch --track -c codex/company-apps origin/codex/company-apps`。任何一步失败都停止处理，不继续 pull，不强制覆盖文件。
4. 将备份内分红 Excel（inputs/input）、data、exports、config.local.json、python.local.txt 恢复到新模块目录；外部数据路径继续使用原配置。保留新版本源码。
5. 确认 App 正常使用、配置与数据已恢复且路径不指向备份后，可自行删除备份。不要使用 reset/clean 清理目录。

## 验证记录

### 本次说明更新（2026-10-15）

- 根据用户反馈记录公司迁移完成、备份已删除；日常入口统一为仓库根目录的一次 `git pull --ff-only`。
- 本次仅修改根目录 README.md、AGENTS.md、COMPANY_SYNC.md。检查文档命令、链接、差异与空白格式；业务代码、配置和数据均无变化，未重新运行 App 测试。
- 以下 152 项测试及演示启动结果属于首次汇总验证；公司迁移成功来自用户反馈，真实 Wind 和公司实际运行环境未由本机再次验证。

### 首次汇总验证（2026-10-15）

本次为已有提交的汇总，不修改两个 App 的业务实现。2026-10-15 在隔离工作目录实际验证：

- 基差 App 完整回归 **48 项通过，0 跳过**，耗时 16.992 秒；使用已有 bundled Python 3.12.14、PySide6 6.11.2 及原开发绘图库。
- 券单 App 完整回归 **104 项通过，0 跳过**，耗时 5.632 秒；使用本机 swhy_delta1 Python 3.13.15、PySide6 6.11.2。测试中的本机回环 HTTP 服务已正常运行。
- 两个 App 分别执行 `--demo --startup-check`，均正常退出（退出码 0）；没有访问真实 Wind 或公司共享盘。
- 合并后的 index_futures_basis 与 `008a31f` 完全一致，securities_lending 与 `f4a51b5` 完全一致，index_strategy 与原已提交版本完全一致。原开发目录的未提交工作保留。
- 公司目录、分支和解压包状态依据用户返回的检查结果。首次迁移当时待验证，现已由用户反馈完成；公司真实 Wind、网络与实际显示环境不属于上述本地回归结果。
