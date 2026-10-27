param([string]$LocalRoot,[switch]$NoPause,[switch]$Routes,[switch]$Connect,[switch]$Overview,
    [ValidateSet('Connect','Indices','ETFs')][string]$WindStage,
    [ValidatePattern('^\d{4}-\d{2}-\d{2}$')][string]$WindDay)
$ErrorActionPreference='Stop'
$repository=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repository
$runtime=Join-Path $PSScriptRoot ('runtime/app_startup/diagnosis-'+[DateTime]::Now.ToString('yyyyMMdd-HHmmss')+'-'+$PID)
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
$report=@{schema='presentation-startup-diagnosis-v1';at=[DateTimeOffset]::Now.ToString('o');
    repository=$repository;network_requested=$false;wind_requested=$false;vpn_changed=$false;app_started=$false;files=@{};
    branch=$null;commit=$null;python=$null;latest_launch=$null;preflight_exit_code=$null}
try {
    if ($WindDay -and -not $WindStage) { throw 'WindDayRequiresExplicitWindStage' }
    $report.script_host=@{wscript_exists=(Test-Path -LiteralPath (Join-Path $env:WINDIR 'System32/wscript.exe'));policies=@{}}
    foreach ($key in @('HKCU:/Software/Microsoft/Windows Script Host/Settings','HKLM:/Software/Microsoft/Windows Script Host/Settings')) {
        $policy=Get-ItemProperty -LiteralPath $key -Name Enabled -ErrorAction SilentlyContinue
        if ($policy) { $report.script_host.policies[$key]=$policy.Enabled }
    }
    foreach ($name in @('start_presentation.vbs','start_app.ps1','app_python.ps1','app_check.py','native/editions_current.py','native/market_overview.py')) {
        $path=Join-Path $PSScriptRoot $name
        $report.files[$name]=@{exists=(Test-Path -LiteralPath $path -PathType Leaf)}
    }
    if (Get-Command git -ErrorAction SilentlyContinue) {
        $report.branch=(& git branch --show-current 2>$null | Out-String).Trim()
        $report.commit=(& git rev-parse HEAD 2>$null | Out-String).Trim()
    }
    $launch=Get-ChildItem -LiteralPath (Join-Path $PSScriptRoot 'runtime/app_startup') -Filter launcher.json -Recurse -File |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($launch) {
        $value=Get-Content -LiteralPath $launch.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
        $report.latest_launch=@{report=$launch.FullName;phase=$value.phase;python=$value.python;
            exit_code=$value.exit_code;updated_at=$value.updated_at;error_type=$value.error_type;error_id=$value.error_id}
    }
    . (Join-Path $PSScriptRoot 'app_python.ps1')
    $report.python=Get-AppPython $repository
    $checkArguments=@('-B','-s','-X','utf8','-m','dashboard.app_check','--output',(Join-Path $runtime 'preflight.json'))
    if ($LocalRoot) { $checkArguments+=@('--local-root',$LocalRoot) }
    & $report.python @checkArguments 1> (Join-Path $runtime 'preflight.log') 2> (Join-Path $runtime 'preflight.stderr.log')
    $report.preflight_exit_code=$LASTEXITCODE
    if ($Overview) {
        $profile=Get-Content -LiteralPath (Join-Path $runtime 'preflight.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $overviewRoot=$LocalRoot
        if (-not $overviewRoot -and $profile.profile) { $overviewRoot=Split-Path $profile.profile -Parent }
        if ($overviewRoot) {
            $overviewArguments=@('-B','-s','-X','utf8','-m','dashboard.overview_check','--local-root',$overviewRoot,'--output',(Join-Path $runtime 'overview.json'))
            & $report.python @overviewArguments 1> (Join-Path $runtime 'overview.log') 2> (Join-Path $runtime 'overview.stderr.log')
            $report.overview_exit_code=$LASTEXITCODE
            $report.overview_report=Join-Path $runtime 'overview.json'
        }
    }
    if ($WindStage) {
        $profile=Get-Content -LiteralPath (Join-Path $runtime 'preflight.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $windRoot=$LocalRoot
        if (-not $windRoot -and $profile.profile) { $windRoot=Split-Path $profile.profile -Parent }
        if ($windRoot) {
            $report.network_requested=$true
            $report.wind_requested=$true
            $report.wind_stage=$WindStage
            $windArguments=@('-B','-s','-X','utf8','-m','dashboard.overview_wind_check','--local-root',$windRoot,
                '--stage',$WindStage.ToLowerInvariant(),'--output',(Join-Path $runtime 'wind.json'))
            if ($WindDay) { $windArguments+=@('--day',$WindDay);$report.wind_day=$WindDay }
            & $report.python @windArguments 1> (Join-Path $runtime 'wind.log') 2> (Join-Path $runtime 'wind.stderr.log')
            $report.wind_exit_code=$LASTEXITCODE
            $report.wind_report=Join-Path $runtime 'wind.json'
        }
    }
    if ($Routes -or $Connect) {
        $profile=Get-Content -LiteralPath (Join-Path $runtime 'preflight.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        $connectionArguments=@('-B','-s','-X','utf8','-m','dashboard.connection_check','--lock-owners','--output',(Join-Path $runtime 'connection.json'))
        if ($LocalRoot) { $connectionArguments+=@('--local-root',$LocalRoot) }
        elseif ($profile.profile) { $connectionArguments+=@('--local-root',(Split-Path $profile.profile -Parent)) }
        else { $connectionArguments+='--all-profiles' }
        if ($Routes) { $connectionArguments+='--routes' }
        if ($Connect) { $connectionArguments+='--connect';$report.network_requested=$true }
        & $report.python @connectionArguments 1> (Join-Path $runtime 'connection.log') 2> (Join-Path $runtime 'connection.stderr.log')
        $report.connection_exit_code=$LASTEXITCODE
        $report.connection_report=Join-Path $runtime 'connection.json'
    }
} catch {
    $report.error_type=$_.Exception.GetType().FullName
    $report.error_id=$_.FullyQualifiedErrorId
}
$output=Join-Path $runtime 'diagnosis.json'
$report | ConvertTo-Json -Depth 10 | Set-Content -LiteralPath $output -Encoding utf8
Write-Host 'Delta1 startup / connection diagnosis (no VPN change / App launch)'
Write-Host ('Branch: '+$report.branch+'    Commit: '+$report.commit)
Write-Host ('Python: '+$report.python)
if ($report.latest_launch) { Write-Host ('Last launch: '+$report.latest_launch.phase+'    Exit: '+$report.latest_launch.exit_code) }
Write-Host ('Dependency check exit: '+$report.preflight_exit_code)
Write-Host ('Report: '+$output)
Write-Host ('Dependency details: '+(Join-Path $runtime 'preflight.json'))
if ($report.connection_report) { Write-Host ('Connection / route details: '+$report.connection_report) }
if ($report.overview_report) { Write-Host ('Overview details: '+$report.overview_report) }
if ($report.wind_report) { Write-Host ('Explicit Wind read details: '+$report.wind_report) }
if (-not $NoPause) { [void](Read-Host 'Press Enter to close') }
