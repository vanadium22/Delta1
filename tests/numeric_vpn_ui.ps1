param([string]$Project)
$ErrorActionPreference='Stop'
. (Join-Path $Project 'dashboard/excel_numeric/startup.ps1')
Add-Type -AssemblyName System.Windows.Forms

# Real Windows Forms, synthetic jobs: do not change any network or credentials.
function Invoke-NumericJob($Interpreter,$Action,$ConfigRoot,$Folder,$HistoryStatus,$JobModule='dashboard.numeric_startup',$VpnMode='auto') {
    $script:events.Add($Action+':'+$VpnMode)
    switch($Action) {
        'summary' { return [pscustomobject]@{local_root='fixture';history_dates=@{'1d'='2026-10-19';'1m'='2026-10-19'};target='2026-10-19';gate=@{allowed=$script:allowed}} }
        'history' {
            if($script:retry -and $VpnMode -eq 'auto') { return [pscustomobject]@{state='waiting_vpn';message='Synthetic VPN failure'} }
            $script:historyExited=$true
            return [pscustomobject]@{state='complete';message='Synthetic history complete'}
        }
        'probe' {
            if(-not $script:historyExited) { throw 'Probe before history exited' }
            return [pscustomobject]@{ok=$true}
        }
        default { throw 'Unexpected action' }
    }
}
$timer=[Windows.Forms.Timer]::new();$timer.Interval=100
$timer.Add_Tick({
    if(((Get-Date)-$script:started).TotalSeconds -gt 30) { throw 'VPN UI timed out' }
    foreach($form in @([Windows.Forms.Application]::OpenForms)) {
        $label=@($form.Controls | Where-Object {$_ -is [Windows.Forms.Label]})[0]
        $text=switch($form.Text) {
            'Delta1 · 历史数据' {'检查并补齐'}
            'Delta1 · 历史网络' {if($script:manual){'已手动连接，开始补齐'}else{'自动连接并补齐'}}
            'Delta1 · 历史网络未就绪' {'手动连接后重试'}
            'Delta1 · 历史结果' {
                if(-not $script:historyExited) { throw 'Result before history exited' }
                '继续打开看板'
            }
            'Delta1 · 行情网络' {
                if(-not $script:historyExited -or $label.Text -notlike '*手动切回实时行情VPN*') { throw 'Missing manual switch instruction' }
                '验证并打开'
            }
            'Delta1 · 历史任务已退出' {
                if(-not $script:historyExited -or $label.Text -notlike '*手动切回实时行情VPN*') { throw 'Missing off-hours switch instruction' }
                '只读打开'
            }
            default {throw ('Unexpected form '+$form.Text)}
        }
        $button=@($form.Controls | Where-Object Text -eq $text)[0]
        if(-not $button){throw ('Missing button '+$text)}
        $script:stages.Add($form.Text);$button.PerformClick();break
    }
})
$results=@()
try {
    foreach($case in @('auto','manual','retry','off-hours')) {
        $script:manual=$case -eq 'manual';$script:retry=$case -eq 'retry';$script:allowed=$case -ne 'off-hours'
        $script:historyExited=$false;$script:started=Get-Date
        $script:events=[Collections.Generic.List[string]]::new()
        $script:stages=[Collections.Generic.List[string]]::new()
        $timer.Start()
        $result=Invoke-NumericWizard 'fixture' 'fixture' 'fixture'
        $timer.Stop()
        if($result.cancelled -or $result.read_only -eq $script:allowed) { throw 'Wrong launch mode' }
        $history=@($script:events | Where-Object {$_ -like 'history:*'})
        $expected=switch($case) {'manual' {'history:manual'} 'retry' {'history:auto,history:manual'} default {'history:auto'}}
        if(($history -join ',') -ne $expected) { throw 'Wrong VPN mode order' }
        if(($case -eq 'retry') -ne ($script:stages -contains 'Delta1 · 历史网络未就绪')) { throw 'Wrong retry flow' }
        if(-not $script:allowed -and ($script:events -contains 'probe:auto')) { throw 'Off-hours realtime connection' }
        $results+=@{case=$case;events=$script:events.ToArray();stages=$script:stages.ToArray();read_only=$result.read_only}
    }
    $results | ConvertTo-Json -Depth 5
} finally {$timer.Stop();$timer.Dispose()}
