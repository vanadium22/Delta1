param([switch]$ProjectOnly)
$ErrorActionPreference='Stop'
$appRoot=[IO.Path]::GetFullPath($PSScriptRoot)
$target=Join-Path $appRoot 'start.cmd'
$icon=Join-Path $appRoot 'assets/research.ico'
if(-not (Test-Path -LiteralPath $target) -or -not (Test-Path -LiteralPath $icon)){throw 'Missing current launcher or icon'}
$shell=New-Object -ComObject WScript.Shell
$folders=@($appRoot)
if(-not $ProjectOnly){$folders+= [Environment]::GetFolderPath('Desktop')}
$legacy=@('start_app.cmd','start_dashboard.cmd','start_developer.cmd','start_viewer.cmd','start_demo.cmd','start_app_recovery.cmd')
$legacyTargets=@($legacy | ForEach-Object {Join-Path $appRoot $_})
$backup=Join-Path $appRoot 'runtime/retired_shortcuts'
foreach($folder in $folders){
    foreach($file in Get-ChildItem -LiteralPath $folder -Filter '*.lnk'){
        $link=$shell.CreateShortcut($file.FullName)
        if($legacyTargets -contains $link.TargetPath){
            New-Item -ItemType Directory -Path $backup -Force | Out-Null
            $copy=Join-Path $backup ((Split-Path -Leaf $folder)+'-'+$file.Name)
            if(-not(Test-Path -LiteralPath $copy)){Copy-Item -LiteralPath $file.FullName -Destination $copy}
            Remove-Item -LiteralPath $file.FullName
        }
    }
    $shortcut=Join-Path $folder 'Delta1 股指看板.lnk'
    if(Test-Path -LiteralPath $shortcut){
        $existing=$shell.CreateShortcut($shortcut)
        if($existing.TargetPath -ne $target){throw 'Unrelated shortcut occupies the requested name'}
    }
    $link=$shell.CreateShortcut($shortcut);$link.TargetPath=$target;$link.WorkingDirectory=$appRoot
    $link.IconLocation=$icon+',0';$link.Description='最新股指行情、连续合约指标与数据维护';$link.Save()
    $verified=$shell.CreateShortcut($shortcut)
    if($verified.TargetPath -ne $target -or $verified.IconLocation -ne ($icon+',0')){throw 'Shortcut verification failed'}
    Write-Output ('Ready: '+$shortcut)
}
