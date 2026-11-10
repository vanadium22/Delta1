param(
    [string]$LocalRoot,
    [ValidateRange(0,1800)][int]$SampleSeconds=600,
    [switch]$NoPause
)
$ErrorActionPreference='Stop'

function Invoke-DeltaGit {
    param([string[]]$GitArguments)
    $result=& git @GitArguments
    if ($LASTEXITCODE -ne 0) { throw 'Git未完成；保留现场，不reset/clean。' }
    return $result
}
function Invoke-DeltaDiagnosis {
    param([string]$Repository,[string]$Profile,[string]$Reports)
    & (Join-Path $Repository 'dashboard/diagnose_presentation.cmd') -LocalRoot $Profile -OutputDirectory $Reports -Overview -NoPause | Out-Host
    if ($LASTEXITCODE -notin @(0,2)) { Write-Host 'Overview未完整结束，仍会保存已有报告并安全打包。' }
}
function Open-DeltaPresentation {
    param([string]$Repository,[string]$Profile)
    & "$env:WINDIR\System32\wscript.exe" (Join-Path $Repository 'dashboard/start_presentation.vbs') --theme public --local-root $Profile
}
function Export-DeltaReturn {
    param([string]$Repository,[string]$Profile,[string]$Reports)
    & (Join-Path $Repository 'dashboard/collect_company_return.cmd') -ReportDirectory $Reports -LocalRoot $Profile -RunMode runtime | Out-Host
    return $LASTEXITCODE
}
function Read-DeltaRun {
    param([string]$Path)
    try { return Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { return $null }
}
function Invoke-CompanyRetest {
    param([string]$Repository,[string]$Profile,[int]$Seconds=600)
    Set-Location -LiteralPath $Repository
    Write-Host '请先正常关闭旧看板，等待窗口自行退出。保留Wind终端登录；实时VPN仍由你手动连接。'
    [void](Read-Host '旧看板已退出后按回车，开始更新与复测')
    $branch=(Invoke-DeltaGit -GitArguments @('branch','--show-current')).Trim()
    if ($branch -ne 'codex/company-apps') { throw '当前不是codex/company-apps；不切换分支，请保留现场。' }
    Invoke-DeltaGit -GitArguments @('status','--short','--branch') | Out-Host
    Invoke-DeltaGit -GitArguments @('pull','--ff-only') | Out-Host
    Invoke-DeltaGit -GitArguments @('log','-1','--oneline') | Out-Host
    if (-not (Test-Path -LiteralPath (Join-Path $Profile 'native.json') -PathType Leaf)) { throw 'LocalRoot/native.json不存在，请核对实际配置路径。' }
    $started=Get-Date
    $reports=Join-Path $Repository ('dashboard/runtime/company_retest/'+$started.ToString('yyyyMMdd_HHmmss_fff'))
    New-Item -ItemType Directory -Path $reports -ErrorAction Stop | Out-Null
    [pscustomobject]@{ LocalRoot=$Profile;Branch=$branch;Commit=(Invoke-DeltaGit -GitArguments @('rev-parse','HEAD')).Trim();
        Status=@(Invoke-DeltaGit -GitArguments @('status','--short','--branch'));StartedAt=$started.ToString('o') } |
        ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $reports 'git.json') -Encoding UTF8
    $drive=Get-PSDrive -Name Y -ErrorAction SilentlyContinue
    [pscustomobject]@{ Mapped=[bool]$drive;Name=$drive.Name;Root=$drive.Root;DisplayRoot=$drive.DisplayRoot;ExpectedServer='192.168.91.230' } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reports 'drive_y.json') -Encoding UTF8
    Write-Host ('本轮报告：'+$reports)
    Open-DeltaPresentation $Repository $Profile
    Write-Host '保持新看板打开约10分钟，检查各页和大/中/小比例。中在1080p完整显示卡片。'
    Write-Host '检查行业覆盖/条形、ETF规模历史与变化、期货量仓图例；需要时在设置点一次DDB一键补齐并等待完成。'
    for ($remaining=$Seconds;$remaining -gt 0;$remaining-=[Math]::Min(30,$remaining)) {
        Write-Progress -Activity '保持看板打开取样' -Status ('剩余约 '+$remaining+' 秒') -PercentComplete (100*(1-$remaining/[Math]::Max(1,$Seconds)))
        Start-Sleep -Seconds ([Math]::Min(30,$remaining))
    }
    Write-Progress -Activity '保持看板打开取样' -Completed
    [void](Read-Host '保持窗口开着；确认已查看各页、实时采集正在运行后按回车，保存开窗Overview')
    Invoke-DeltaDiagnosis $Repository $Profile $reports
    $openRecord=$null
    foreach ($dir in @(Get-ChildItem -LiteralPath $reports -Directory -Filter 'diagnosis-*' | Sort-Object Name -Descending)) {
        $overview=Read-DeltaRun (Join-Path $dir.FullName 'overview.json')
        $record=@($overview.app_reports.matching_profile)[0]
        if ($record.report_path -and $record.collection_worker_running -and -not $record.closing) { $openRecord=$record.report_path;break }
    }
    Write-Host '现在请正常关闭看板，等待窗口自行消失。不要结束进程、删除锁或关闭Wind/Excel。'
    [void](Read-Host '看板窗口已自行退出后按回车，检查排空并保存关闭后Overview')
    if ($openRecord) {
        for ($waited=0;$waited -lt 240;$waited+=2) {
            $record=Read-DeltaRun $openRecord
            if ($record.phase -eq 'closed' -and $record.shutdown.complete) { break }
            if ($waited -eq 0) { Write-Host '后台仍在排空，最多等4分钟；不会强杀。超时也保留缺项反馈包。' }
            Start-Sleep -Seconds 2
        }
    } else { Write-Host '未识别到本轮开窗采集报告；包会如实标缺项，请仍回传。' }
    Invoke-DeltaDiagnosis $Repository $Profile $reports
    $code=Export-DeltaReturn $Repository $Profile $reports
    Write-Host '请回传上面打印的安全ZIP（仅白名单JSON），并说明页面比例、规模曲线和正常关闭感受。'
    return $code
}

if ($MyInvocation.InvocationName -ne '.') {
    try {
        $repository=Split-Path $PSScriptRoot -Parent
        if (-not $LocalRoot) { $LocalRoot=Join-Path $PSScriptRoot 'localsetting/app' }
        $code=Invoke-CompanyRetest -Repository $repository -Profile ([IO.Path]::GetFullPath($LocalRoot)) -Seconds $SampleSeconds
        if (-not $NoPause) { [void](Read-Host '结果已保留，按回车退出') }
        exit $code
    } catch {
        Write-Host ('复测未完成：'+$_.Exception.Message)
        if (-not $NoPause) { [void](Read-Host '请保留上述提示，按回车退出') }
        exit 1
    }
}
