param(
    [string]$Python = 'python', [string]$Output, [string]$LocalRoot,
    [string]$Snapshot, [string]$FeedFile, [switch]$ReadOnlyCache,
    [switch]$Once, [switch]$Hidden, [int]$MaxUpdates = 0
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
try {
    if (-not $FeedFile) {
        $FeedFile = Join-Path $runRoot 'workbook.json'
        $arguments = @('-B','-X','utf8','-m','dashboard.numeric_excel','--feed',$FeedFile,'--stop-file',$stopFile)
        if ($LocalRoot) { $arguments += @('--local-root',[IO.Path]::GetFullPath($LocalRoot)) }
        if ($Snapshot) { $arguments += @('--snapshot',[IO.Path]::GetFullPath($Snapshot)); $Once = $true }
        elseif (-not $ReadOnlyCache) { $arguments += '--collect' }
        if ($Once) { $arguments += @('--iterations','1') }
        # Native process arguments, never a shell command.
        $quoted = $arguments | ForEach-Object { if ($_ -match '"') { throw '参数不得含双引号' }; '"' + $_ + '"' }
        $producer = Start-Process -FilePath $Python -ArgumentList $quoted -WorkingDirectory $projectRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $runRoot 'producer.out.log') -RedirectStandardError (Join-Path $runRoot 'producer.err.log')
    }
    Write-Output '正在读取本地历史和行情缓存。首次加载分钟指标较慢；已有每日缓存时先展示上次结果。'
    $deadline = (Get-Date).AddSeconds(600)
    while (-not (Test-Path -LiteralPath $FeedFile)) {
        if ($producer -and $producer.HasExited) { throw "数据服务退出，检查 $runRoot\producer.err.log" }
        if ((Get-Date) -gt $deadline) { throw '等待本地历史计算超时。' }
        Start-Sleep -Milliseconds 300
    }
    Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'template.xlsx') -Destination $Output
    # Own a separate Excel instance; never attach to user workbooks.
    $excel = New-Object -ComObject Excel.Application
    $owned = $true; $excel.Visible = -not $Hidden; $excel.DisplayAlerts = $false
    $book = $excel.Workbooks.Open($Output)
    $last = ''; $updates = 0; $counts = @{}; $lastSuccess = Get-Date
    while ($true) {
        try { $open = $book.Name } catch { break }
        if (-not $open) { break }
        if ($producer -and $producer.HasExited -and -not $Once) { throw "数据服务已停止，最后结果保留。检查 $runRoot\producer.err.log" }
        $feed = Get-Content -LiteralPath $FeedFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($feed.generated_at -ne $last) {
            if ($feed.schema_version -ne 1) { throw '不支持的数据格式' }
            $excel.ScreenUpdating = $false
            try {
                foreach ($property in $feed.sheets.PSObject.Properties) {
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
                    $sheet.Range('A3').Formula = [string]$feed.mode
                    $sheet.Range('A4').Formula = '已更新（北京）：' + ([DateTimeOffset]::Parse($feed.generated_at).ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd HH:mm:ss')) + ' · 关闭窗口即停止；重开文件仅为保存快照'
                }
                $book.Save(); $last = $feed.generated_at; $lastSuccess = Get-Date; $updates++
            } finally { $excel.ScreenUpdating = $true }
        }
        if ($Once -or ($MaxUpdates -gt 0 -and $updates -ge $MaxUpdates)) { break }
        if (((Get-Date)-$lastSuccess).TotalSeconds -gt 30) {
            foreach ($sheet in $book.Worksheets) { $sheet.Range('A4').Formula = '更新延迟：最后成功写入 ' + $lastSuccess.ToString('yyyy-MM-dd HH:mm:ss') + '；请检查数据服务。' }
        }
        Start-Sleep -Milliseconds 500
    }
    Write-Output "Excel: $Output; updates: $updates"
} finally {
    [IO.File]::WriteAllText($stopFile,'stop')
    if ($producer -and -not $producer.HasExited) {
        if (-not $producer.WaitForExit(25000)) { Stop-Process -Id $producer.Id }
    }
    if ($book) {
        try {
            foreach ($sheet in $book.Worksheets) { $sheet.Range('A4').Formula = '已停止自动更新 · 保存时点（北京） ' + ([DateTimeOffset]::Now.ToOffset([TimeSpan]::FromHours(8)).ToString('yyyy-MM-dd HH:mm:ss')) + ' · 数据时点见逐行列' }
            $book.Save()
            if ($Hidden) { $book.Close($true) }
        } catch { }
    }
    if ($excel -and $owned) {
        if ($Hidden -or -not $Once) { try { $excel.Quit() } catch { } }
        else { $excel.DisplayAlerts = $true }
        [void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)
    }
}
