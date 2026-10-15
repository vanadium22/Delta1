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

本次补充汇总：券单分支 `24875ce`（含 `298ed75` 行业联系表功能及公司同步说明修正）、基差分支 `a2cf6ae`（原业务实现及同步说明修正）均已合入。三个模块源码与入口同时保留；index_strategy 本次仅补公司更新说明，原已提交业务实现不变。尚未提交的其他开发工作继续留在原目录。

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

各模块公司说明、交接提示词现已统一为 **codex/company-apps**。公司保持此分支，按各 App 的入口启动；切换 Git 分支会改变整个仓库的源码集合。

## 误切开发分支后的恢复

用户曾执行券单旧说明中的 `git switch codex/securities-lending`，随后发现 `index_futures_basis` 只剩复制过来的数据文件夹。该开发分支未包含基差源码，因此 Git 移除了当前检出中的基差跟踪文件，忽略的本地数据仍保留。恢复无需删除数据、找回已删除备份或重新解压 ZIP。

关闭所有 App，在 PowerShell 整段运行；任何 Git 步骤失败都会停止：

```powershell
& {
    Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard' -ErrorAction Stop
    git fetch origin
    if ($LASTEXITCODE -ne 0) { throw '获取更新失败，已停止。' }
    git switch codex/company-apps
    if ($LASTEXITCODE -ne 0) { throw '切换失败，请保留文件并反馈报错。' }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw '更新失败，请保留文件并反馈报错。' }
    git branch --show-current
    Get-Item -LiteralPath '.\securities_lending\start.cmd', '.\index_futures_basis\start.cmd', '.\index_strategy\start_app.cmd' -ErrorAction Stop | Select-Object FullName
}
```

成功时显示 `codex/company-apps` 和三个启动文件的完整路径。以后保持该分支，只运行日常 pull。若有本地源码冲突，保留现场处理，不强制切换或清理。模块的准确目录名是 `index_futures_basis`（futures 有 s）。

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

### 同步入口修正与补充汇总（2026-10-15）

- 券单、基差各四份文档（README、COMPANY_SETUP、AGENTS、PROJECT_HANDOFF）在各自开发分支修正并推送，交接完整提示词同样要求发布到公司分支。11 个 PowerShell 代码块语法、35 处本地文档链接及 Git 差异检查通过。
- 合并后的券单完整回归 **114 项通过，0 跳过，6.263 秒**；基差完整回归 **48 项通过，0 跳过，17.175 秒**。使用原验证环境，无真实 Wind 或公司共享盘调用。
- 两个 App 的 `--demo --startup-check` 均正常退出（退出码 0）。最终 12 份说明中的 22 个 PowerShell 代码块语法与 47 处本地链接路径检查通过；公司更新的可执行命令均指向统一分支。
- 在项目忽略的 QA 目录创建纯本地隔离副本，实测切到券单开发分支后基差启动文件消失；切回公司分支后，三个 App 入口均恢复，合成分红目录文件、行情目录文件、导出目录文件、配置和 Python 路径文件共 5 份文件 SHA256 全部不变，Git 工作区干净。
- 两个业务模块的合并结果分别与上述开发分支完全一致；指数策略已提交业务代码保持不变。本次未修改 App 业务实现，真实公司恢复操作仍由用户执行。

### 整体更新说明（2026-10-15，ff48f0d）

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
