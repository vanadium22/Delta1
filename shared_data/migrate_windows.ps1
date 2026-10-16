param(
    [switch]$NoPause,
    [switch]$PlanOnly
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$exitStatus = 1
try {
    Set-Location -LiteralPath $projectRoot
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    [Console]::OutputEncoding = New-Object System.Text.UTF8Encoding($false)
    $candidates = @($env:SWHY_DELTA1_PYTHON, $env:BASIS_APP_PYTHON, $env:REPORT_APP_PYTHON, $env:D1_LENDING_PYTHON)
    foreach ($module in @('index_futures_basis', 'script_making', 'securities_lending')) {
        $setting = Join-Path $projectRoot "$module\python.local.txt"
        if (Test-Path -LiteralPath $setting -PathType Leaf) {
            $candidates += (Get-Content -LiteralPath $setting -Encoding UTF8 -TotalCount 1).Trim().Trim('"')
        }
    }
    $candidates += 'D:\conda\envs\swhy_delta1\python.exe'
    if ($env:CONDA_PREFIX) { $candidates += (Join-Path $env:CONDA_PREFIX 'python.exe') }
    $environments = Join-Path $env:USERPROFILE '.conda\environments.txt'
    if (Test-Path -LiteralPath $environments -PathType Leaf) {
        foreach ($registered in Get-Content -LiteralPath $environments) {
            if ((Split-Path -Leaf $registered) -ieq 'swhy_delta1') {
                $candidates += (Join-Path $registered 'python.exe')
            }
        }
    }
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($command) { $candidates += $command.Source }
    $interpreter = $null
    foreach ($candidate in $candidates) {
        if ($candidate) { $candidate = $candidate.Trim().Trim('"') }
        if ($candidate -and (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            if ([IO.Path]::GetFileName($candidate) -ieq 'pythonw.exe') {
                $candidate = Join-Path (Split-Path -Parent $candidate) 'python.exe'
            }
            if (Test-Path -LiteralPath $candidate -PathType Leaf) {
                & $candidate -B -s -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>$null
                if ($LASTEXITCODE -eq 0) { $interpreter = $candidate; break }
            }
        }
    }
    if (-not $interpreter) { throw 'Python 3.10+ not found. Configure SWHY_DELTA1_PYTHON or a module python.local.txt first.' }
    Write-Host "Repository: $projectRoot"
    Write-Host "Python: $interpreter"
    Write-Host 'Close the Apps before migrating. Existing source files will be retained.'
    $arguments = @('-B', '-s', '-X', 'utf8', '-m', 'shared_data', 'migrate', '--summary')
    if (-not $PlanOnly) { $arguments += '--apply' }
    & $interpreter @arguments
    $exitStatus = $LASTEXITCODE
    if ($exitStatus -ne 0) {
        Write-Host 'Migration stopped. Original files are preserved. Resolve the error above and run again.' -ForegroundColor Red
    }
}
catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    Write-Host 'No original files were removed.'
    $exitStatus = 1
}
finally {
    if (-not $NoPause) { [void](Read-Host 'Press Enter to close') }
}
exit $exitStatus
