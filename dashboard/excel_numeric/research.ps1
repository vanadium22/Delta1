# The owned workbook is the only UI state we read. Never rewrite user's selectors
# during refresh; a changed request clears values before publishing the request.
$script:researchPages=[ordered]@{basis='期现';calendar='同品种跨期';cross='跨品种'}
function Write-ResearchRows($Sheet,[int]$Row,[int]$Column,$Rows,[int]$Width) {
    if(-not $Rows.Count){return}
    $matrix=New-Object 'object[,]' ([Math]::Max(2,$Rows.Count)),$Width
    for($r=0;$r -lt $Rows.Count;$r++) {
        for($c=0;$c -lt $Width;$c++) {
            $v=$Rows[$r][$c]
            if($v -is [ValueType]){$v=[double]$v}
            elseif($v -is [string] -and $v -match '^\d{4}-\d\d-\d\dT') {
                $v=[DateTimeOffset]::Parse($v).ToOffset([TimeSpan]::FromHours(8)).DateTime.ToOADate()
            }elseif($v -is [string] -and $v.StartsWith('=')){$v="'"+$v}
            # Unwrap PowerShell's JSON string wrapper before COM SAFEARRAY
            # marshalling; Excel otherwise reports E_OUTOFMEMORY on strings.
            if($v -is [string]){$matrix[$r,$c]=[string]$v}else{$matrix[$r,$c]=$v}
        }
    }
    $Sheet.Range($Sheet.Cells.Item($Row,$Column),$Sheet.Cells.Item($Row+[Math]::Max(2,$Rows.Count)-1,$Column+$Width-1)).Value2=$matrix
}
function Read-ResearchChoice($Sheet) {
    return [ordered]@{
        variant_id=[string]$Sheet.Range('B3').Value2;scope=[string]$Sheet.Range('E3').Value2
        root=[string]$Sheet.Range('H3').Value2;left=[string]$Sheet.Range('K3').Value2;right=[string]$Sheet.Range('N3').Value2
        timing=[string]$Sheet.Range('B4').Value2;date=[string]$Sheet.Range('E4').Value2
        expiry_mode=[string]$Sheet.Range('H4').Value2;offset=$Sheet.Range('K4').Value2;limit=$Sheet.Range('N4').Value2
        participation=$Sheet.Range('B8').Value2
    }
}
function Sync-Workspace($Feed) {
    if(-not $Feed.research){return}
    # A previous daily result may be shown during startup. Its saved selection
    # must not replace newer preferences before the fresh producer is ready.
    if($Feed.ready -eq $false -and -not $script:researchInitialized){return}
    $w=$Feed.research;$screenBefore=$excel.ScreenUpdating
    try {
        if(-not $script:researchInitialized) {
            $excel.ScreenUpdating=$false
            foreach($id in $script:researchPages.Keys) {
                $s=$book.Worksheets.Item($script:researchPages[$id]);$choice=$w.selection.pages.$id
                if($choice) {
                    foreach($entry in @(@('B3','variant_id'),@('E3','scope'),@('H3','root'),@('K3','left'),@('N3','right'),@('B4','timing'),@('E4','date'),@('H4','expiry_mode'),@('K4','offset'),@('N4','limit'),@('B8','participation'))) {
                        if($null -ne $choice.($entry[1])){$s.Range($entry[0]).Formula=[string]$choice.($entry[1])}
                    }
                }
            }
            if($w.selection.active_page -in @($script:researchPages.Keys)) {
                $script:researchActive=[string]$w.selection.active_page
                [void]$book.Worksheets.Item($script:researchPages[$script:researchActive]).Activate()
            }
            $options=@(@($w.contracts)+@('000300.SH','000016.SH','000905.SH','000852.SH') | Select-Object -Unique | ForEach-Object {,@($_)})
            Write-ResearchRows ($book.Worksheets.Item('合约选项')) 7 1 $options 1
            foreach($name in $script:researchPages.Values) {
                $s=$book.Worksheets.Item($name)
                foreach($cell in @('K3','N3')) {
                    $s.Range($cell).Validation.Delete()
                    $s.Range($cell).Validation.Add(3,1,1,'=INDIRECT("''合约选项''!A7:A606")')
                }
            }
            $script:researchInitialized=$true
        }
        $active='basis'
        foreach($id in $script:researchPages.Keys){if($book.ActiveSheet.Name -eq $script:researchPages[$id]){$active=$id}}
        # Source/status/hidden-sheet focus does not silently change research page.
        if($book.ActiveSheet.Name -notin @($script:researchPages.Values) -and $script:researchActive){$active=$script:researchActive}
        $script:researchActive=$active
        $pages=[ordered]@{}
        foreach($id in $script:researchPages.Keys){$pages[$id]=Read-ResearchChoice ($book.Worksheets.Item($script:researchPages[$id]))}
        $selection=[ordered]@{active_page=$active;pages=$pages}
        $signature=ConvertTo-Json -InputObject $selection -Depth 12 -Compress
        if($Once) {
            $script:researchSignature=$signature;$script:researchRequest=$w.request_id
        }elseif($signature -ne $script:researchSignature) {
            $excel.ScreenUpdating=$false
            $script:researchSignature=$signature;$script:researchRequest=[guid]::NewGuid().ToString('N')
            $selection.request_id=$script:researchRequest
            $tmp=$selectionFile+'.tmp'
            [IO.File]::WriteAllText($tmp,($selection | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false))
            Move-Item -LiteralPath $tmp -Destination $selectionFile -Force
            foreach($name in $script:researchPages.Values) {
                $s=$book.Worksheets.Item($name);$s.Range('G13:Q266').ClearContents();$s.Range('A280:K1800').ClearContents()
                $s.Range('A9').Formula='正在计算所选变体；旧请求结果不会回填'
            }
            $script:researchRendered=$null;$script:workspaceChanged=$true
        }
        if($w.request_id -ne $script:researchRequest){return}
        $revision=ConvertTo-Json -InputObject $w.excel_pages -Depth 35 -Compress
        if($revision -eq $script:researchRendered){return}
        $excel.ScreenUpdating=$false
        foreach($id in $script:researchPages.Keys) {
            $p=$w.excel_pages.$id;if(-not $p){continue}
            $s=$book.Worksheets.Item($script:researchPages[$id])
            $s.Range('A13:E266').ClearContents();$s.Range('G13:Q266').ClearContents();$s.Range('A280:K1800').ClearContents()
            Write-ResearchRows $s 13 1 $p.directory 5
            Write-ResearchRows $s 13 7 $p.entities 11
            Write-ResearchRows $s 280 1 $p.details 11
            if($p.details.Count -gt 0) {
                [void]$s.Range('A280:K'+[string](279+$p.details.Count)).Rows.AutoFit()
            }
            $s.Range('A9').Formula=[string]$p.status
        }
        $script:researchRendered=$revision;$script:workspaceChanged=$true
    }finally{$excel.ScreenUpdating=$screenBefore}
}
