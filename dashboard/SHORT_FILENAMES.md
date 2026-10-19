# 短文件名更新与公司安装

2026-10-19。所有代码仍在 `codex/company-apps`，新看板前端、实际行情和本机配置不发布。

历史与实时 Parquet 采用 `2026-10-19.parquet`、`2026-10-19.2.parquet` 等名称；同日追加/修订独立发布，不覆盖已有文件。策略重复导出仍产生独立文件。原始 HTTP 响应使用轮次/批次名称，完整校验值在元数据中保留。版本清单的内部版本 ID 保持兼容格式，不缩短这些版本 ID。

打包器默认重写所有分片相对路径与清单，使用短包目录及 `s1`、`s2` 等数据集目录，即使源数据仍有旧长文件名也会导出短名称。价格、时点、修订号、样本和数据文件 SHA256 不变。包的身份每次独立；安装器只新增 dashboard 导入目录、备份并切换 active_package.json。已存在但内容不同的文件拒绝覆盖。

**替换 ZIP 文件本身不会更新正在读取的数据。不要把 ZIP 解压后覆盖整个 data。** 下载新包后需要执行下面的安装命令。原包、旧长文件、原 Wind 数据可以保留；无须手工删除目录。

## 公司按顺序操作

1. 关闭数字 Excel 和本项目采集/更新程序。打开已激活 `swhy_delta1` 的 PowerShell，在公司仓库根目录执行。已有源码修改先保留处理，不要 reset/clean。

```powershell
Set-Location -LiteralPath 'D:\WORKSPACE\MAIN\SwhySc\DeltaOne\project\dashboard'
git status --short
git branch --show-current
```

2. 应在 `codex/company-apps`。将单独交付的新包 `dashboard-data-short-v2-20261019.zip` 放到仓库的 `data\incoming`。整块执行以下命令；失败会停止这一块，保留原数据。

```powershell
& {
    $ErrorActionPreference = 'Stop'
    $branch = git branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch -ne 'codex/company-apps') { throw '当前不是公司统一分支，停止' }
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw '拉取失败，停止；不要覆盖本机修改' }
    $numericPython = python -c "import sys,pyarrow; print(sys.executable)"
    if ($LASTEXITCODE -ne 0) { throw 'Python 环境检查失败，停止' }
    $env:SWHY_DELTA1_PYTHON = $numericPython.Trim()
    $numericDataRoot = python -c "from dashboard.marketdata.paths import DATA_ROOT; print(DATA_ROOT)"
    if ($LASTEXITCODE -ne 0) { throw '数据根目录检查失败，停止' }
    python -m dashboard.data_package install '.\data\incoming\dashboard-data-short-v2-20261019.zip' --data-root $numericDataRoot
    if ($LASTEXITCODE -ne 0) { throw '数据导入失败，停止' }
    python -m dashboard.numeric_config
    if ($LASTEXITCODE -ne 0) { throw '数字配置检查失败，停止' }
    python -m dashboard.short_paths --local-root '.\dashboard\localsetting\numeric_excel'
    if ($LASTEXITCODE -ne 0) { throw '已有缓存短文件名迁移失败，停止并保留日志' }
    .\dashboard\start_numeric_excel.cmd -ReadOnlyCache
}
```

`DATA_ROOT` 遵循公司既有环境变量/本机设置，不强制设为开发机路径。`numeric_config` 使用数字专用配置副本；新包激活时仅更新副本中的历史读取路径，备份原副本，保留原 `localsetting/native.json`、连接设置、有效分红目录与实时缓存目录。共享数据设置不修改。

`short_paths` 不改任何配置，只迁移明确登记的标准化历史/实时索引。历史版本清单与旧分片保留，发布指针一次切换；实时库先备份，再事务更新分片/原始响应索引。备份位置见命令输出 `backup`。实时库要求既有 v4 结构，不代替旧库升级或 Wind 转换。遇到缺文件/校验不符立即停止，不能用重命名掩盖丢失数据。

3. 四张表检查正常后，下次在同一环境用 `dashboard\start_numeric_excel.cmd` 启动。09:29 前、15:01 起和休市仍读取历史/缓存，不新增实时接入。代码更新后新采集、新历史提交、新打包均使用短名称；这不表示自动增加了历史数据源或补齐任务。

迁移后的目录仍能看到旧长文件，那些是保留给旧版本和回滚的文件。当前索引指向短文件；不要按文件名自行删除旧文件。

## 开发机与后续维护

在统一分支运行 `python -m dashboard.data_package export --local-root <配置目录> --output <新包路径>` 即为短名称包，无需再次手工改 ZIP。真实数据包只在私有渠道交付，不进入 Git。

显式迁移本机旧数据：`python -m dashboard.short_paths --local-root <配置目录>`。也可使用重复的 `--history-root` 与单个 `--realtime-root`；只能指向已登记的看板数据，不能填原 Wind 库。

公司安装验证是本机离线复现，不能当成公司 VPN/Wind 实连验收。精确发布与数据验证记录保存在开发机被忽略的 `.deps/numeric_integration/short_release/`。
