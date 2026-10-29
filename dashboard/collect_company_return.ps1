param(
    [Parameter(Mandatory=$true)][string]$ReportDirectory,
    [Parameter(Mandatory=$true)][string]$LocalRoot,
    [ValidateSet('runtime','full')][string]$RunMode='runtime'
)
$ErrorActionPreference='Stop'
$reportRoot=(Get-Item -LiteralPath $ReportDirectory -ErrorAction Stop).FullName
$repository=Split-Path $PSScriptRoot -Parent
function Read-DeltaJson {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    if ((Get-Item -LiteralPath $Path).Length -gt 64MB) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 -ErrorAction Stop | ConvertFrom-Json -ErrorAction Stop) }
    catch { return $null }
}
function Same-DeltaPath {
    param([string]$Left,[string]$Right)
    if (-not $Left -or -not $Right) { return $false }
    try { return [IO.Path]::GetFullPath($Left).TrimEnd('\','/') -ieq [IO.Path]::GetFullPath($Right).TrimEnd('\','/') }
    catch { return $false }
}
$git=Read-DeltaJson (Join-Path $reportRoot 'git.json')
if (-not $git -or -not $git.StartedAt -or $git.Commit -notmatch '^[a-fA-F0-9]{40}$') { throw '缺有效git.json及本轮StartedAt/Commit；保留原目录。' }
$started=[DateTimeOffset]::Parse($git.StartedAt)
$finished=[DateTimeOffset]::Now
if ($started -gt $finished) { throw '本轮StartedAt晚于当前时间。' }
$safe=$reportRoot+'_safe_'+$finished.ToString('HHmmss_fff')+'_'+[Guid]::NewGuid().ToString('N').Substring(0,8)
New-Item -ItemType Directory -Path $safe -ErrorAction Stop | Out-Null
$missing=@();$stages=@();$openRuns=@();$closedRuns=@();$includedReports=@()
function Copy-DeltaJson {
    param([string]$Source,[string]$Target)
    if ($null -eq (Read-DeltaJson $Source)) { return $false }
    Copy-Item -LiteralPath $Source -Destination $Target -ErrorAction Stop
    if ($null -eq (Read-DeltaJson $Target)) { throw '复制后的JSON无效，停止打包并保留目录。' }
    return $true
}
$required=@('git.json','drive_y.json')
if ($RunMode -eq 'full') { $required+=@('dividend_before.json','dividend_share.json','dividend_import.json','dividend_after.json','etf_local.json','etf_capabilities.json') }
foreach ($name in @('git.json','drive_y.json','dividend_before.json','dividend_share.json','dividend_import.json','dividend_after.json','dividend_downloaded.json','etf_local.json','etf_capabilities.json')) {
    $source=Join-Path $reportRoot $name
    if ((Test-Path -LiteralPath $source) -or $name -in $required) {
        if (-not (Copy-DeltaJson $source (Join-Path $safe $name))) { $missing+=$name }
    }
}
# New diagnoses go directly into this run. Recover legacy runtime reports by
# their recorded diagnosis.at, never by Windows directory CreationTime.
$candidates=@(Get-ChildItem -LiteralPath $reportRoot -Directory -Filter 'diagnosis-*')
$legacy=Join-Path $PSScriptRoot 'runtime/app_startup'
foreach ($dir in @(Get-ChildItem -LiteralPath $legacy -Directory -Filter 'diagnosis-*' -ErrorAction SilentlyContinue)) {
    $meta=Read-DeltaJson (Join-Path $dir.FullName 'diagnosis.json')
    try {
        $at=[DateTimeOffset]::Parse($meta.at)
        if ($at -ge $started -and $at -le $finished) { $candidates+=$dir }
    } catch { }
}
$number=0
foreach ($dir in @($candidates | Sort-Object FullName -Unique)) {
    $number++
    $name=$dir.Name+'-'+$number
    $target=Join-Path $safe $name
    New-Item -ItemType Directory -Path $target -ErrorAction Stop | Out-Null
    foreach ($file in @('diagnosis.json','preflight.json','overview.json','wind.json')) {
        $source=Join-Path $dir.FullName $file
        if ((Test-Path -LiteralPath $source) -or $file -in @('diagnosis.json','preflight.json')) {
            if (-not (Copy-DeltaJson $source (Join-Path $target $file))) { $missing+=($name+'/'+$file+' absent or invalid') }
        }
    }
    $meta=Read-DeltaJson (Join-Path $target 'diagnosis.json')
    $current=$false
    try { $at=[DateTimeOffset]::Parse($meta.at);$current=$meta.commit -eq $git.Commit -and $at -ge $started -and $at -le $finished } catch { }
    if (-not $current) { $missing+=($name+' diagnosis time/commit mismatch');continue }
    $overview=Read-DeltaJson (Join-Path $target 'overview.json')
    $profileMatches=Same-DeltaPath $meta.local_root $LocalRoot
    if ($overview -and (Same-DeltaPath $overview.diagnostic_profile.local_root $LocalRoot)) {
        $stages+='Overview'
        $app=@($overview.app_reports.matching_profile)[0]
        try {
            $observed=[DateTimeOffset]::Parse($app.observed_at)
            if ($app.report_path -and $observed -ge $started -and $observed -le $finished) {
                if ($app.collection_worker_running -and -not $app.closing) { $openRuns+=$app.report_path }
                if ($app.shutdown.complete -and $app.phase -eq 'closed') { $closedRuns+=$app.report_path }
            }
        } catch { }
    } elseif ($overview) { $missing+=($name+' Overview profile mismatch') }
    if ($profileMatches -and $meta.wind_stage -and (Read-DeltaJson (Join-Path $target 'wind.json'))) { $stages+=$meta.wind_stage }
    $includedReports+=($name)
}
$requiredStages=if ($RunMode -eq 'full') { @('Connect','Indices','ETFs','Nav','Overview') } else { @('Overview') }
foreach ($stage in $requiredStages) { if ($stage -notin $stages) { $missing+=($stage+' report absent') } }
if (-not @($openRuns | Where-Object { $_ -in $closedRuns }).Count) { $missing+='same-run open and completed shutdown reports absent' }
$files=@(Get-ChildItem -LiteralPath $safe -Recurse -File)
if (@($files | Where-Object { $_.Extension -ne '.json' }).Count) { throw '安全目录出现非JSON文件，停止打包。' }
[pscustomobject]@{ Schema='company-safe-return-v2';RunMode=$RunMode;StartedAt=$started.ToString('o');CreatedAt=$finished.ToString('o');Commit=$git.Commit;
    Complete=($missing.Count -eq 0);MissingReports=@($missing);DiagnosisReports=@($includedReports);
    IncludedFiles=@($files | ForEach-Object { $_.FullName.Substring($safe.Length+1) }) } |
    ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $safe 'return_manifest.json') -Encoding UTF8
$zip=$safe+'.zip'
Compress-Archive -LiteralPath $safe -DestinationPath $zip -ErrorAction Stop
Add-Type -AssemblyName System.IO.Compression.FileSystem
$archive=[IO.Compression.ZipFile]::OpenRead($zip)
try {
    foreach ($entry in $archive.Entries) {
        if ($entry.Name -and -not $entry.Name.EndsWith('.json',[StringComparison]::OrdinalIgnoreCase)) { throw 'ZIP出现非JSON文件。' }
    }
} finally { $archive.Dispose() }
if ($missing.Count) { Write-Warning ('报告尚有缺项：'+($missing -join ', ')) }
Write-Host ('请回传：'+$zip)
