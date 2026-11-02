param([Parameter(ValueFromRemainingArguments=$true)][string[]]$AppArguments)
$ErrorActionPreference='Stop'
$repository=Split-Path $PSScriptRoot -Parent
. (Join-Path $PSScriptRoot 'app_python.ps1')
$interpreter=Get-AppPython $repository
$runtime=Join-Path $PSScriptRoot ('runtime/backtest_startup/run-'+$PID)
New-Item -ItemType Directory -Force -Path $runtime | Out-Null
function ConvertTo-BacktestArgument {
    param([AllowEmptyString()][string]$Value)
    '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}
$arguments=@('-B','-s','-X','utf8','-m','dashboard.backtest.desktop_run')
if ($null -ne $AppArguments) { $arguments+=$AppArguments }
$info=New-Object System.Diagnostics.ProcessStartInfo
$info.FileName=$interpreter
$info.Arguments=($arguments | ForEach-Object { ConvertTo-BacktestArgument $_ }) -join ' '
$info.WorkingDirectory=$repository
$info.UseShellExecute=$false
$info.CreateNoWindow=$true
$info.RedirectStandardOutput=$true
$info.RedirectStandardError=$true
$stdout=[System.IO.File]::Create((Join-Path $runtime 'stdout.log'))
$stderr=[System.IO.File]::Create((Join-Path $runtime 'stderr.log'))
$child=New-Object System.Diagnostics.Process
$child.StartInfo=$info
try {
    [void]$child.Start()
    $outCopy=$child.StandardOutput.BaseStream.CopyToAsync($stdout)
    $errCopy=$child.StandardError.BaseStream.CopyToAsync($stderr)
    $child.WaitForExit()
    [void]$outCopy.GetAwaiter().GetResult()
    [void]$errCopy.GetAwaiter().GetResult()
    exit $child.ExitCode
} finally {
    $stdout.Dispose();$stderr.Dispose();$child.Dispose()
}
