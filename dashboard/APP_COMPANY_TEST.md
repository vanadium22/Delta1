# 公司本轮完整复测命令（2026-10-29）

本轮接续69789a4的Y盘、导入及审计修复；公司真实取数尚未验收。本页是完整命令入口。公司Git根为 `D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard`，LocalRoot为其下 `dashboard/localsetting/app`。先正常关闭旧看板并等后台退出，保留Wind终端登录；用平时能打开Y:的同一Windows用户，在同一个PowerShell窗口按顺序执行。

确认公盘为 `Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026`。Y:映射192.168.91.230，完整UNC共享名未知，不猜拼IP地址、不重新映射。2026是年份目录，匹配 `指数基差情况_*.xlsx`，业务日以Sheet1!B1为准。

## 1. 更新与本轮输出

```powershell
Set-Location -LiteralPath 'D:/WORKSPACE/MAIN/SwhySc/DeltaOne/project/dashboard'
git status --short --branch
if ((git branch --show-current).Trim() -ne 'codex/company-apps') { throw '当前不是codex/company-apps；保留现场，先核对分支。' }
git pull --ff-only
if ($LASTEXITCODE -ne 0) { throw 'Git更新未完成；保留现场并回传终端提示。' }
git log -1 --oneline

$deltaLocalRoot = Join-Path (Get-Location) 'dashboard/localsetting/app'
if (-not (Test-Path -LiteralPath (Join-Path $deltaLocalRoot 'native.json'))) { throw '公司LocalRoot/native.json不存在，先核对实际配置位置。' }
$deltaSource = 'Y:\jrcx\for_jrcx\OTC-Quant\pybct\TZQ\日终基差结果\2026'
$deltaTestStarted = Get-Date
$deltaReport = Join-Path (Get-Location) ('dashboard/runtime/company_retest/' + $deltaTestStarted.ToString('yyyyMMdd_HHmmss_fff'))
New-Item -ItemType Directory -Path $deltaReport -ErrorAction Stop | Out-Null
[pscustomobject]@{ Branch=(git branch --show-current).Trim(); Commit=(git rev-parse HEAD).Trim(); Status=@(git status --short --branch); StartedAt=$deltaTestStarted.ToString('o') } |
    ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $deltaReport 'git.json') -Encoding UTF8
$deltaYDrive = Get-PSDrive -Name Y -ErrorAction SilentlyContinue
[pscustomobject]@{ Mapped=[bool]$deltaYDrive; Name=$deltaYDrive.Name; Root=$deltaYDrive.Root; DisplayRoot=$deltaYDrive.DisplayRoot; ExpectedServer='192.168.91.230' } |
    ConvertTo-Json | Set-Content -LiteralPath (Join-Path $deltaReport 'drive_y.json') -Encoding UTF8
Write-Host ('本轮输出目录：' + $deltaReport)
```

`drive_y.json`仅记录映射元数据。DisplayRoot为空时可额外执行 `net use Y:` 查看Remote名称；此命令不重新映射。Git有冲突/错误时保留现场，不reset/clean。不要将native.json或命令的原始异常日志放进回传目录。

## 2. 分红导入与实际来源

```powershell
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'dividend_before.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Share -SourceDirectory $deltaSource -Output (Join-Path $deltaReport 'dividend_share.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Import -SourceDirectory $deltaSource -Output (Join-Path $deltaReport 'dividend_import.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'dividend_after.json') -NoPause

$deltaDividend = Get-Content -LiteralPath (Join-Path $deltaReport 'dividend_after.json') -Raw -Encoding UTF8 | ConvertFrom-Json
$deltaDividend.diagnostic_profile | Format-List
$deltaDividend.audit | Select-Object record_count,file_versions,oldest_business_day,latest_business_day,history_dividends_complete | Format-List
$deltaDividend.audit.sources | Select-Object configured_share_directory,share_directory,store_directory,configured_file | Format-List
$deltaDividend.audit.current_dividends.'IF00.CFE' | Format-List contract_id,points,source_business_date,effective_from,file_sha256,inherited_from,reason
```

Local离线；Share有界只读检查Y盘并临时验证，不发布；Import追加到新库。`SourceDirectory`仅覆盖这次Share/Import读取，不保存配置。`diagnostic_profile`标识实际native文件位置/SHA；`sources.configured_share_directory`是原配置值，`share_directory`是有效源，二者可不同。

退出2/ok=false可能仅是历史D不完整，继续后续诊断并回传。分开看 `sync.status/inserted/business_dates`、`matched_names/source_directories`、`audit.latest_business_day/history_dividends_complete` 和16项 `current_dividends`，不能把历史未齐解释为本次文件未读取。`matched_names`是年份目录文件名样本，实际日期看B1解析结果；窗口外业务日见 `outside_range_files`，文件名旧或超出窗口不决定业务日。

新D不回写过去。当前Local是当前业务时点D；非交易界面可能用昨日价格参考，须同时看Overview的pricing_day和D来源。公盘缺旧日时如实缺项，不拿今日单表或DDB重下价格掩盖。

可选：若另有已下载的本地Excel，在打开看板前执行，**仅修改第一行路径**：

```powershell
$deltaDownloadedFile = 'T:\inani\下载\AI\分红\指数基差情况_2026-10-27.xlsx'
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Import -InputFile $deltaDownloadedFile -Output (Join-Path $deltaReport 'dividend_downloaded.json') -NoPause
./dashboard/diagnose_dividends.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'dividend_after.json') -NoPause
```

`InputFile`只允许Import，与SourceDirectory互斥；跳过公盘同步，追加到相同新库，原件/配置不改。`file_import.status=imported/unchanged`、business_dates和SHA证明指定文件已读取或同内容已存在。下载目录不会自动扫描。默认自动主源为Y盘；已有其他自定义目录保留，若要持续改源，需在设置中核对并手动保存，SourceDirectory不会替你持久化。

## 3. 行业与ETF只读阶段

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Connect -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Indices -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage ETFs -NoPause
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage Local -Output (Join-Path $deltaReport 'etf_local.json') -NoPause
./dashboard/diagnose_data_capabilities.cmd -LocalRoot $deltaLocalRoot -Stage ETF -Output (Join-Path $deltaReport 'etf_capabilities.json') -NoPause
```

这些均只读，不发布正式资料、不订阅、不改VPN。需要固定同一已完成交易日时，只对显式Wind阶段加 `-WindDay '2026-10-28'`，日期必须是实际已完成交易日；默认日期规则不改。

ETF能力测试总预算90秒，close_nav查看同日有效配对数；IOPV/净申赎/PCF返回mapping_required表示缺已核验字段/单位/带日定义，不等于本次接口失败或已取得数据。可选字段文件的真实参数与契约见 [DATA_CAPABILITIES](docs/DATA_CAPABILITIES.md)，不猜字段，不提交本地字段文件。本机缺WindPy不能推断公司缺WindPy。

## 4. 正常页面运行与开窗取样

```powershell
& "$env:WINDIR\System32\wscript.exe" '.\dashboard\start_presentation.vbs' --theme public --local-root $deltaLocalRoot
```

保持看板打开10–15分钟，实时VPN仍手动。**正常任务才会发布行业/ETF资料**；需要立即复核时，在“数据更新/设置”点一次“DDB一键补齐”：先复核Wind资料，再按实际缺口补概览日线，本地标准历史优先复用，等待结束，勿反复点击。缺项资料有每日有界修复，成分行情约60秒一轮。

检查20卡/16期货20与60分位、逐卡较昨日变化、行业覆盖/缺项、ETF同日收盘溢价、午休/盘前盘后参考及切页/滚动；可选验证行情分析查询、取消和CSV。研究32项/A02继续暂停。然后**保持窗口开着**，回到同一PowerShell执行：

```powershell
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -WindStage Nav -NoPause
./dashboard/diagnose_presentation.cmd -LocalRoot $deltaLocalRoot -Overview -NoPause
```

默认Overview离线，不启动采集或任何接口。Nav需要正常任务已发布ETF排名；尚未发布时失败也回传，不能用只读ETFs成功冒充生产发布。历史closing/stopped记录不能单独证明采样时当前窗口状态。

## 5. 仅收白名单JSON并打包

以下脚本只复制列出的JSON到新建安全目录，验证JSON后压缩并核验ZIP扩展名。native.json、原始异常日志、SQLite、Excel及整个业务目录不会被复制；不要直接压缩LocalRoot或整个runtime。

```powershell
$deltaSafe = $deltaReport + '_safe_' + (Get-Date).ToString('HHmmss_fff')
New-Item -ItemType Directory -Path $deltaSafe -ErrorAction Stop | Out-Null
$deltaMissing = @()
function Copy-DeltaSafeJson {
    param([string]$Source, [string]$Target)
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { return $false }
    try {
        $null = Get-Content -LiteralPath $Source -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop
        Copy-Item -LiteralPath $Source -Destination $Target -ErrorAction Stop
        return $true
    } catch { return $false }
}
foreach ($deltaName in @('git.json','drive_y.json','dividend_before.json','dividend_share.json','dividend_import.json','dividend_after.json','etf_local.json','etf_capabilities.json')) {
    if (-not (Copy-DeltaSafeJson (Join-Path $deltaReport $deltaName) (Join-Path $deltaSafe $deltaName))) { $deltaMissing += $deltaName }
}
$deltaOptional = Join-Path $deltaReport 'dividend_downloaded.json'
if (Test-Path -LiteralPath $deltaOptional) {
    if (-not (Copy-DeltaSafeJson $deltaOptional (Join-Path $deltaSafe 'dividend_downloaded.json'))) { $deltaMissing += 'dividend_downloaded.json (invalid)' }
}
$deltaSeenStages = @()
$deltaDiagnosisRoot = Join-Path (Get-Location) 'dashboard/runtime/app_startup'
$deltaDiagnosisDirs = @(Get-ChildItem -LiteralPath $deltaDiagnosisRoot -Directory -Filter 'diagnosis-*' -ErrorAction SilentlyContinue |
    Where-Object { $_.CreationTime -ge $deltaTestStarted })
foreach ($deltaDir in $deltaDiagnosisDirs) {
    $deltaTarget = Join-Path $deltaSafe $deltaDir.Name
    New-Item -ItemType Directory -Path $deltaTarget -ErrorAction Stop | Out-Null
    foreach ($deltaName in @('diagnosis.json','wind.json','overview.json','preflight.json')) {
        $deltaFile = Join-Path $deltaDir.FullName $deltaName
        if (Test-Path -LiteralPath $deltaFile) {
            if (-not (Copy-DeltaSafeJson $deltaFile (Join-Path $deltaTarget $deltaName))) { $deltaMissing += ($deltaDir.Name + '/' + $deltaName + ' (invalid)') }
        } elseif ($deltaName -in @('diagnosis.json','preflight.json')) { $deltaMissing += ($deltaDir.Name + '/' + $deltaName) }
    }
    $deltaMetaFile = Join-Path $deltaTarget 'diagnosis.json'
    if (Test-Path -LiteralPath $deltaMetaFile) {
        $deltaMeta = Get-Content -LiteralPath $deltaMetaFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($deltaMeta.wind_stage -and (Test-Path -LiteralPath (Join-Path $deltaTarget 'wind.json'))) { $deltaSeenStages += $deltaMeta.wind_stage }
    }
    if (Test-Path -LiteralPath (Join-Path $deltaTarget 'overview.json')) { $deltaSeenStages += 'Overview' }
}
foreach ($deltaStage in @('Connect','Indices','ETFs','Nav','Overview')) {
    if ($deltaStage -notin $deltaSeenStages) { $deltaMissing += ($deltaStage + ' report absent') }
}
$deltaFiles = @(Get-ChildItem -LiteralPath $deltaSafe -Recurse -File)
if (@($deltaFiles | Where-Object { $_.Extension -ne '.json' }).Count) { throw '安全目录出现非JSON文件，停止打包。' }
[pscustomobject]@{ Schema='company-safe-return-v1'; CreatedAt=(Get-Date).ToString('o'); MissingReports=@($deltaMissing); IncludedFiles=@($deltaFiles | ForEach-Object { $_.FullName.Substring($deltaSafe.Length + 1) }) } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $deltaSafe 'return_manifest.json') -Encoding UTF8
$deltaZip = $deltaSafe + '.zip'
Compress-Archive -LiteralPath $deltaSafe -DestinationPath $deltaZip -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem
$deltaArchive = [System.IO.Compression.ZipFile]::OpenRead($deltaZip)
try {
    foreach ($deltaEntry in $deltaArchive.Entries) {
        if ($deltaEntry.Name -and -not $deltaEntry.Name.EndsWith('.json',[StringComparison]::OrdinalIgnoreCase)) { throw 'ZIP出现非JSON文件。' }
    }
} finally { $deltaArchive.Dispose() }
Write-Host ('缺少或无效报告：' + ($deltaMissing -join ', '))
Write-Host ('请回传：' + $deltaZip)
```

回传最后打印的ZIP，含git/映射元数据、分红before/share/import/after（可选downloaded）、ETF Local/能力报告、五个阶段的diagnosis/preflight及对应wind/overview JSON，以及缺失文件清单return_manifest.json。缺阶段也保留并回传，不补造成功结果。

另用一句话注明测试时间、Overview取样时窗口是否开着、行业/ETF是否出现、正常关闭约几秒；页面异常可另附截图。正常关闭后等写入者排空，不强杀、不删锁。不要发送native.json、凭据、原始异常日志、SQLite或Excel。

## 自动复制与验收判断

默认自动缓存为 `<LocalRoot>/overview_dividends`，实际位置看audit.sources.store_directory；raw按业务日/SHA归档，records.sqlite保存版本，derived.sqlite保存计算缓存。09:00/15:30上海检查，成功时段不重复，失败有限退避；首次按20/60历史加缓冲窗口筛选B1，后续增量并保留旧记录。文件晚于成功检查产生时手动更新，或按实际产出时间调整设置，不持续轮询下载目录。

本轮本地55项受影响测试通过，包含真实Windows CMD中文空格路径与B1错名文件测试；不代表公司Y盘、真实历史D/行业/ETF或持续运行已经验收。历史229/62/272项属于此前批次，当前验收只依据本轮公司同次HEAD、来源、正式发布与开窗报告。
