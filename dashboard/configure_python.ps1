param([switch]$SelfTest,[switch]$FromApp,[string]$TestPython)
$ErrorActionPreference='Stop'
if($SelfTest){[Console]::OutputEncoding=New-Object System.Text.UTF8Encoding($false)}
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$repository=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'app_python.ps1')
$work=if($SelfTest){Join-Path $env:TEMP 'delta1-python-setup-selftest'}else{Join-Path $PSScriptRoot 'runtime/python_setup'}
New-Item -ItemType Directory -Force -Path $work | Out-Null

function Quote-Argument([string]$Value) {
    '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

$form=New-Object System.Windows.Forms.Form
$form.Text='看板 Python 环境设置';$form.StartPosition='CenterScreen'
$form.ClientSize=New-Object System.Drawing.Size(720,530)
$form.MinimumSize=New-Object System.Drawing.Size(700,540)
$font=New-Object System.Drawing.Font('Microsoft YaHei UI',10)
$form.Font=$font
$pathLabel=New-Object System.Windows.Forms.Label
$pathLabel.SetBounds(20,18,660,26);$pathLabel.Text='选择看板使用的 Python 解释器（python.exe）'
$path=New-Object System.Windows.Forms.TextBox
$path.SetBounds(20,50,558,32);$path.Anchor='Top,Left,Right'
try { $path.Text=Get-AppPython $repository } catch { $path.Text='' }
$browse=New-Object System.Windows.Forms.Button
$browse.SetBounds(590,48,110,34);$browse.Anchor='Top,Right';$browse.Text='浏览…'
$hint=New-Object System.Windows.Forms.Label
$hint.SetBounds(20,92,680,52);$hint.Anchor='Top,Left,Right'
$hint.Text='检查版本与依赖；补齐安装到看板专用目录，不修改所选 Python 的原有包。Wind 终端和 VPN 客户端需在本机可用。'
$check=New-Object System.Windows.Forms.Button;$check.SetBounds(20,151,158,40);$check.Text='检查环境'
$install=New-Object System.Windows.Forms.Button;$install.SetBounds(190,151,165,40);$install.Text='一键补齐依赖'
$use=New-Object System.Windows.Forms.Button;$use.SetBounds(367,151,180,40);$use.Text='保存选择并启动'
if($FromApp){$use.Text='保存选择（重启生效）'}
$output=New-Object System.Windows.Forms.TextBox
$output.SetBounds(20,205,680,230);$output.Anchor='Top,Bottom,Left,Right'
$output.Multiline=$true;$output.ReadOnly=$true;$output.ScrollBars='Vertical'
$progress=New-Object System.Windows.Forms.ProgressBar
$progress.SetBounds(20,449,680,16);$progress.Anchor='Bottom,Left,Right';$progress.Style='Continuous'
$status=New-Object System.Windows.Forms.Label
$status.SetBounds(20,477,680,32);$status.Anchor='Bottom,Left,Right';$status.Text='先检查所选环境，再按需补齐。'
$form.Controls.AddRange(@($pathLabel,$path,$browse,$hint,$check,$install,$use,$output,$progress,$status))
$script:ReadyPython='';$script:Task=$null;$script:TaskAction='';$script:Report=''
$timer=New-Object System.Windows.Forms.Timer;$timer.Interval=300

function Set-Busy([bool]$Busy) {
    $browse.Enabled=-not $Busy;$check.Enabled=-not $Busy;$install.Enabled=-not $Busy;$use.Enabled=-not $Busy;$path.Enabled=-not $Busy
    $progress.Style=if($Busy){'Marquee'}else{'Continuous'}
}
function Start-Task([string]$Action) {
    $python=$path.Text.Trim()
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { $status.Text='请选择存在的 python.exe。';return }
    $script:TaskAction=$Action
    $script:Report=Join-Path $work ('result-'+[Guid]::NewGuid().ToString('N')+'.json')
    $arguments=@('-B','-X','utf8','-m','dashboard.python_environment',$Action,'--output',$script:Report)
    $argumentLine=($arguments | ForEach-Object { Quote-Argument $_ }) -join ' '
    try {
        $info=New-Object System.Diagnostics.ProcessStartInfo
        $info.FileName=$python;$info.Arguments=$argumentLine;$info.WorkingDirectory=$repository
        $info.UseShellExecute=$false;$info.CreateNoWindow=$true
        $parent=$info.EnvironmentVariables['DELTA1_APP_PYTHON'];$overlay=$info.EnvironmentVariables['DELTA1_APP_OVERLAY']
        if($parent -and $overlay -and [IO.Path]::GetFullPath($parent) -ine [IO.Path]::GetFullPath($python)){
            $remaining=@($info.EnvironmentVariables['PYTHONPATH'] -split ';' | Where-Object {$_ -and [IO.Path]::GetFullPath($_) -ine [IO.Path]::GetFullPath($overlay)})
            if($remaining.Count){$info.EnvironmentVariables['PYTHONPATH']=$remaining -join ';'}else{[void]$info.EnvironmentVariables.Remove('PYTHONPATH')}
            [void]$info.EnvironmentVariables.Remove('DELTA1_APP_PYTHON');[void]$info.EnvironmentVariables.Remove('DELTA1_APP_OVERLAY')
        }
        $script:Task=[System.Diagnostics.Process]::Start($info)
        Set-Busy $true;$status.Text=if($Action -eq 'install'){'正在补齐依赖，请稍候…'}elseif($Action -eq 'select'){'正在保存选择…'}else{'正在检查环境…'}
        $timer.Start()
    } catch { $status.Text='无法启动所选 Python，请检查路径和权限。' }
}
$browse.Add_Click({
    $dialog=New-Object System.Windows.Forms.OpenFileDialog
    $dialog.Filter='Python (python.exe)|python.exe|可执行文件 (*.exe)|*.exe';$dialog.CheckFileExists=$true
    if($dialog.ShowDialog($form) -eq [System.Windows.Forms.DialogResult]::OK){$path.Text=$dialog.FileName}
    $dialog.Dispose()
})
$path.Add_TextChanged({$script:ReadyPython=''})
$check.Add_Click({Start-Task 'probe'})
$install.Add_Click({Start-Task 'install'})
$use.Add_Click({
    if($script:ReadyPython -ne $path.Text.Trim()){$status.Text='请先检查或补齐这个 Python 环境。';return}
    Start-Task 'select'
})
$timer.Add_Tick({
    if($null -eq $script:Task -or -not $script:Task.HasExited){return}
    $timer.Stop();Set-Busy $false
    try { $report=Get-Content -LiteralPath $script:Report -Raw -Encoding UTF8 | ConvertFrom-Json }
    catch { $status.Text='环境工具未完成，请检查解释器是否可用。';return }
    $detail=if($script:TaskAction -eq 'install'){$report.check}else{$report}
    if($null -ne $detail.packages){
        $lines=@('Python '+$detail.version+' / '+$detail.bits+' 位')
        foreach($item in $detail.packages){
            $label=if($item.status -eq 'ok'){'可用'}elseif($item.status -eq 'version_mismatch'){'版本不匹配'}else{'缺失或无法加载'}
            $lines+=($item.package+'：'+$label+$(if($item.version){'  '+$item.version}else{''}))
        }
        if($detail.compatible){$lines+=('WindPy：'+$(if($detail.windpy_detected){'已找到'}else{'未找到，相关功能需本机 Wind 环境'}))}
        else{$lines+='解释器不受支持，尚未检查依赖。'}
        $output.Lines=$lines
    }
    if($script:TaskAction -eq 'select' -and $report.ok){
        if($FromApp){$status.Text='已保存，正常重启看板后生效。';$form.Close();return}
        $status.Text='已保存，将启动看板。'
        $launch=Join-Path $PSScriptRoot 'start_presentation.vbs'
        Start-Process -FilePath 'wscript.exe' -ArgumentList (Quote-Argument $launch) -WindowStyle Hidden | Out-Null
        $form.Close();return
    }
    if($report.ok){
        $script:ReadyPython=$path.Text.Trim()
        $status.Text='环境可用；点击“保存选择并启动”。'
    }else{
        $script:ReadyPython=''
        $status.Text=switch($report.stage){
            'unsupported_python' {'需要受支持的 64 位 Python 3.10 或更高版本。'}
            'pip_unavailable' {'所选 Python 缺少 pip，请使用内置 Python 或准备 pip 后重试。'}
            'install_failed' {'依赖补齐未完成，请检查网络或离线安装包后重试。'}
            'verification_failed' {'安装后检查未通过，请查看下方包状态。'}
            default {'部分依赖缺失或版本不匹配，可点击“一键补齐依赖”。'}
        }
    }
})
$form.Add_FormClosing({$timer.Stop()})
if($SelfTest){
    if($TestPython){
        $path.Text=$TestPython;Start-Task 'probe'
        $deadline=[DateTime]::UtcNow.AddSeconds(60)
        while($timer.Enabled -and [DateTime]::UtcNow -lt $deadline){[System.Windows.Forms.Application]::DoEvents();[Threading.Thread]::Sleep(30)}
        if($timer.Enabled){throw 'python_setup_probe_timeout'}
    }
    [pscustomobject]@{title=$form.Text;buttons=@($check.Text,$install.Text,$use.Text);controls=$form.Controls.Count;
        status=$status.Text;result=$output.Text} | ConvertTo-Json -Compress
}else{[void]$form.ShowDialog()}
$timer.Dispose();$form.Dispose();$font.Dispose()
