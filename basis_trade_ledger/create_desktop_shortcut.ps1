param(
    [string]$OutputDirectory = '',
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$exitCode = 0
$shell = $link = $saved = $null
try {
    $entryPath = Join-Path $PSScriptRoot 'start.cmd'
    $iconPath = Join-Path $PSScriptRoot 'assets\app.ico'
    $cmdPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
    foreach ($file in @($entryPath, $iconPath, $cmdPath)) {
        if (-not (Test-Path -LiteralPath $file -PathType Leaf)) { throw "文件缺失 $file" }
    }
    if (-not $OutputDirectory) { $OutputDirectory = [Environment]::GetFolderPath('DesktopDirectory') }
    if (-not $OutputDirectory) { throw '找不到 Windows 桌面目录。' }
    $OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
    [IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
    $linkPath = Join-Path $OutputDirectory '基差交易台账.lnk'
    $description = 'Delta1 - basis_trade_ledger (start.cmd)'
    $arguments = '/d /v:off /c .\start.cmd'
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($linkPath)
    if ((Test-Path -LiteralPath $linkPath) -and $link.Description -ne $description) {
        throw "桌面已有同名快捷方式，请先为它改名 $linkPath"
    }
    $link.TargetPath = $cmdPath
    $link.Arguments = $arguments
    $link.WorkingDirectory = $PSScriptRoot
    $link.IconLocation = $iconPath + ',0'
    $link.Description = $description
    $link.WindowStyle = 7
    $link.Save()

    $saved = $shell.CreateShortcut($linkPath)
    if (-not (Test-Path -LiteralPath $linkPath -PathType Leaf) -or $saved.TargetPath -ne $cmdPath -or
        $saved.Arguments -ne $arguments -or $saved.WorkingDirectory -ne $PSScriptRoot -or
        $saved.IconLocation -ne ($iconPath + ',0')) {
        throw "快捷方式核验失败 $linkPath"
    }
    Write-Host "已创建 $linkPath"
    Write-Host "启动入口 $entryPath"
    Write-Host "图标 $iconPath"
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    $exitCode = 1
} finally {
    foreach ($object in @($saved, $link, $shell)) {
        if ($null -ne $object) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($object) }
    }
    if (-not $NoPause) { Read-Host '按 Enter 关闭' | Out-Null }
}
exit $exitCode
