param([ValidateSet('presentation','development')][string]$Edition='presentation',
      [Parameter(ValueFromRemainingArguments=$true)][string[]]$AppArguments)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'app_python.ps1')
$repository=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repository
$runtime=Join-Path $PSScriptRoot ('runtime/app_startup/run-'+$PID)
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
try {
    $interpreter=Get-AppPython $repository
    & $interpreter -B -s -X utf8 -m dashboard.app_check --output (Join-Path $runtime 'preflight.json') *> (Join-Path $runtime 'preflight.log')
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $interpreter -B -s -X utf8 -m dashboard.native.editions_current --edition $Edition @AppArguments *> (Join-Path $runtime ('app-'+$PID+'.log'))
    exit $LASTEXITCODE
} catch {
    $_.Exception.GetType().FullName | Out-File -LiteralPath (Join-Path $runtime 'launcher-error.log') -Encoding utf8
    exit 1
}
