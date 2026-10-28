param(
    [string]$LocalRoot = '',
    [string]$OutputDirectory = '',
    [switch]$NoPause
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object Text.UTF8Encoding($false)
$exitCode = 2
$shell = $null
$shortcut = $null
$existing = $null
$checked = $null
$pendingPath = $null
try {
    $repository = [IO.Path]::GetFullPath((Split-Path $PSScriptRoot -Parent))
    $entry = Join-Path $PSScriptRoot 'start_presentation.vbs'
    $icon = Join-Path $PSScriptRoot 'assets/company_overview.ico'
    $target = Join-Path $env:SystemRoot 'System32/wscript.exe'
    foreach ($required in @($entry,$icon,$target)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) { throw 'Required shortcut asset missing' }
    }
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { $OutputDirectory = [Environment]::GetFolderPath('DesktopDirectory') }
    if ([string]::IsNullOrWhiteSpace($OutputDirectory)) { throw 'Desktop folder unavailable' }
    $outputRoot = [IO.Path]::GetFullPath($OutputDirectory)
    [void][IO.Directory]::CreateDirectory($outputRoot)
    $shortcutPath = [IO.Path]::GetFullPath((Join-Path $outputRoot 'Delta1 股指看板.lnk'))
    $pendingPath = [IO.Path]::GetFullPath((Join-Path $outputRoot ('.Delta1-public-' + [guid]::NewGuid().ToString('N') + '.lnk')))
    $boundary = $outputRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar
    foreach ($ownedPath in @($shortcutPath,$pendingPath)) {
        if (-not $ownedPath.StartsWith($boundary,[StringComparison]::OrdinalIgnoreCase)) { throw 'Shortcut path outside selected desktop' }
    }
    $shell = New-Object -ComObject WScript.Shell
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        $existing = $shell.CreateShortcut($shortcutPath)
        if ($existing.Arguments -notmatch 'start_presentation\.(vbs|cmd)' -and $existing.Description -ne 'Delta1 public dashboard') {
            throw 'The existing shortcut belongs to a different application'
        }
        if ([string]::IsNullOrWhiteSpace($LocalRoot) -and $existing.Arguments -match '--local-root\s+"([^"]+)"') { $LocalRoot = $Matches[1] }
    }
    if ([string]::IsNullOrWhiteSpace($LocalRoot)) {
        foreach ($candidate in @('localsetting/app','localsetting')) {
            $path = Join-Path $PSScriptRoot $candidate
            if (Test-Path -LiteralPath (Join-Path $path 'native.json')) { $LocalRoot = $path;break }
        }
        if ([string]::IsNullOrWhiteSpace($LocalRoot)) { $LocalRoot = Join-Path $PSScriptRoot 'localsetting/app' }
    }
    $LocalRoot = [IO.Path]::GetFullPath($LocalRoot)
    $arguments = '"' + $entry + '" --theme "public" --local-root "' + $LocalRoot + '"'
    $shortcut = $shell.CreateShortcut($pendingPath)
    $shortcut.TargetPath = $target
    $shortcut.Arguments = $arguments
    $shortcut.WorkingDirectory = $repository
    $shortcut.IconLocation = $icon + ',0'
    $shortcut.Description = 'Delta1 public dashboard'
    $shortcut.WindowStyle = 1
    $shortcut.Save()
    $checked = $shell.CreateShortcut($pendingPath)
    if (-not (Test-Path -LiteralPath $pendingPath -PathType Leaf) -or $checked.TargetPath -ne $target -or
        $checked.Arguments -ne $arguments -or $checked.WorkingDirectory -ne $repository -or $checked.IconLocation -ne ($icon+',0')) {
        throw 'New shortcut verification failed'
    }
    [void][Runtime.InteropServices.Marshal]::ReleaseComObject($checked)
    $checked = $null
    if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
        $backupRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot 'runtime/shortcut_backups'))
        if (-not $backupRoot.StartsWith(($PSScriptRoot.TrimEnd('\','/') + [IO.Path]::DirectorySeparatorChar),[StringComparison]::OrdinalIgnoreCase)) {
            throw 'Backup path outside dashboard'
        }
        [void][IO.Directory]::CreateDirectory($backupRoot)
        $backupPath = Join-Path $backupRoot ((Get-Date -Format 'yyyyMMdd_HHmmss_fffffff') + '.lnk')
        [IO.File]::WriteAllBytes($backupPath,[IO.File]::ReadAllBytes($shortcutPath))
    }
    # Both absolute targets were checked against the selected desktop above.
    Move-Item -LiteralPath $pendingPath -Destination $shortcutPath -Force
    $checked = $shell.CreateShortcut($shortcutPath)
    if ($checked.TargetPath -ne $target -or $checked.Arguments -ne $arguments -or $checked.IconLocation -ne ($icon+',0')) {
        throw 'Saved shortcut verification failed'
    }
    Write-Host ('Created: ' + $shortcutPath)
    Write-Host ('LocalRoot: ' + $LocalRoot)
    $exitCode = 0
} catch {
    Write-Host ('Shortcut creation failed: ' + $_.Exception.Message)
} finally {
    foreach ($item in @($checked,$existing,$shortcut,$shell)) {
        if ($null -ne $item) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($item) }
    }
    if ($pendingPath -and (Test-Path -LiteralPath $pendingPath -PathType Leaf)) { Remove-Item -LiteralPath $pendingPath }
    if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
}
exit $exitCode
