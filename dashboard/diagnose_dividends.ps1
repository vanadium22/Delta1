param(
    [string]$LocalRoot = '',
    [ValidateSet('Local','Share','Import')][string]$Stage = 'Local',
    [string]$Output = '',
    [switch]$NoPause
)
$ErrorActionPreference = 'Stop'
$exitCode = 2
try {
    $repository = Split-Path $PSScriptRoot -Parent
    . (Join-Path $PSScriptRoot 'app_python.ps1')
    $interpreter = Get-AppPython $repository
    if ([string]::IsNullOrWhiteSpace($LocalRoot)) {
        foreach ($candidate in @('localsetting/app','localsetting')) {
            $selected = Join-Path $PSScriptRoot $candidate
            if (Test-Path -LiteralPath (Join-Path $selected 'native.json')) {
                $LocalRoot = $selected
                break
            }
        }
    }
    if (-not (Test-Path -LiteralPath (Join-Path $LocalRoot 'native.json'))) { throw 'LocalRoot/native.json missing' }
    Set-Location -LiteralPath $repository
    $parameters = @('-B','-X','utf8','-m','dashboard.dividend_check','--local-root',$LocalRoot,'--stage',$Stage.ToLowerInvariant())
    if (-not [string]::IsNullOrWhiteSpace($Output)) { $parameters += @('--output',$Output) }
    & $interpreter @parameters
    $exitCode = $LASTEXITCODE
} catch {
    Write-Host ('Dividend check failed: ' + $_.Exception.GetType().Name)
} finally {
    if (-not $NoPause) { Read-Host 'Press Enter to close' | Out-Null }
}
exit $exitCode
