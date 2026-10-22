param(
    [string]$Python = 'python', [string]$Output, [string]$LocalRoot,
    [string]$Snapshot, [string]$FeedFile, [switch]$ReadOnlyCache,
    [switch]$Once, [switch]$Hidden, [switch]$NoPrompt, [int]$MaxUpdates = 0
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$runRoot = Join-Path $projectRoot ('dashboard\runtime\numeric_live\' + [guid]::NewGuid().ToString('N'))
[void](New-Item -ItemType Directory -Path $runRoot -Force)
$stopFile = Join-Path $runRoot 'stop'
if (-not $Output) { $Output = Join-Path $projectRoot ('data\cache\dashboard\numeric\数字看板_' + (Get-Date -Format 'yyyyMMdd_HHmmss') + '.xlsx') }
$Output = [IO.Path]::GetFullPath($Output)
if (Test-Path -LiteralPath $Output) { throw '输出文件已存在，请另选文件名以保留原工作簿。' }
[void](New-Item -ItemType Directory -Path (Split-Path $Output -Parent) -Force)
$producer = $null; $excel = $null; $book = $null; $owned = $false
$runId = Split-Path $runRoot -Leaf
$runFile = Join-Path $runRoot 'run.json'
$run = [ordered]@{ run_id=$runId; launcher_pid=$PID; started_at=[DateTimeOffset]::Now.ToString('o');
    output=$Output; requested_python=$Python; read_only_cache=[bool]$ReadOnlyCache; state='starting';
    heartbeat_at=$null; last_write_at=$null; last_save_at=$null; error=$null; writes=0; saves=0 }
function SaveRun {
    $run.heartbeat_at = [DateTimeOffset]::Now.ToString('o')
    $tmp = $runFile + '.tmp'
    [IO.File]::WriteAllText($tmp, ($run | ConvertTo-Json -Depth 12), [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $tmp -Destination $runFile -Force
}
function Beijing($value) {
    if (-not $value) { return '无' }
    return [DateTimeOffset]::Parse($value).ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd HH:mm:ss')
}
function SheetRevision($feed, $name) {
    if ($feed.sheet_revisions -and $feed.sheet_revisions.$name) { return [string]$feed.sheet_revisions.$name }
    $raw = ConvertTo-Json -InputObject $feed.sheets.$name -Depth 30 -Compress
    $hash = [Security.Cryptography.SHA256]::Create()
    try { return [Convert]::ToBase64String($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($raw))) }
    finally { $hash.Dispose() }
}
function IsBusy($exception) {
    while ($exception) {
        if ($exception.HResult -in @(-2147418111,-2147417846,-2146777998,-2146827284)) { return $true }
        $exception = $exception.InnerException
    }
    return $false
}
function Set-ViewState([string]$Mode, [string]$Message, [string]$Identity, [string]$Times) {
    $book.Worksheets.Item('概览').Range('G3').Formula=$Mode
    $book.Worksheets.Item('概览').Range('B4').Formula=$Message
    $book.Worksheets.Item('概览').Range('B41').Formula=$Identity
    $book.Worksheets.Item('概览').Range('B42').Formula=$Times
    $book.Worksheets.Item('指标').Range('B4').Formula=$Mode+' · '+$Message
    $book.Worksheets.Item('指标').Range('B35').Formula=$Identity
    $book.Worksheets.Item('组合对比').Range('A5').Formula=$Identity+' · '+$Mode
}
SaveRun
function ProducerFailure {
    $errorLog = Join-Path $runRoot 'producer.err.log'
    $tail = if (Test-Path -LiteralPath $errorLog) { (Get-Content -LiteralPath $errorLog -Tail 15 -Encoding UTF8) -join [Environment]::NewLine } else { '' }
    return "数据服务退出，日志：$errorLog`n$tail"
}
. (Join-Path $PSScriptRoot 'workspace.ps1')
$selectionFile=Join-Path $runRoot 'selection.json'
try {
    . (Join-Path $PSScriptRoot 'startup.ps1')
    Write-Output "Python请求: $Python"
    Write-Output "启动检查日志：$runRoot"
    if (-not $FeedFile) {
        $Python=Resolve-NumericPython $Python
        $run['resolved_python']=$Python
        SaveRun
        Write-Output "Python路径: $Python"
    }
    if (-not ($ReadOnlyCache -or $Once -or $Hidden -or $Snapshot -or $FeedFile -or $NoPrompt)) {
        $choice=Invoke-NumericWizard $Python $LocalRoot $runRoot
        if ($choice.cancelled) { $run.state='cancelled'; return }
        $ReadOnlyCache=[bool]$choice.read_only
        if ($choice.local_root) { $LocalRoot=$choice.local_root }
        $run.read_only_cache=[bool]$ReadOnlyCache
    }
    if (-not $FeedFile) {
        $FeedFile = Join-Path $runRoot 'workbook.json'
        $arguments = @('-B','-X','utf8','-m','dashboard.numeric_excel','--feed',$FeedFile,'--stop-file',$stopFile)
        $arguments += @('--selection-file',$selectionFile)
        if ($LocalRoot) { $arguments += @('--local-root',[IO.Path]::GetFullPath($LocalRoot)) }
        if ($Snapshot) { $arguments += @('--snapshot',[IO.Path]::GetFullPath($Snapshot)); $Once = $true }
        elseif (-not $ReadOnlyCache) { $arguments += '--collect' }
        if ($Once) { $arguments += @('--iterations','1') }
        # Native process arguments, never a shell command.
        $quoted = $arguments | ForEach-Object { if ($_ -match '"') { throw '参数不得含双引号' }; '"' + $_ + '"' }
        $producer = Start-Process -FilePath $Python -ArgumentList $quoted -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'producer.out.log') -RedirectStandardError (Join-Path $runRoot 'producer.err.log')
        $run.producer_pid = $producer.Id
    }
    $run.feed = [IO.Path]::GetFullPath($FeedFile)
    SaveRun
    Write-Output "正在读取本地历史和行情缓存。Excel 将先打开，四个档位计算进度会显示在窗口中。日志：$runRoot"
    $statusFile = [IO.Path]::ChangeExtension($FeedFile, '.status.json')
    $deadline = (Get-Date).AddSeconds(600)
    while (-not (Test-Path -LiteralPath $FeedFile)) {
        if ($producer -and $producer.HasExited) { throw (ProducerFailure) }
        if ((Get-Date) -gt $deadline) { throw "等待数据服务初始化超时，日志：$runRoot" }
        Start-Sleep -Milliseconds 300
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'template.xlsx') -Destination $Output
    # Own a separate Excel instance; never attach to user workbooks.
    $excel = New-Object -ComObject Excel.Application
    $owned = $true; $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Open($Output)
    $excel.Calculation = -4105 # Automatic; selectors recalculate without another feed.
    $book.Worksheets.Item('概览').Activate()
    foreach ($sheet in $book.Worksheets) {
        if ($sheet.Name -notin @('概览','指标','组合对比','来源与状态')) { $sheet.Visible=0 }
    }
    $book.Windows.Item(1).Zoom=85
    $valueAxis=$book.Worksheets.Item('概览').ChartObjects(1).Chart.Axes(2)
    $valueAxis.MinimumScale=0; $valueAxis.MaximumScale=1
    $book.Worksheets.Item('概览').ChartObjects(1).Chart.PlotVisibleOnly=$false
    Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public class NumericWindow { [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h, out uint p); [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr h); }'
    $run.hwnd = [long]$excel.Hwnd
    [uint32]$excelProcessId = 0
    [void][NumericWindow]::GetWindowThreadProcessId([IntPtr]$run.hwnd, [ref]$excelProcessId)
    $run.excel_pid = $excelProcessId
    $book.Windows.Item(1).Caption = (Split-Path $Output -Leaf) + ' · Delta1 ' + $runId.Substring(0,8)
    foreach ($sheet in $book.Worksheets) {
        if ($sheet.Name -notin @('概览','指标','组合对比')) { $sheet.Range('A1').Formula = '文件：' + $Output }
    }
    # Excel may ignore Visible=True before it has an open workbook. Restore
    # only this owned workbook after Open; never attach to another instance.
    if (-not $Hidden) {
        $window = $book.Windows.Item(1)
        $window.Visible = $true
        $window.WindowState = -4137 # xlMaximized
        $book.Activate()
        $excel.Visible = $true
        if (-not $excel.Visible -or -not $window.Visible) { throw "Excel 窗口未能显示，文件：$Output；日志：$runRoot" }
        Write-Output "Excel 窗口已显示：$Output"
    }
    # Excel may replace its initial hidden application HWND when the workbook
    # becomes visible. Pin the actual workbook window only after showing it.
    $run.hwnd = [long]$book.Windows.Item(1).Hwnd
    [void][NumericWindow]::GetWindowThreadProcessId([IntPtr]$run.hwnd, [ref]$excelProcessId)
    $run.excel_pid = $excelProcessId
    $last = ''; $updates = 0; $counts = @{}; $revisions = @{}; $lastSuccess = Get-Date; $lastProgress = ''; $nextProgress = Get-Date
    $initialReady = $false; $nextRefreshNotice = Get-Date; $nextProgressNotice = Get-Date
    $nextHeartbeat = Get-Date; $nextStatusWrite = Get-Date; $lastMode = ''; $lastReady = $false
    $run.state = 'running'; $run.excel_visible = [NumericWindow]::IsWindowVisible([IntPtr]$run.hwnd)
    SaveRun
    while ($true) {
        if (Test-Path -LiteralPath $stopFile) { break }
        try { $open = $book.Name } catch {
            if (IsBusy $_.Exception) {
                $run.state='excel_busy'; $run.error='Excel 正在编辑或暂不接受 COM 调用；保留本次运行并重试。'; SaveRun
                Start-Sleep -Milliseconds 1000; continue
            }
            break
        }
        if (-not $open) { break }
        $feed = Get-Content -LiteralPath $FeedFile -Raw -Encoding UTF8 | ConvertFrom-Json
        try { Sync-Workspace $feed; $run['workspace_error']=$null } catch {
            $run['workspace_error']=$_.Exception.Message
            if(-not (IsBusy $_.Exception)) { Write-Warning ('组合选择等待重试：'+$_.Exception.Message) }
            try { $book.Worksheets.Item('组合对比').Range('A17').Formula='组合读取暂未完成；正在重试，详情见启动终端' } catch {}
        }
        if ($producer -and $producer.HasExited -and (-not $Once -or $feed.ready -eq $false)) { throw (ProducerFailure) }
        if ($feed.ready -ne $false -and -not $initialReady) {
            Write-Output '完整计算结果已就绪，正在写入 Excel。'
            $initialReady = $true
        }
        if (-not $initialReady -and (Get-Date) -gt $deadline) { throw "首次完整计算超过600秒，当前结果保留。日志：$runRoot" }
        $run.feed_generated_at = $feed.generated_at
        $run.ready = ($feed.ready -ne $false)
        $run.runtime = $feed.runtime
        $run.evidence = $feed.evidence
        $run.calculation_completed_at = $feed.calculation_completed_at
        if ($feed.generated_at -ne $last -or (Get-Date) -ge $nextStatusWrite) {
            if ($feed.schema_version -ne 1) { throw '不支持的数据格式' }
            try {
                $changed = @{}
                foreach ($property in $feed.sheets.PSObject.Properties) {
                    $revision = SheetRevision $feed $property.Name
                    if ($revisions[$property.Name] -ne $revision) { $changed[$property.Name] = $revision }
                }
                $writeStatus = $script:workspaceChanged -or $changed.Count -gt 0 -or $lastMode -ne $feed.mode -or $lastReady -ne ($feed.ready -ne $false) -or (Get-Date) -ge $nextStatusWrite
                if ($writeStatus) { $excel.ScreenUpdating = $false }
                foreach ($property in $feed.sheets.PSObject.Properties) {
                    if (-not $changed.ContainsKey($property.Name)) { continue }
                    $sheet = $book.Worksheets.Item($property.Name)
                    $rows = $property.Value; $columns = $feed.headers.($property.Name).Length
                    if ($counts.ContainsKey($property.Name) -and $counts[$property.Name] -gt $rows.Count) {
                        $sheet.Range($sheet.Cells.Item(7,1),$sheet.Cells.Item(6+$counts[$property.Name],$columns)).ClearContents()
                    }
                    if ($rows.Count) {
                        $matrixRows=[Math]::Max(2,$rows.Count)
                        $matrix = New-Object 'object[,]' $matrixRows,$columns
                        for ($r=0; $r -lt $rows.Count; $r++) {
                            for ($c=0; $c -lt $columns; $c++) {
                                $value = $rows[$r][$c]
                                if ($value -is [ValueType]) { $value = [double]$value }
                                elseif ($value -is [string] -and $value.StartsWith('=')) { $value = "'" + $value }
                                $matrix[$r,$c] = $value
                            }
                        }
                        # Keep Value2 exclusively for SAFEARRAYs. Scalar status
                        # strings below use Formula to avoid COM type caching.
                        $target=$sheet.Range($sheet.Cells.Item(7,1),$sheet.Cells.Item(6+$matrixRows,$columns))
                        $target.Value2=$matrix
                    }
                    $counts[$property.Name] = $rows.Count
                }
                if ($writeStatus) {
                    $calculated = if ($feed.calculation_completed_at) { $feed.calculation_completed_at } else { $feed.generated_at }
                    $source = if ($feed.evidence) { (Beijing $feed.evidence.oldest_source_time) + ' 至 ' + (Beijing $feed.evidence.newest_source_time) } else { '以逐行数据时间为准' }
                    $note = if ($feed.evidence) { [string]$feed.evidence.note } else { '未提供行情变化证据' }
                    foreach ($sheet in $book.Worksheets) {
                        if ($sheet.Name -in @('概览','指标','组合对比')) { continue }
                        $sheet.Range('A3').Formula = [string]$feed.mode + ' · ' + $note
                        $sheet.Range('A4').Formula = if ($feed.ready -eq $false) { '四档计算中，尚未全部就绪 · 原始数据：' + $source } else { '计算完成（北京）：' + (Beijing $calculated) + ' · 原始数据：' + $source }
                        $sheet.Range('A5').Formula = '运行 ' + $runId.Substring(0,8) + ' · 检查 ' + (Beijing ([DateTimeOffset]::Now.ToString('o'))) + ' · 仅启动器窗口持续更新；重开文件为快照'
                    }
                    $compactMode=if($feed.ready -eq $false){'计算中'}elseif($feed.acquisition -like '*快照*'){'历史回看'}elseif($ReadOnlyCache){'只读缓存'}elseif($feed.acquisition -like '*时段守卫*'){'保存数据'}elseif($feed.collector -eq 'running'){'采集中'}else{'缓存 · 未采集'}
                    $compactNote=if($feed.ready -eq $false){'四档计算中'}elseif($feed.evidence.display_inputs_changed -eq $true){'源时 / 报价变化'}elseif($feed.evidence.display_inputs_changed -eq $false){'源时 / 报价未变'}else{'数据时间见各卡片'}
                    Set-ViewState $compactMode $compactNote ('维护中 · '+$runId.Substring(0,8)+' · '+(Split-Path $Output -Leaf)) ('计算 '+(Beijing $calculated)+' · 写入 '+(Get-Date -Format 'HH:mm:ss')+' · 上次保存 '+(Beijing $run.last_save_at))
                    $book.Worksheets.Item('概览').Calculate()
                    $book.Worksheets.Item('指标').Calculate()
                    $run.last_write_at = [DateTimeOffset]::Now.ToString('o'); $run.writes++
                    $s = $book.Worksheets.Item('数字看板')
                    $actual = @($s.Range('D7').Value2,$s.Range('E7').Value2,$s.Range('J7').Value2,$s.Range('L7').Value2)
                    if ($feed.sheets.'数字看板'.Count -gt 0) {
                        $expected = @($feed.sheets.'数字看板'[0][3],$feed.sheets.'数字看板'[0][4],$feed.sheets.'数字看板'[0][9],$feed.sheets.'数字看板'[0][11])
                        for ($i=0; $i -lt 4; $i++) {
                            if ($null -eq $expected[$i]) { if ($null -ne $actual[$i]) { throw '单元格回读不符：缺失未清空' } }
                            elseif ([Math]::Abs([double]$expected[$i]-[double]$actual[$i]) -gt 0.0000001) { throw '单元格回读不符' }
                        }
                    }
                    $run.observed = [ordered]@{ full_name=$book.FullName; hwnd=$run.hwnd; cells=$actual;
                        status=$s.Range('A3').Value2; times=$s.Range('A4').Value2; identity=$s.Range('A5').Value2 }
                    # A COM Save can display a modal dialog even with alerts off.
                    # Publish the pending stage BEFORE entering that blocking call.
                    $run.state='saving'; SaveRun
                    $book.Save()
                    $script:workspaceChanged=$false
                    $run.last_save_at = [DateTimeOffset]::Now.ToString('o'); $run.saves++
                    $excel.StatusBar='Delta1 '+$runId.Substring(0,8)+' · 保存成功 '+(Get-Date -Format 'HH:mm:ss')+' · 行情时间见卡片'
                    $run.saved_file_mtime = (Get-Item -LiteralPath $Output).LastWriteTimeUtc.ToString('o')
                    $lastSuccess = Get-Date; $nextStatusWrite = (Get-Date).AddSeconds(30)
                    foreach ($name in $changed.Keys) { $revisions[$name] = $changed[$name] }
                    $lastMode = $feed.mode; $lastReady = ($feed.ready -ne $false)
                }
                $last = $feed.generated_at; $run.state='running'; $run.error=$null
                if ($writeStatus -and $feed.ready -ne $false) {
                    $updates++
                    if ($updates -eq 1) {
                        Write-Output "Excel 首次写入成功：$Output"
                        if (-not $Once) { Write-Output '已进入持续检查；相同缓存不代表新行情，请核对原始数据时点。' }
                        $nextRefreshNotice = (Get-Date).AddSeconds(30)
                    }
                    elseif ((Get-Date) -ge $nextRefreshNotice) {
                        Write-Output ('Excel 已刷新并保存：' + $lastSuccess.ToString('HH:mm:ss') + "；累计写入 $updates 次。")
                        $nextRefreshNotice = (Get-Date).AddSeconds(30)
                    }
                }
            } catch {
                $run.state='write_error'; $run.error=$_.Exception.Message; SaveRun
                if (-not (IsBusy $_.Exception)) { throw }
                Write-Warning 'Excel 正在编辑、忙碌或保存失败；未确认成功，保留运行并重试。'
                Start-Sleep -Milliseconds 1000; continue
            } finally { try { $excel.ScreenUpdating = $true } catch {} }
        }
        if ((Get-Date) -ge $nextHeartbeat) { SaveRun; $nextHeartbeat=(Get-Date).AddSeconds(2) }
        if (($Once -and $initialReady) -or ($MaxUpdates -gt 0 -and $updates -ge $MaxUpdates)) { break }
        if (-not $initialReady -and (Get-Date) -ge $nextProgress) {
            $message = '首次计算中，尚未完成四个档位'
            if (Test-Path -LiteralPath $statusFile) {
                $progress = Get-Content -LiteralPath $statusFile -Raw -Encoding UTF8 | ConvertFrom-Json
                $elapsed = [int]($progress.elapsed_seconds + ([DateTimeOffset]::Now - [DateTimeOffset]::Parse($progress.updated_at)).TotalSeconds)
                $message = [string]$progress.message + " · 累计 $elapsed 秒"
                if ($progress.message -ne $lastProgress -or (Get-Date) -ge $nextProgressNotice) {
                    Write-Output $message; $lastProgress = $progress.message
                    $nextProgressNotice = (Get-Date).AddSeconds(10)
                }
            }
            try {
                foreach ($sheet in $book.Worksheets) {
                    if ($sheet.Name -notin @('概览','指标','组合对比')) { $sheet.Range('A4').Formula = $message + '；空白表示待计算，关闭窗口可停止。' }
                }
                Set-ViewState '计算中' $message ('维护中 · '+$runId.Substring(0,8)) '空白表示待计算'
            } catch {
                $run.state='write_error'; $run.error=$_.Exception.Message; SaveRun
                if (-not (IsBusy $_.Exception)) { throw }
            }
            $nextProgress = (Get-Date).AddSeconds(2)
        }
        elseif ($initialReady -and $run.state -ne 'calculation_delayed' -and (([DateTimeOffset]::Now - [DateTimeOffset]::Parse($feed.generated_at)).TotalSeconds -gt 60)) {
            $run.state='calculation_delayed'; SaveRun
            try {
                foreach ($sheet in $book.Worksheets) {
                    if ($sheet.Name -notin @('概览','指标','组合对比')) { $sheet.Range('A5').Formula = '计算更新延迟 · 运行 ' + $runId.Substring(0,8) + ' · 上次计算 ' + (Beijing $feed.generated_at) + '；行情是否新鲜见原始时点。' }
                }
                Set-ViewState '更新延迟' '数据时间见各卡片' ('维护中 · '+$runId.Substring(0,8)) ('上次计算 '+(Beijing $feed.generated_at))
            } catch {
                $run.state='write_error'; $run.error=$_.Exception.Message; SaveRun
                if (-not (IsBusy $_.Exception)) { throw }
            }
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Output "Excel: $Output; updates: $updates"
} catch {
    $run.state='failed'; $run.error=$_.Exception.Message; SaveRun
    throw
} finally {
    [IO.File]::WriteAllText($stopFile,'stop')
    if ($producer -and -not $producer.HasExited) {
        if (-not $producer.WaitForExit(25000)) { Stop-Process -Id $producer.Id }
    }
    if ($book) {
        try {
            foreach ($sheet in $book.Worksheets) {
                if ($sheet.Name -notin @('概览','指标','组合对比')) { $sheet.Range('A5').Formula = '已停止自动更新 · 运行 ' + $runId.Substring(0,8) + ' · 此文件为保存快照；数据时点见逐行列' }
            }
            $endMode=if($run.state -eq 'failed'){'错误 · 已停止'}else{'已停止'}
            $endNote=if($run.state -eq 'failed'){'本次失败，详情见启动终端；数据时间见卡片'}else{'保存快照 · 数据时间见各卡片'}
            Set-ViewState $endMode $endNote ('已停止 · '+$runId.Substring(0,8)+' · '+(Split-Path $Output -Leaf)) ('上次成功保存 '+(Beijing $run.last_save_at))
            $book.Worksheets.Item('组合对比').Range('A17').Formula='已停止维护 · 此文件为快照；选择不再触发计算'
            $book.Save()
            $excel.StatusBar='Delta1 · '+$endMode+' · 此文件为保存快照'
            if ($Hidden) { $book.Close($true) }
        } catch { }
    }
    if ($excel -and $owned) {
        if ($Hidden -or -not $Once) { try { $excel.Quit() } catch { } }
        else { $excel.DisplayAlerts = $true }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
    if ($run.state -notin @('failed','cancelled')) { $run.state='stopped' }
    $run.stopped_at=[DateTimeOffset]::Now.ToString('o'); SaveRun
}
