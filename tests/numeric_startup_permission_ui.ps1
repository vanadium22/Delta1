param([string]$Python,[string]$Project,[string]$Folder,[string]$MissingPython)
$ErrorActionPreference='Stop'
$projectRoot=$Project
. (Join-Path $Project 'dashboard/excel_numeric/startup.ps1')
Add-Type -AssemblyName System.Windows.Forms
$local=Join-Path $Folder 'settings'
[void](New-Item -ItemType Directory -Force -Path $local)
[IO.File]::WriteAllText((Join-Path $local 'native.json'),'{"history_roots":[]}',[Text.UTF8Encoding]::new($false))
$jobs=@()
if((Resolve-NumericPython $Python) -ne [IO.Path]::GetFullPath($Python)) {throw 'Explicit interpreter changed'}
if($MissingPython) {
    $previousPath=$env:PATH
    try {
        $env:PATH=(Split-Path $MissingPython -Parent)+';'+$previousPath
        if((Resolve-NumericPython 'python') -ne [IO.Path]::GetFullPath($MissingPython)) {throw 'PATH interpreter not pinned'}
    } finally { $env:PATH=$previousPath }
    $result=Invoke-NumericJob $MissingPython 'summary' $local $Folder ''
    if($result.state -ne 'failed' -or $result.ok -or $result.exit_code -ne 1) {throw 'Missing dependency was accepted'}
    if($result.error.stage -ne 'imports' -or $result.error.module -ne 'pandas') {throw 'Import evidence lost'}
    if($result.runtime.python -ne [IO.Path]::GetFullPath($MissingPython)) {throw 'Actual child interpreter lost'}
    if($result.message -notlike '*实际Python*' -or $result.message -notlike '*pandas*') {throw 'Unclear import message'}
    if(Get-Process -Id $result.runtime.pid -ErrorAction SilentlyContinue) {throw 'Failed child still running'}
    $jobs+=@{action='real-missing-pandas';state=$result.state;runtime=$result.runtime;exit_code=$result.exit_code}
    # Run the actual launcher through its import-failure dialog; no producer/Excel/VPN.
    $previousRuns=@(Get-ChildItem -LiteralPath (Join-Path $Project 'dashboard/runtime/numeric_live') -Directory | Select-Object -ExpandProperty Name)
    $output=Join-Path $Folder 'must-not-open.xlsx'
    $exitTimer=[Windows.Forms.Timer]::new();$exitTimer.Interval=100
    $exitTimer.Add_Tick({
        foreach($form in @([Windows.Forms.Application]::OpenForms)) {
            if($form.Text -eq 'Delta1 · Python环境') {
                @($form.Controls | Where-Object Text -eq '退出')[0].PerformClick()
            }
        }
    })
    try {
        $exitTimer.Start()
        & (Join-Path $Project 'dashboard/excel_numeric/live.ps1') -Python $MissingPython -Output $output | Out-Null
    } finally {$exitTimer.Stop();$exitTimer.Dispose()}
    $newRuns=@(Get-ChildItem -LiteralPath (Join-Path $Project 'dashboard/runtime/numeric_live') -Directory | Where-Object {
        if($_.Name -in $previousRuns) {return $false}
        $candidate=Get-Content -LiteralPath (Join-Path $_.FullName 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
        return $candidate.output -eq $output
    })
    if($newRuns.Count -ne 1) {throw 'Unexpected launcher run count'}
    $run=Get-Content -LiteralPath (Join-Path $newRuns[0].FullName 'run.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    if($run.requested_python -ne $MissingPython -or $run.resolved_python -ne [IO.Path]::GetFullPath($MissingPython)) {throw 'Launcher interpreter evidence lost'}
    if($run.state -ne 'cancelled' -or $run.producer_pid -or (Test-Path -LiteralPath $output)) {throw 'Import failure started Excel/producer'}
    $jobs+=@{action='real-launcher-import-exit';state=$run.state;requested_python=$run.requested_python;resolved_python=$run.resolved_python}
}
$result=Invoke-NumericJob $Python 'summary' $local $Folder ''
if($result.exit_code -ne 0 -or $result.runtime.python -ne [IO.Path]::GetFullPath($Python)) {throw 'Healthy child runtime lost'}
$jobs+=@{action='real-summary';runtime=$result.runtime;exit_code=$result.exit_code}
foreach($action in @('summary','stale','missing')) {
    $result=Invoke-NumericJob $Python $action $local $Folder '' 'tests.numeric_startup_permission_worker'
    if($result.state -ne 'failed' -or $result.ok) {throw ('Failed worker accepted: '+$action)}
    if(-not $result.diagnostic_file -or -not (Test-Path -LiteralPath $result.diagnostic_file)) {throw 'Missing stderr path'}
    if($action -eq 'summary') {
        if($result.error.stage -ne 'summary' -or $result.gate.allowed -ne $true) {throw 'Error/clock evidence lost'}
        if($result.message -notlike '*fixture.locked.json*') {throw 'Missing denied file'}
        $log=Get-Content -LiteralPath $result.diagnostic_file -Raw -Encoding UTF8
        if($log -notlike '*DELTA1_STARTUP_ERROR*' -or $log -like '*fixture-secret-password*') {throw 'Unsafe/incomplete diagnostics'}
    } elseif($result.exit_code -ne 1) {throw ('Process exit code lost: '+$action+' '+($result | ConvertTo-Json -Compress))}
    $jobs+=@{action=$action;state=$result.state;diagnostic_file=$result.diagnostic_file}
}

# Exercise the real wizard routing; only replace dialogs and network/child jobs.
function Invoke-NumericJob($Interpreter,$Action,$ConfigRoot,$RunFolder,$HistoryStatus) {
    $script:events.Add($Action)
    if($Action -eq 'probe') {return [pscustomobject]@{ok=$true}}
    if($Action -ne 'summary') {throw 'Unexpected history/network task'}
    $script:summaries++
    if($script:case -like 'imports*' -and $script:summaries -eq 1) {
        return [pscustomobject]@{state='failed';message='pandas · actual fixture Python';error=@{stage='imports'}}
    }
    if($script:case -like 'unknown*' -and $script:summaries -le 2) {
        return [pscustomobject]@{state='failed';message='synthetic unknown clock'}
    }
    return [pscustomobject]@{state='failed';message='synthetic history read denied';local_root='fixture';gate=@{allowed=($script:case -ne 'off-hours')}}
}
function Invoke-NumericChoice($Title,$Message,$Primary,$Secondary) {
    $script:titles.Add($Title)
    if($script:titles.Count -gt 8) {throw 'Unexpected retry loop'}
    switch($Title) {
        'Delta1 · 历史数据' {return 'No'}
        'Delta1 · Python环境' {
            if($script:case -eq 'imports-exit') {return 'No'}
            return 'Yes'
        }
        'Delta1 · 时段检查未完成' {
            if($Message -notlike '*不能视为非交易时段*') {throw 'Unknown clock reported as off-hours'}
            if($script:case -eq 'unknown-readonly') {return 'No'}
            return 'Yes'
        }
        'Delta1 · 行情网络' {return 'Yes'}
        default {throw ('Unexpected dialog: '+$Title)}
    }
}
$cases=@()
foreach($script:case in @('history-error-clock-valid','unknown-retry','unknown-readonly','off-hours','imports-exit','imports-retry')) {
    $script:events=[Collections.Generic.List[string]]::new()
    $script:titles=[Collections.Generic.List[string]]::new()
    $script:summaries=0
    $result=Invoke-NumericWizard 'fixture' 'fixture' 'fixture'
    if($script:case -eq 'imports-exit') {
        if(-not $result.cancelled -or $script:events.Count -ne 1 -or $script:titles[0] -ne 'Delta1 · Python环境') {throw 'Import failure entered history/VPN/readonly flow'}
        $cases+=@{case=$script:case;events=$script:events.ToArray();titles=$script:titles.ToArray();cancelled=$true}
        continue
    }
    $readonly=$script:case -in @('unknown-readonly','off-hours')
    if($result.cancelled -or $result.read_only -ne $readonly) {throw ('Wrong launch mode: '+$script:case)}
    if(($script:events -contains 'probe') -eq $readonly) {throw 'Wrong network boundary'}
    if(($script:titles -contains 'Delta1 · 时段检查未完成') -ne ($script:case -like 'unknown*')) {throw 'Wrong unknown-clock prompt'}
    $cases+=@{case=$script:case;events=$script:events.ToArray();titles=$script:titles.ToArray();read_only=$result.read_only}
}
@{jobs=$jobs;cases=$cases} | ConvertTo-Json -Depth 6
