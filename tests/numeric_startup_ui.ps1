param([string]$Python,[string]$LocalRoot,[string]$RunFolder,[string]$Project)
$ErrorActionPreference='Stop'
$projectRoot=$Project
. (Join-Path $Project 'dashboard/excel_numeric/startup.ps1')
Add-Type -AssemblyName System.Windows.Forms
$clicks=[Collections.Generic.List[string]]::new()
$timer=[Windows.Forms.Timer]::new();$timer.Interval=200
$started=Get-Date
$timer.Add_Tick({
    if(((Get-Date)-$started).TotalSeconds -gt 60){throw 'Startup UI timed out'}
    foreach($form in @([Windows.Forms.Application]::OpenForms)){
        $button=$null
        switch($form.Text){
            'Delta1 · 历史数据' {$button=@($form.Controls | Where-Object Text -eq '检查并补齐')[0]}
            'Delta1 · 历史网络' {$button=@($form.Controls | Where-Object Text -eq '自动连接并补齐')[0]}
            'Delta1 · 历史结果' {
                $text=@($form.Controls | Where-Object {$_ -is [Windows.Forms.Label]})[0].Text
                if($text -notlike '*DDB未配置*'){throw "Unexpected history result: $text"}
                $button=@($form.Controls | Where-Object Text -eq '继续打开看板')[0]
            }
            'Delta1 · 行情网络' {$button=@($form.Controls | Where-Object Text -eq '只读打开')[0]}
            'Delta1 · 历史任务已退出' {$button=@($form.Controls | Where-Object Text -eq '只读打开')[0]}
        }
        if($button){$clicks.Add($form.Text);$button.PerformClick();break}
    }
})
try {
    $timer.Start()
    $result=Invoke-NumericWizard $Python $LocalRoot $RunFolder
    if(-not $result.read_only -or $result.cancelled){throw 'Expected readonly fallback'}
    if($clicks.Count -lt 3){throw 'History stages not traversed'}
    foreach($name in @('summary','history')){
        if(-not (Get-ChildItem -LiteralPath $RunFolder -Filter ($name+'-*.json'))){throw "Missing $name result"}
    }
    $timer.Stop()
    $cancelTimer=[Windows.Forms.Timer]::new();$cancelTimer.Interval=200
    $cancelTimer.Add_Tick({
        foreach($form in @([Windows.Forms.Application]::OpenForms)){
            if($form.Text -eq 'Delta1 · 正在检查'){
                $button=@($form.Controls | Where-Object Text -eq '取消并等待退出')[0]
                if($button.Enabled){$button.PerformClick()}
            }
        }
    })
    try {
        $cancelTimer.Start()
        $cancelled=Invoke-NumericJob $Python 'history' $LocalRoot $RunFolder '' 'tests.numeric_startup_worker'
        if($cancelled.state -ne 'cancelled'){throw 'Cancel not reported'}
        $workers=@(Get-ChildItem -LiteralPath $RunFolder -Filter 'history-*.json' | ForEach-Object {
            $r=Get-Content -LiteralPath $_.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
            if($r.state -eq 'synthetic_stopped'){$r}
        })
        if(-not $workers -or -not $workers[-1].cancelled){throw 'Worker did not observe cancellation'}
        if(Get-Process -Id $workers[-1].pid -ErrorAction SilentlyContinue){throw 'Worker still running after UI returned'}
    } finally {$cancelTimer.Stop();$cancelTimer.Dispose()}
    @{result=$result;stages=$clicks.ToArray();cancelled_worker_exited=$true} | ConvertTo-Json -Depth 4
} finally {$timer.Stop();$timer.Dispose()}
