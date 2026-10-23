param([ValidateSet('presentation','development')][string]$Edition='presentation',
      [Parameter(ValueFromRemainingArguments=$true)][string[]]$AppArguments)
$ErrorActionPreference='Stop'
. (Join-Path $PSScriptRoot 'app_python.ps1')
$repository=Split-Path $PSScriptRoot -Parent
Set-Location -LiteralPath $repository
$runtime=Join-Path $PSScriptRoot ('runtime/app_startup/run-'+$PID)
New-Item -ItemType Directory -Force -Path $runtime | Out-Null

function ConvertTo-AppArgument {
    param([AllowEmptyString()][string]$Value)
    # Start-Process joins ArgumentList into one Windows command line.
    # Preserve spaces, quotes and trailing backslashes for the child argv.
    '"' + (($Value -replace '(\\*)"', '$1$1\"') -replace '(\\+)$', '$1$1') + '"'
}

function Invoke-AppProcess {
    param([string]$Interpreter,[string[]]$Arguments,[string]$LogName)
    $commandLine=($Arguments | ForEach-Object { ConvertTo-AppArgument $_ }) -join ' '
    # Hide only the console. SW_HIDE in STARTUPINFO also hides Qt's first
    # top-level window, so do not use Start-Process -WindowStyle Hidden here.
    $info=New-Object System.Diagnostics.ProcessStartInfo
    $info.FileName=$Interpreter;$info.Arguments=$commandLine
    $info.WorkingDirectory=$repository;$info.UseShellExecute=$false
    $info.CreateNoWindow=$true
    $info.RedirectStandardOutput=$true;$info.RedirectStandardError=$true
    $stdout=[System.IO.File]::Create((Join-Path $runtime ($LogName+'.log')))
    $stderr=[System.IO.File]::Create((Join-Path $runtime ($LogName+'.stderr.log')))
    $child=New-Object System.Diagnostics.Process
    $child.StartInfo=$info
    try {
        [void]$child.Start()
        # Drain both pipes concurrently: warning output must not stop or
        # deadlock a long-running App. Preserve bytes and the actual exit code.
        $outCopy=$child.StandardOutput.BaseStream.CopyToAsync($stdout)
        $errCopy=$child.StandardError.BaseStream.CopyToAsync($stderr)
        $child.WaitForExit()
        [void]$outCopy.GetAwaiter().GetResult();[void]$errCopy.GetAwaiter().GetResult()
        $child.ExitCode
    } finally {
        $stdout.Dispose();$stderr.Dispose();$child.Dispose()
    }
}

$launchState=@{schema='app-launch-v1';edition=$Edition;launcher_pid=$PID;phase='preflight';
    started_at=[DateTimeOffset]::Now.ToString('o');updated_at=$null;python=$null;exit_code=$null}
function Save-LaunchState {
    $launchState.updated_at=[DateTimeOffset]::Now.ToString('o')
    $launchState | ConvertTo-Json | Set-Content -LiteralPath (Join-Path $runtime 'launcher.json') -Encoding utf8
}
try {
    $interpreter=Get-AppPython $repository
    $launchState.python=$interpreter;Save-LaunchState
    $preflightCode=Invoke-AppProcess $interpreter @('-B','-s','-X','utf8','-X','faulthandler','-m','dashboard.app_check','--output',(Join-Path $runtime 'preflight.json')) 'preflight'
    if ($preflightCode -ne 0) {
        $launchState.phase='preflight_failed';$launchState.exit_code=$preflightCode;Save-LaunchState
        exit $preflightCode
    }
    $launchState.phase='app_running';Save-LaunchState
    $appParameters=@('-B','-s','-X','utf8','-X','faulthandler','-m','dashboard.native.editions_current','--edition',$Edition)
    if ($null -ne $AppArguments) { $appParameters+=$AppArguments }
    $appCode=Invoke-AppProcess $interpreter $appParameters ('app-'+$PID)
    $launchState.phase='app_exited';$launchState.exit_code=$appCode;Save-LaunchState
    exit $appCode
} catch {
    $launchState.phase='launcher_failed';$launchState.exit_code=1
    $launchState.error_type=$_.Exception.GetType().FullName
    $launchState.error_id=$_.FullyQualifiedErrorId
    Save-LaunchState
    $_.Exception.GetType().FullName | Out-File -LiteralPath (Join-Path $runtime 'launcher-error.log') -Encoding utf8
    exit 1
}
