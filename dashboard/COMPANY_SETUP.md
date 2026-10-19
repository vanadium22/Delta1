# 公司已有项目：数字 Excel 按顺序启用

长期分支为 `codex/company-apps`。公司现有 `D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard` 本身是仓库根目录；下面的 `dashboard\start_numeric_excel.cmd` 是新增模块入口，两个 dashboard 是正常的层级。路径若已改变，以 `git rev-parse --show-toplevel` 为准。

短文件名修复及新数据包安装按 [SHORT_FILENAMES.md](SHORT_FILENAMES.md)。不能只替换 ZIP 或覆盖整个 data；新包需用安装器激活，旧 Wind 和配置保留。

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

仅当确实缺少标准化历史、且手头已有经核验的 `dashboard-data-20261019.zip` 时，可显式安装：把下例包路径换成现有文件，数据根目录从既有共享配置解析，不写死另一台机器路径。

```powershell
$numericDataRoot = & $env:SWHY_DELTA1_PYTHON -c "from dashboard.marketdata.paths import DATA_ROOT; print(DATA_ROOT)"
if ($LASTEXITCODE -ne 0) { throw '数据路径读取失败' }
& $env:SWHY_DELTA1_PYTHON -B -X utf8 -m dashboard.data_package install '已有数据包的完整路径\dashboard-data-20261019.zip' --data-root $numericDataRoot
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
