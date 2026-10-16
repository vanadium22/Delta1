param(
    [string]$OutputDirectory = '',
    [switch]$NoPause
)

$ErrorActionPreference = 'Stop'
$exitCode = 0
$shell = $null
$shortcut = $null
$saved = $null
try {
    $appRoot = $PSScriptRoot
    $shortcutName = 'Delta1 券源工作台'
    $description = 'Delta1 - securities_lending (start.cmd)'
    $entryPath = Join-Path $appRoot 'start.cmd'
    $iconPath = Join-Path $appRoot 'assets\app.ico'
    $cmdPath = Join-Path $env:SystemRoot 'System32\cmd.exe'
    foreach ($requiredPath in @($entryPath, $iconPath, $cmdPath)) {
        if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
            throw "Required file not found: $requiredPath"
        }
    }
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
        # Resolve Windows' actual desktop, including redirected/OneDrive desktops.
        $OutputDirectory = [Environment]::GetFolderPath('DesktopDirectory')
    }
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
        throw 'Windows did not return a desktop folder.'
    }
    $OutputDirectory = [IO.Path]::GetFullPath($OutputDirectory)
    [IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
    $shortcutPath = Join-Path $OutputDirectory ($shortcutName + '.lnk')
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    if ((Test-Path -LiteralPath $shortcutPath) -and $shortcut.Description -ne $description) {
        throw "A different shortcut already has this name. Rename it first: $shortcutPath"
    }
    $shortcut.TargetPath = $cmdPath
    # The working directory carries the project path without embedding it in CMD code.
    $shortcut.Arguments = '/d /v:off /c .\start.cmd'
    $shortcut.WorkingDirectory = $appRoot
    $shortcut.IconLocation = $iconPath + ',0'
    $shortcut.Description = $description
    $shortcut.WindowStyle = 1
    $shortcut.Save()

    $saved = $shell.CreateShortcut($shortcutPath)
    if (-not (Test-Path -LiteralPath $shortcutPath -PathType Leaf) -or
        $saved.TargetPath -ne $cmdPath -or
        $saved.Arguments -ne $shortcut.Arguments -or
        $saved.WorkingDirectory -ne $appRoot -or
        $saved.IconLocation -ne ($iconPath + ',0')) {
        throw "Shortcut verification failed: $shortcutPath"
    }
    Write-Host "Created: $shortcutPath"
    Write-Host "Launch:  $entryPath"
    Write-Host "Icon:    $iconPath"
    Write-Host 'Run this script again after moving the project folder.'
} catch {
    Write-Host ("ERROR: " + $_.Exception.Message) -ForegroundColor Red
    $exitCode = 1
} finally {
    foreach ($comObject in @($saved, $shortcut, $shell)) {
        if ($null -ne $comObject) {
            [void][Runtime.InteropServices.Marshal]::ReleaseComObject($comObject)
        }
    }
    if (-not $NoPause) {
        Read-Host 'Press Enter to close' | Out-Null
    }
}
exit $exitCode
