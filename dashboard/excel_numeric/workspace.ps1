# User-editable cells are read only here. Results never overwrite selections.
function Write-WorkspaceRows($Sheet, [int]$Row, [int]$Column, $Rows, [int]$Width) {
    if(-not $Rows.Count) { return }
    $matrix=New-Object 'object[,]' ([Math]::Max(2,$Rows.Count)),$Width
    for($r=0;$r -lt $Rows.Count;$r++) {
        for($c=0;$c -lt $Width;$c++) {
            $v=$Rows[$r][$c]
            if($v -is [ValueType]) {$v=[double]$v}
            elseif($v -is [string] -and $v -match '^\d{4}-\d\d-\d\dT') {
                $v=[DateTimeOffset]::Parse($v).ToOffset([TimeSpan]::FromHours(8)).DateTime.ToOADate()
            } elseif($v -is [string] -and $v.StartsWith('=')) {$v="'"+$v}
            if($v -is [string]) { $matrix[$r,$c]=[string]$v }
            else { $matrix[$r,$c]=$v }
        }
    }
    $Sheet.Range($Sheet.Cells.Item($Row,$Column),$Sheet.Cells.Item($Row+[Math]::Max(2,$Rows.Count)-1,$Column+$Width-1)).Value2=$matrix
}
function Sync-Workspace($Feed) {
    if(-not $Feed.workspace) { return }
    $screenBefore=$excel.ScreenUpdating
    $screenChanged=$false
    try {
    $w=$Feed.workspace
    $sheet=$book.Worksheets.Item('组合对比')
    if(-not $script:workspaceInitialized) {
        $excel.ScreenUpdating=$false;$screenChanged=$true
        $values=@()
        foreach($r in $w.selection.rows) {
            $values+=,@($r.category,$r.left,$r.right,$r.input,$r.timing,$r.date)
        }
        Write-WorkspaceRows $sheet 7 1 $values 6
        if($w.selection.group){$sheet.Range('B3').Formula=[string]$w.selection.group}
        if($w.selection.detail_row){$sheet.Range('E3').Formula=[string]$w.selection.detail_row}
        $options=@(@($w.active)+@($w.contracts)+@('000300.SH','000016.SH','000905.SH','000852.SH') | Select-Object -Unique | ForEach-Object {,@($_)})
        Write-WorkspaceRows ($book.Worksheets.Item('合约选项')) 7 1 $options 1
        $sheet.Range('B7:C14').Validation.Delete()
        $sheet.Range('B7:C14').Validation.Add(3,1,1,'=INDIRECT("''合约选项''!A7:A606")')
        $script:workspaceInitialized=$true
    }
    $cells=$sheet.Range('A7:F14').Value2
    $rows=@()
    for($r=1;$r -le 8;$r++) {
        $rows+= [ordered]@{category=[string]$cells[$r,1];left=[string]$cells[$r,2];right=[string]$cells[$r,3];
            input=[string]$cells[$r,4];timing=[string]$cells[$r,5];date=[string]$cells[$r,6]}
    }
    $selection=[ordered]@{rows=$rows;group=[string]$sheet.Range('B3').Value2;detail_row=$sheet.Range('E3').Value2}
    $signature=ConvertTo-Json -InputObject $selection -Depth 8 -Compress
    if($Once) {
        $script:workspaceSignature=$signature
        $script:workspaceRequest=$w.request_id
    } elseif($signature -ne $script:workspaceSignature) {
        $excel.ScreenUpdating=$false;$screenChanged=$true
        $script:workspaceSignature=$signature
        $script:workspaceRequest=[guid]::NewGuid().ToString('N')
        $selection.request_id=$script:workspaceRequest
        $tmp=$selectionFile+'.tmp'
        [IO.File]::WriteAllText($tmp,($selection | ConvertTo-Json -Depth 8),[Text.UTF8Encoding]::new($false))
        Move-Item -LiteralPath $tmp -Destination $selectionFile -Force
        $sheet.Range('G7:P14').ClearContents();$sheet.Range('A20:I99').ClearContents()
        $sheet.Range('A17').Formula='正在计算所选组合；日终值不会冒充盘中值'
        $script:workspaceRendered=$null
    }
    if($w.request_id -eq $script:workspaceRequest) {
        $revision=ConvertTo-Json -InputObject @($w.comparisons,$w.details) -Depth 20 -Compress
        if($revision -ne $script:workspaceRendered) {
            $excel.ScreenUpdating=$false;$screenChanged=$true
            $sheet.Range('G7:P14').ClearContents();$sheet.Range('A20:I99').ClearContents()
            Write-WorkspaceRows $sheet 7 7 $w.comparisons 10
            Write-WorkspaceRows $sheet 20 1 $w.details 9
            $sheet.Range('A17').Formula='第 '+[string]$w.selection.detail_row+' 组 · '+[string]$w.selection.group+' · 盘中 / 日终分别列示'
            $script:workspaceRendered=$revision
            $script:workspaceChanged=$true
        }
    }
    } finally {
        if($screenChanged){$excel.ScreenUpdating=$screenBefore}
    }
}
