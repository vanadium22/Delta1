# 公司已有项目：数字 Excel 按顺序启用

## 2026-10-20 DDB VPN自动登录补充

先按下一节更新到统一分支最新代码，保留全部本机数据和配置。已重跑 `configure_numeric_history.cmd` 更正数据库账号密码即可，不必重建环境；该入口只改数字版数据库连接设置，保留VPN配置及历史路径。数据库账号与VPN账号是两套凭据。

第一次在公司启用自动VPN，运行：

```powershell
$env:SWHY_DELTA1_PYTHON = 'D:\conda\envs\swhy_delta1\python.exe'
.\dashboard\configure_numeric_vpn.cmd
```

输入VPN网关（HTTPS及端口）、经核验的网关证书SHA256指纹、VPN账号和密码。密码不回显，使用当前Windows用户DPAPI加密，只保存本机 `dashboard/localsetting/numeric_excel/ddb_vpn.local.json`；证书指纹保存在同目录 `ddb_vpn.trust.local.json`。数据库配置文件仍是 `ddb.connection.local.json`。`native.json` 新增的只有 `history_vpn_config`、`history_vpn_trust` 和可选 `history_vpn_powershell`；修改前备份数字配置副本。

公司若已有**本机当前用户**加密的VPN配置和匹配信任文件，可引用既有完整路径，免重复录入：

```powershell
.\dashboard\configure_numeric_vpn.cmd --reuse-config '本机已有sslvpn.json完整路径' --trust-file '本机已有sslvpn.trust.local.json完整路径'
```

自动登录复用已有深信服客户端，需要PowerShell 7（`pwsh.exe`）；启动向导本身仍用Windows PowerShell，DDB沿用已配置的Python。配置器依次检查指定路径、环境变量 `SWHY_SSLVPN_POWERSHELL`、PATH及常见已有位置；未找到时可填写现有pwsh.exe路径，或回车以后配置并继续手动连接，不会盲目安装环境。证书变更、验证码/二次认证或登录失败会停止自动尝试，提示手动连接后重试。

正常使用顺序：

1. 不带 `-ReadOnlyCache` 启动数字Excel，选择“检查并补齐”。
2. 选择“自动连接并补齐”；已连接的DDB网络直接复用，只有实际缺口需要查询且网络不通时才登录。也可选“已手动连接，开始补齐”。
3. 等待历史结果；有剩余缺口或错误时不算补齐成功。取消也要等窗口确认进程退出。
4. **历史任务退出后，手动退出/切换DDB VPN，连接实时行情VPN**，再点“验证并打开”。程序不自动断开或切回；时段外提醒切回后只读打开。

只读或使用现有数据不会触发DDB自动登录。代码更新无需重新导数据包，凭据不进入Git。开发机已验证自动VPN登录、DDB只读常量查询及连接关闭；未据此声称公司补齐或公司自动登录验收通过。

## 2026-10-20 精简界面与历史向导更新

先关闭本次数值Excel及启动器，保留其他Excel和全部数据/配置。公司已在统一分支，无需切换。源码有本地修改时先保留并处理冲突，不能强制覆盖：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git status --short
if ((git branch --show-current) -ne 'codex/company-apps') { throw '分支不符，停止并保留现场' }
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '更新失败，停止；不要强制覆盖' }
git log -1 --oneline
$env:SWHY_DELTA1_PYTHON = 'D:\conda\envs\swhy_delta1\python.exe'
.\dashboard\start_numeric_excel.cmd
```

先选“使用现有数据”，再按提示连接公司行情VPN、验证打开。概览/指标各自E3切换00—03，确认品种合约、卡片数值与数据时点；不要用计算时间判断新行情。非接入时段直接只读进入。想直接只读测试界面可用原 `-ReadOnlyCache`；该参数会跳过向导。

DDB可之后在公司配置：

```powershell
.\dashboard\configure_numeric_history.cmd
```

输入本机DDB地址/端口/账号/密码、SSL及**已有**DDB Python路径；没有SDK时先确认已有环境，不盲目重装原swhy_delta1。密码本机加密，配置仅保存到数字副本。之后重新打开，选择“检查并补齐”，按顶部说明自动或手动连接历史网络；任务退出后手动切回行情VPN。普通代码更新无需导入数据包，不覆盖整个data或Wind库。

需要核验界面时，原只读诊断命令仍可用；新增window.view和overview_match_feed核对正在看的卡片，不仅核对隐藏原始表：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
& 'D:\conda\envs\swhy_delta1\python.exe' -B -X utf8 -m dashboard.numeric_diagnose --samples 2 --interval 10
```

公司是否已更新、DDB实际连通/补齐及本次界面连续运行仍待实机反馈；开发机合成通过不能代替这些验收。下面保留早先首次部署资料，当前更新按本节。

已启用后的普通代码更新无需重新安装数据包。早先“界面似乎未刷新”的诊断见 [REFRESH_DIAGNOSIS.md](REFRESH_DIAGNOSIS.md)：公司11:06曾确认60e5446、实际Python及同一可见工作簿；当时ReadOnlyCache且配置中的实时SQLite不存在，显示历史收盘。该记录不代表已取得本次精简界面，请按本节更新；以下第3—4节供缺环境/首次配置时参考。

长期分支为 `codex/company-apps`。公司现有 `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard` 本身是仓库根目录；下面的 `dashboard\start_numeric_excel.cmd` 是新增模块入口，两个 dashboard 是正常的层级。路径若已改变，以 `git rev-parse --show-toplevel` 为准。

仅确需短文件名迁移或安装数据时，按 [SHORT_FILENAMES.md](SHORT_FILENAMES.md)。不能只替换 ZIP 或覆盖整个 data；新包需用安装器激活，旧 Wind 和配置保留。已有兼容数据不因本次代码更新重导。

## 1. 先检查现场

关闭使用该项目的 App 和数字 Excel，保留原项目目录及现有备份。以下命令只检查，不修改文件：

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git rev-parse --show-toplevel
git branch --show-current
git status --short
git ls-files -- data localsetting dashboard/localsetting
```

`status` 若有源码修改，先保留并逐项处理，不继续切分支。`ls-files` 若列出真实数据/配置，说明它们已被跟踪，先核对；不能仅凭 .gitignore 就认定安全。公司本机的未跟踪且已忽略数据一般留在原目录，不按分支存一份；切分支主要更换受 Git 跟踪的源码。代码指向不同路径也会造成“数据不见了”的错觉。

不要运行 `reset --hard`、`clean -fdx`、强制 checkout/switch，也不要用新目录覆盖旧项目。不需要重新迁移或下载整份仓库。

## 2. 只在误切分支时恢复一次，然后更新

检查无待处理修改后执行。每步失败即停止，避免 switch 失败后把另一分支拉进当前分支。

```powershell
git fetch origin
if ($LASTEXITCODE -ne 0) { throw 'fetch 失败，停止' }
git switch codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '切分支失败，停止；保留当前文件并检查报错' }
git pull --ff-only origin codex/company-apps
if ($LASTEXITCODE -ne 0) { throw '不能快进，停止；不要 reset 或强推' }
git branch --show-current
git log -1 --oneline
```

只有远端同名分支、本地尚无时，`git switch` 通常会创建跟踪分支；若报错，只按报错核对，不执行覆盖命令。以后一直留在公司分支，日常关闭 App 后 `git pull --ff-only` 即可，无需再切看板发布分支。旧分支保留作历史，不作为后续更新入口。

## 3. 检查 Excel 和已有 Python

需要已安装、能正常打开的 Windows 桌面 Microsoft Excel；只装 WPS 不满足 Excel COM 接口。无需开启宏，不需要安装 Wind Excel 插件来运行本数字版。

在现有项目 Python 环境已激活的终端里检查：

```powershell
python -c "import sys,pandas,numpy,pyarrow,requests,openpyxl; print(sys.executable)"
```

若通过，复用该环境，并将输出的真实 Python 路径设为当前终端启动器所用路径。例如使用以下命令自动取得，不修改系统设置：

```powershell
$numericPython = python -c "import sys; print(sys.executable)"
if ($LASTEXITCODE -ne 0) { throw '请先激活原项目 Python 环境' }
$env:SWHY_DELTA1_PYTHON = $numericPython
```

若缺依赖，不要直接升级原 Wind 环境。可使用已有 Python 3.11 或更高版本在忽略目录下创建独立环境：

```powershell
python -m venv .venvs\numeric_excel
if ($LASTEXITCODE -ne 0) { throw '环境创建失败' }
& .\.venvs\numeric_excel\Scripts\python.exe -m pip install -r dashboard\requirements-numeric.txt
if ($LASTEXITCODE -ne 0) { throw '依赖安装失败；检查网络或公司离线安装源' }
$env:SWHY_DELTA1_PYTHON = (Resolve-Path .\.venvs\numeric_excel\Scripts\python.exe).Path
```

只选上面一种环境方式。`$env:` 只对当前终端及其启动的程序有效；以后从同一已激活环境启动，或重新设置该变量。数字版不调用 WindPy，不需要为它重新配置 Wind 登录或覆盖原 `.env`、`localsetting/data.local.json`。

## 4. 离线检查配置与历史

```powershell
& $env:SWHY_DELTA1_PYTHON -B -X utf8 -m dashboard.numeric_config
```

默认首次把 `dashboard/localsetting/native.json` 和已有公式复制到 `dashboard/localsetting/numeric_excel/`，已有副本不覆盖；没有原配置则创建仅供数字版编辑的初始文件。已安装的标准化数据包只在该副本里激活路径。原看板配置和根目录共享数据配置不修改。不传 `-LocalRoot` 即采用这个默认副本；显式 `-LocalRoot` 是高级覆盖，所指定目录会用于写配置。

检查必须通过后再启动。未通过时只编辑 `dashboard/localsetting/numeric_excel/native.json` 中的下列路径，保留其他字段：

| 字段 | 填写内容 |
| --- | --- |
| `history_roots` | 标准化历史目录列表，每个目录含 `dataset.json`、`current.json` 和对应 Parquet；不能填 Wind SQLite 或随便一个 data 目录 |
| `reference_file` | 有效合约、挂牌/到期日等参考 JSON |
| `dividend_root` | 公司原有符合看板格式的分红 Excel 所在目录，或已有独立包中的分红目录；缺失则相关指标留空 |
| `realtime_root` | 本地实时行情缓存根目录；新装默认用共享 data 下 `market/index_futures/dashboard/realtime` |

如果公司只有原始 Wind 库，还没有看板标准化历史，**当前版本不会直接转换或读取那个 Wind 库**。需另行生成兼容历史，或使用此前已验收的独立看板数据包；不要移动、覆盖或清空原 Wind 库。已有标准化历史和配置则无需重新导入。

仅当确实缺少标准化历史、且手头已有经核验的 `dashboard-data-short-v2-20261019.zip` 时，可显式安装：把下例包路径换成现有文件，数据根目录从既有共享配置解析，不写死另一台机器路径。

```powershell
$numericDataRoot = & $env:SWHY_DELTA1_PYTHON -c "from dashboard.marketdata.paths import DATA_ROOT; print(DATA_ROOT)"
if ($LASTEXITCODE -ne 0) { throw '数据路径读取失败' }
& $env:SWHY_DELTA1_PYTHON -B -X utf8 -m dashboard.data_package install '已有数据包的完整路径\dashboard-data-short-v2-20261019.zip' --data-root $numericDataRoot
if ($LASTEXITCODE -ne 0) { throw '导入失败；不要覆盖处理冲突文件' }
& $env:SWHY_DELTA1_PYTHON -B -X utf8 -m dashboard.numeric_config
```

安装器仅向 data 下 dashboard 专属 imports 目录增量添加并校验，重复安装复用，冲突拒绝，不写其他模块行情库；会更新 dashboard 专属 active_package.json。该私有数据包不在 Git 中。没有包也没有兼容数据时，保留现场反馈检查结果，不能把仅拉到代码视为数据已就绪。

## 5. 先读本地数据，再开实时更新

```powershell
.\dashboard\start_numeric_excel.cmd -ReadOnlyCache
```

此模式不创建实时采集器，但会写数字版计算缓存和新的 Excel 文件。核对四张表的具体合约、时间、指标和缺失原因；首次历史计算可能较慢。关闭本次 Excel 后，盘中登录公司实时行情 VPN，再启动：

若旧版只停在“正在读取”，先 pull 最新启动修复并重开，无须重装环境或重新导入数据。新版先打开 Excel，显示00至03档进度；完整首次计算仍需时间。阶段耗时和错误看终端显示的本次日志目录，不要读取之前运行号的旧日志。

```powershell
.\dashboard\start_numeric_excel.cmd
```

实时行情来自公司 HTTP 接口，不来自 WindPy。DDB 历史 VPN 与公司实时 VPN 按已有客户端手动切换，程序不代切。北京时间交易日 09:29（含）至 15:01（不含）允许接入实时；之外不新建实时行情请求，比较最新有效历史与保存观测显示较新数据并标时点。保存观测不保证是最终收盘价。

Excel 保持由启动器打开，同一个工作簿会自动更新；直接双击以前保存的 xlsx 只看最后保存结果。默认新成品在仓库 `data/cache/dashboard/numeric/`，每日计算 JSON 在共享 data 同名子路径，实际共享根以检查输出为准。已有输出文件拒绝覆盖。原 Wind 库不迁移；若采集使用既有 HTTP 实时库，首次写入升级结构前会备份，原历史行及已发布分片保留。

## 6. 公司日常只需拉取；修改代码才需要提交

一般使用 App 不需要 `add/commit/push`。若你在公司也改了代码，按确切文件名 `git add`，再核对 `git diff --cached --name-status` 与 `git diff --cached`，确认没有公司数据、配置、凭据或真实 Excel 才提交。只允许无业务数据的 `dashboard/excel_numeric/template.xlsx` 模板例外。

**pull/push 同步提交，不是勾选几个文件同步。** “注意 git 的内容”应落实在暂存、提交前；不能靠 push 时选择文件过滤已经提交的数据。不要全量 `git add .` 或 `git add -A`。如果意外暂存敏感文件，先从暂存区移除，不能先推送再删除。
