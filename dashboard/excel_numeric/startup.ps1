# Startup UI only. Background actions use the numeric Python; DDB login is optional.
function Resolve-NumericPython([string]$Interpreter) {
    $command=Get-Command -Name $Interpreter -CommandType Application -ErrorAction Stop | Select-Object -First 1
    return $command.Source
}

function Invoke-NumericChoice([string]$Title, [string]$Message, [string]$Primary, [string]$Secondary) {
    $form = New-Object Windows.Forms.Form
    $form.Text=$Title; $form.Width=620; $form.Height=250; $form.StartPosition='CenterScreen'
    $form.FormBorderStyle='FixedDialog'; $form.MaximizeBox=$false; $form.MinimizeBox=$false
    $form.Font=New-Object Drawing.Font('Microsoft YaHei',10)
    $label=New-Object Windows.Forms.Label
    $label.Text=$Message; $label.SetBounds(24,20,550,115)
    $a=New-Object Windows.Forms.Button; $a.Text=$Primary; $a.SetBounds(24,145,240,38)
    $a.DialogResult=[Windows.Forms.DialogResult]::Yes
    $b=New-Object Windows.Forms.Button; $b.Text=$Secondary; $b.SetBounds(300,145,270,38)
    $b.DialogResult=[Windows.Forms.DialogResult]::No
    $form.Controls.AddRange(@($label,$a,$b)); $form.AcceptButton=$a
    try { return $form.ShowDialog().ToString() } finally { $form.Dispose() }
}

function Invoke-NumericJob([string]$Interpreter, [string]$Action, [string]$ConfigRoot, [string]$Folder, [string]$HistoryStatus, [string]$JobModule='dashboard.numeric_startup', [string]$VpnMode='auto') {
    $report=Join-Path $Folder ($Action+'-'+[guid]::NewGuid().ToString('N')+'.json')
    $stop=$report+'.stop'
    $argsList=@('-B','-X','utf8','-m',$JobModule,$Action,'--report',$report,'--stop-file',$stop)
    if ($ConfigRoot) { $argsList+=@('--local-root',$ConfigRoot) }
    if ($Action -eq 'history' -and $JobModule -eq 'dashboard.numeric_startup') { $argsList+=@('--vpn-mode',$VpnMode) }
    $quoted=$argsList | ForEach-Object { if ($_ -match '"') { throw '参数不得含双引号' }; '"'+$_+'"' }
    $process=Start-Process -FilePath $Interpreter -ArgumentList $quoted -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput ($report+'.out') -RedirectStandardError ($report+'.err')
    # Keep the child handle before a fast process exits (Windows PowerShell 5).
    $jobHandle=$process.Handle
    $started=Get-Date
    $form=New-Object Windows.Forms.Form; $form.Text='Delta1 · 正在检查'; $form.Width=620; $form.Height=220
    $form.StartPosition='CenterScreen'; $form.Font=New-Object Drawing.Font('Microsoft YaHei',10)
    $label=New-Object Windows.Forms.Label; $label.SetBounds(20,20,560,100)
    $label.Text=if($Action -eq 'history'){'正在扫描历史缺口，旧数据仍可保留。'}else{'正在验证，请稍候。'}
    $button=New-Object Windows.Forms.Button; $button.Text='取消并等待退出'; $button.SetBounds(20,125,260,36)
    $state=@{cancelled=$false;cancelTime=$null;finished=$false}
    $cancel={
        if(-not $state.cancelled) {
            [IO.File]::WriteAllText($stop,'stop'); $state.cancelled=$true; $state.cancelTime=Get-Date
            $label.Text='正在结束本次任务，请等待；结束前不要切换网络。'; $button.Enabled=$false
        }
    }
    $button.Add_Click($cancel)
    $form.Add_FormClosing({param($sender,$eventArgs) if(-not $state.finished){$eventArgs.Cancel=$true; & $cancel}})
    $timer=New-Object Windows.Forms.Timer; $timer.Interval=300
    $timer.Add_Tick({
        if($process.HasExited) { $process.WaitForExit(); $state.finished=$true; $timer.Stop(); $form.Close(); return }
        if(((Get-Date)-$started).TotalMinutes -gt 45) { & $cancel }
        if($state.cancelled -and ((Get-Date)-$state.cancelTime).TotalSeconds -gt 30) {
            $process.Kill(); $process.WaitForExit(); return
        }
        if(-not $state.cancelled -and $Action -eq 'history' -and (Test-Path -LiteralPath $report)) {
            try {
                $phase=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
                if($phase.state -eq 'connecting_vpn') { $label.Text=[string]$phase.message; return }
            } catch {}
        }
        if(-not $state.cancelled -and $Action -eq 'history' -and $HistoryStatus -and (Test-Path -LiteralPath $HistoryStatus)) {
            try {
                $s=Get-Content -LiteralPath $HistoryStatus -Raw -Encoding UTF8 | ConvertFrom-Json
                if([DateTimeOffset]::Parse($s.updated_at).LocalDateTime -ge $started) {
                    $label.Text=[string]$s.message+"`r`n剩余 "+$s.pending_symbol_days+' 项 · 本轮发布 '+$s.inserted+' 条'
                }
            } catch {}
        }
    })
    $form.Controls.AddRange(@($label,$button))
    try {
        $timer.Start(); [void]$form.ShowDialog()
        if($state.cancelled) { return [pscustomobject]@{state='cancelled';message='已取消，历史任务已退出。';ok=$false} }
        $runtime=$null
        try {
            if(Test-Path -LiteralPath ($report+'.runtime.json')) {
                $runtime=Get-Content -LiteralPath ($report+'.runtime.json') -Raw -Encoding UTF8 | ConvertFrom-Json
            }
        } catch {}
        try {
            if(Test-Path -LiteralPath $report) {
                $result=Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
                if($process.ExitCode -eq 0 -or $result.state -eq 'failed') {
                    $result | Add-Member -NotePropertyName exit_code -NotePropertyValue $process.ExitCode -Force
                    $result | Add-Member -NotePropertyName requested_python -NotePropertyValue $Interpreter -Force
                    if($runtime) { $result | Add-Member -NotePropertyName runtime -NotePropertyValue $runtime -Force }
                    if($result.state -eq 'failed') {
                        $result | Add-Member -NotePropertyName ok -NotePropertyValue $false -Force
                        $result | Add-Member -NotePropertyName diagnostic_file -NotePropertyValue ($report+'.err') -Force
                        $result.message=[string]$result.message+"`r`n诊断："+($report+'.err')
                    }
                    return $result
                }
            }
        } catch {}
        return [pscustomobject]@{state='failed';message=('检查未完成或结果不可读；Python：'+$Interpreter+"`r`n诊断："+$report+'.err');ok=$false;diagnostic_file=($report+'.err');exit_code=$process.ExitCode;requested_python=$Interpreter;runtime=$runtime}
    } finally {
        $timer.Stop(); $timer.Dispose(); $form.Dispose()
        if(-not $process.HasExited) {
            [IO.File]::WriteAllText($stop,'stop')
            if(-not $process.WaitForExit(30000)) { $process.Kill(); $process.WaitForExit() }
        }
        $process.Dispose()
    }
}

function Invoke-NumericSummary([string]$Interpreter, [string]$ConfigRoot, [string]$Folder) {
    while($true) {
        $info=Invoke-NumericJob $Interpreter 'summary' $ConfigRoot $Folder ''
        if($info.error.stage -ne 'imports') { return $info }
        $choice=Invoke-NumericChoice 'Delta1 · Python环境' ([string]$info.message) '重试检查' '退出'
        if($choice -ne 'Yes') { return [pscustomobject]@{state='cancelled'} }
    }
}

function Invoke-NumericWizard([string]$Interpreter, [string]$ConfigRoot, [string]$Folder) {
    $done=$null
    Add-Type -AssemblyName System.Windows.Forms
    Add-Type -AssemblyName System.Drawing
    [Windows.Forms.Application]::EnableVisualStyles()
    $info=Invoke-NumericSummary $Interpreter $ConfigRoot $Folder
    if($info.state -eq 'cancelled') { return @{cancelled=$true} }
    if($info.local_root) { $ConfigRoot=$info.local_root }
    $description=if($info.history_dates) {
        '日线 '+$info.history_dates.'1d'+' · 分钟 '+$info.history_dates.'1m'+"`r`n补齐目标："+$info.target+"（完整缺口会另行核验）"
    } else { [string]$info.message }
    $choice=Invoke-NumericChoice 'Delta1 · 历史数据' $description '检查并补齐' '使用现有数据'
    if($choice -notin @('Yes','No')) { return @{cancelled=$true} }
    if($choice -eq 'Yes') {
        $choice=Invoke-NumericChoice 'Delta1 · 历史网络' "自动模式优先复用已连通网络，否则使用本机VPN配置登录。`r`n补齐结束后，请手动切回实时行情VPN。" '自动连接并补齐' '已手动连接，开始补齐'
        if($choice -notin @('Yes','No')) { return @{cancelled=$true} }
        if($choice -in @('Yes','No')) {
            $vpnMode=if($choice -eq 'Yes'){'auto'}else{'manual'}
            $hp=if($info.history_python){$info.history_python}else{$Interpreter}
            try { $done=Invoke-NumericJob $hp 'history' $ConfigRoot $Folder $info.history_status 'dashboard.numeric_startup' $vpnMode }
            catch { $done=[pscustomobject]@{message='历史Python无法启动；请配置已有解释器。'} }
            while($done.state -in @('waiting_vpn','waiting_network')) {
                $choice=Invoke-NumericChoice 'Delta1 · 历史网络未就绪' ([string]$done.message) '手动连接后重试' '使用现有数据'
                if($choice -eq 'No') { break }
                if($choice -ne 'Yes') { return @{cancelled=$true} }
                try { $done=Invoke-NumericJob $hp 'history' $ConfigRoot $Folder $info.history_status 'dashboard.numeric_startup' 'manual' }
                catch { $done=[pscustomobject]@{message='历史Python无法启动；请配置已有解释器。'} }
            }
            $choice=Invoke-NumericChoice 'Delta1 · 历史结果' ([string]$done.message) '继续打开看板' '退出'
            if($choice -ne 'Yes') { return @{cancelled=$true} }
        }
    }
    # Refresh the clock after a possibly long history task. Never reuse the old gate.
    $info=Invoke-NumericSummary $Interpreter $ConfigRoot $Folder
    if($info.state -eq 'cancelled') { return @{cancelled=$true} }
    while(-not $info.gate -or $info.gate.allowed -isnot [bool]) {
        $choice=Invoke-NumericChoice 'Delta1 · 时段检查未完成' ("尚未取得有效时段判断，不能视为非交易时段。`r`n"+[string]$info.message) '重试检查' '只读打开'
        if($choice -eq 'No') { return @{read_only=$true;local_root=$ConfigRoot} }
        if($choice -ne 'Yes') { return @{cancelled=$true} }
        $info=Invoke-NumericSummary $Interpreter $ConfigRoot $Folder
        if($info.state -eq 'cancelled') { return @{cancelled=$true} }
    }
    if(-not $info.gate.allowed) {
        if($done) {
            $choice=Invoke-NumericChoice 'Delta1 · 历史任务已退出' "当前不在行情接入时段，将只读打开。`r`n如需恢复公司网络，请手动切回实时行情VPN。" '只读打开' '退出'
            if($choice -ne 'Yes') { return @{cancelled=$true} }
        }
        return @{read_only=$true;local_root=$ConfigRoot}
    }
    while($true) {
        $choice=Invoke-NumericChoice 'Delta1 · 行情网络' "历史任务已退出。请手动切回实时行情VPN。`r`n连接完成后再验证；只读模式不采集新行情。" '验证并打开' '只读打开'
        if($choice -notin @('Yes','No')) { return @{cancelled=$true} }
        if($choice -eq 'No') { return @{read_only=$true;local_root=$ConfigRoot} }
        $probe=Invoke-NumericJob $Interpreter 'probe' $ConfigRoot $Folder ''
        if($probe.ok) { return @{read_only=$false;local_root=$ConfigRoot} }
        if($probe.offline) { return @{read_only=$true;local_root=$ConfigRoot} }
        $choice=Invoke-NumericChoice 'Delta1 · 网络未就绪' ([string]$probe.message) '重试' '只读打开'
        if($choice -eq 'No') { return @{read_only=$true;local_root=$ConfigRoot} }
        if($choice -ne 'Yes') { return @{cancelled=$true} }
    }
}
