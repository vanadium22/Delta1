param([switch]$InstallGui)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'app_python.ps1')
$repository=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repository
$interpreter=Get-AppPython $repository
if ($InstallGui) {
    # Local target only; existing pandas / Wind / SDK packages remain installed as-is.
    & $interpreter -m pip install --disable-pip-version-check --no-deps --target (Join-Path $repository '.deps/dashboard_native') -r (Join-Path $PSScriptRoot 'requirements-app-ui.txt')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}
& $interpreter -B -s -X utf8 -m dashboard.app_check --output (Join-Path $PSScriptRoot 'runtime/app_startup/preflight.json')
exit $LASTEXITCODE
