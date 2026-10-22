
# The owned workbook is the UI. Choice changes clear old results before publishing.
$script:researchPages=[ordered]@{basis='期现';calendar='同品种跨期';cross='跨品种'}
$script:researchScopes=@{representatives='默认代表';all='全部合约';history='历史合约';specified='指定合约'}
$script:researchExpiry=@{same='相同到期';all='全部期限';mixed='不同到期'}
$script:researchLastInput=@{}
$script:researchChoiceKeys=@{}
$script:researchValidationKeys=@{}
function Write-ResearchRows($Sheet,[int]$Row,[int]$Column,$Rows,[int]$Width) {
    if(-not $Rows.Count){return}
    $matrix=New-Object 'object[,]' ([Math]::Max(2,$Rows.Count)),$Width
    for($r=0;$r -lt $Rows.Count;$r++) {for($c=0;$c -lt $Width;$c++) {
        $v=$Rows[$r][$c]
        if($v -is [ValueType]){$v=[double]$v}
        elseif($v -is [string] -and $v -match '^\d{4}-\d\d-\d\dT') {$v=[DateTimeOffset]::Parse($v).ToOffset([TimeSpan]::FromHours(8)).DateTime.ToOADate()}
        elseif($v -is [string] -and $v.StartsWith('=')){$v="'"+$v}
        if($v -is [string]){$matrix[$r,$c]=[string]$v}else{$matrix[$r,$c]=$v}
    }}
    $Sheet.Range($Sheet.Cells.Item($Row,$Column),$Sheet.Cells.Item($Row+[Math]::Max(2,$Rows.Count)-1,$Column+$Width-1)).Value2=$matrix
}
function Research-Code($Map,$Value,$Default) {
    if($Map.ContainsKey([string]$Value)){return [string]$Value}
    foreach($key in $Map.Keys){if($Map[$key] -eq $Value){return $key}}
    return $Default
}
function Set-ResearchChoice($Sheet,$Detail,$Choice,$Controls) {
    $variant=@($Controls.variants | Where-Object {$_.variant_id -eq $Choice.variant_id})[0]
    if(-not $variant -and $Choice.family_id){
        $family=@($Controls.families | Where-Object {$_.family_id -eq $Choice.family_id})[0]
        $option=@($Controls.inputs | Where-Object {$_.input_id -eq $Choice.input})[0]
        if($family){$Sheet.Range('B3').Formula=[string]$family.label}
        if($option.advanced){$Sheet.Range('E3').Formula='更多口径';$Detail.Range('B7').Formula=[string]$option.label}
        elseif($option){$Sheet.Range('E3').Formula=[string]$option.label}
        elseif($Choice.input){$Sheet.Range('E3').Formula=[string]$Choice.input}
    }
    if($variant) {
        $Sheet.Range('B3').Formula=[string]$variant.family_label
        $option=@($Controls.inputs | Where-Object {$_.input_id -eq $variant.input_id})[0]
        if($variant.input_id -eq 'fixed'){$Sheet.Range('E3').Formula='固定口径'}
        elseif($option.advanced){$Sheet.Range('E3').Formula='更多口径';$Detail.Range('B7').Formula=[string]$option.label}
        else {$Sheet.Range('E3').Formula=[string]$variant.input_label}
    }
    foreach($entry in @(@('B4','timing'))) {if($null -ne $Choice.($entry[1])){$Sheet.Range($entry[0]).Formula=[string]$Choice.($entry[1])}}
    if($Choice.scope){$Sheet.Range('E4').Formula=[string]$script:researchScopes[[string]$Choice.scope]}
    foreach($entry in @(@('B3','root'),@('E3','left'),@('H3','right'),@('B4','date'),@('H4','offset'),@('B5','limit'),@('E5','participation'))) {
        if($null -ne $Choice.($entry[1])){$Detail.Range($entry[0]).Formula=[string]$Choice.($entry[1])}
    }
    if($Choice.expiry_mode){$Detail.Range('E4').Formula=[string]$script:researchExpiry[[string]$Choice.expiry_mode]}
    if(-not $Choice.root -and $Choice.product){$Detail.Range('B3').Formula=[string]$Choice.product}
    if($Choice.limit -gt 24){$Detail.Range('B5').Formula='24'}
}
function Read-ResearchChoice($Sheet,$Detail,$Controls,$Page) {
    $familyText=[string]$Sheet.Range('B3').Value2;$inputText=[string]$Sheet.Range('E3').Value2
    # Stable IDs pasted from older B3 selectors migrate to their Chinese family/input.
    $legacy=@($Controls.variants | Where-Object {$_.variant_id -eq $familyText})[0]
    if($legacy){Set-ResearchChoice $Sheet $Detail $legacy $Controls;$familyText=[string]$legacy.family_label;$inputText=[string]$Sheet.Range('E3').Value2}
    $family=@($Controls.families | Where-Object {$_.label -eq $familyText -or $_.family_id -eq $familyText -or $familyText -in @($_.legacy_labels)})[0]
    if($family -and $family.label -ne $familyText){$Sheet.Range('B3').Formula=[string]$family.label}
    if($family -and $script:researchValidationKeys[$Page] -ne $family.family_id){
        $available=@($Controls.inputs | Where-Object {$_.input_id -in @($family.input_ids)})
        $labels=@($available | Where-Object {-not $_.advanced} | ForEach-Object {$_.label})
        if($family.fixed){$labels=@('固定口径')}
        $advanced=@($available | Where-Object {$_.advanced})
        if($advanced.Count){$labels+=,'更多口径';$Detail.Range('B7').Validation.Delete();$Detail.Range('B7').Validation.Add(3,1,1,($advanced.label -join ','))}
        if($labels.Count){$Sheet.Range('E3').Validation.Delete();$Sheet.Range('E3').Validation.Add(3,1,1,($labels -join ','))}
        $script:researchValidationKeys[$Page]=[string]$family.family_id
    }
    if($family.fixed){
        if($inputText -and $inputText -notlike '固定口径*'){$script:researchLastInput[$Page]=$inputText}
        $inputText='固定口径';$Sheet.Range('E3').Formula=$inputText
    }elseif($inputText -eq '固定口径'){
        $inputText=if($script:researchLastInput[$Page]){$script:researchLastInput[$Page]}else{[string](@($Controls.inputs | Where-Object {$_.input_id -eq 'basis'})[0].label)}
        $Sheet.Range('E3').Formula=$inputText
    }
    $inputValue=if($inputText -eq '更多口径'){[string]$Detail.Range('B7').Value2}else{$inputText}
    $option=@($Controls.inputs | Where-Object {$_.label -eq $inputValue -or $_.input_id -eq $inputValue -or $inputValue -in @($_.legacy_labels)})[0]
    if($option -and -not $family.fixed){
        if($option.advanced){$Sheet.Range('E3').Formula='更多口径';$Detail.Range('B7').Formula=[string]$option.label}
        else{$Sheet.Range('E3').Formula=[string]$option.label}
    }
    $inputId=if($family.fixed){'fixed'}elseif($option){[string]$option.input_id}else{$inputValue}
    $variant=@($Controls.variants | Where-Object {$_.family_id -eq $family.family_id -and $_.input_id -eq $inputId})[0]
    $choice=[ordered]@{family_id=if($family){[string]$family.family_id}else{$familyText};input=$inputId;variant_id=$null;
        scope=(Research-Code $script:researchScopes ([string]$Sheet.Range('E4').Value2) 'representatives');
        timing=[string]$Sheet.Range('B4').Value2;root=[string]$Detail.Range('B3').Value2;
        left=[string]$Detail.Range('E3').Value2;right=[string]$Detail.Range('H3').Value2;
        date=[string]$Detail.Range('B4').Value2;expiry_mode=(Research-Code $script:researchExpiry ([string]$Detail.Range('E4').Value2) 'all');
        offset=$Detail.Range('H4').Value2;limit=[Math]::Min(24,[Math]::Max(1,[int]$Detail.Range('B5').Value2));participation=$Detail.Range('E5').Value2}
    if($Detail.Range('B5').Value2 -ne $choice.limit){$Detail.Range('B5').Formula=[string]$choice.limit}
    if($variant){$choice.variant_id=[string]$variant.variant_id}else{$choice.selection_error='此指标不适用当前输入，请选择适用口径。'}
    $key=@($choice.family_id,$choice.input,$choice.scope,$choice.root,$choice.left,$choice.right,$choice.date,$choice.timing,$choice.expiry_mode) -join '|'
    if($script:researchChoiceKeys.ContainsKey($Page) -and $script:researchChoiceKeys[$Page] -ne $key){$choice.offset=0;$Detail.Range('H4').Formula='0'}
    $script:researchChoiceKeys[$Page]=$key
    return $choice
}
function Sync-Workspace($Feed) {
    if(-not $Feed.research){return}
    if($Feed.ready -eq $false -and -not $script:researchInitialized){return}
    $w=$Feed.research;$screenBefore=$excel.ScreenUpdating
    try {
        if(-not $script:researchInitialized) {
            $excel.ScreenUpdating=$false
            foreach($id in $script:researchPages.Keys) {
                $s=$book.Worksheets.Item($script:researchPages[$id]);$d=$book.Worksheets.Item($script:researchPages[$id]+'详情')
                $choice=$w.selection.pages.$id;if($choice){Set-ResearchChoice $s $d $choice $w.ui_controls.$id}
            }
            if($w.selection.active_page -in @($script:researchPages.Keys)) {
                $script:researchActive=[string]$w.selection.active_page
                [void]$book.Worksheets.Item($script:researchPages[$script:researchActive]).Activate()
            }
            $options=@(@($w.contracts)+@('000300.SH','000016.SH','000905.SH','000852.SH') | Select-Object -Unique | ForEach-Object {,@($_)})
            Write-ResearchRows ($book.Worksheets.Item('合约选项')) 7 1 $options 1
            foreach($name in $script:researchPages.Values) {foreach($cell in @('E3','H3')) {
                $range=$book.Worksheets.Item($name+'详情').Range($cell);$range.Validation.Delete();$range.Validation.Add(3,1,1,'=INDIRECT("''合约选项''!A7:A606")')
            }}
            $script:researchInitialized=$true
        }
        $active=if($script:researchActive){$script:researchActive}else{'basis'}
        foreach($id in $script:researchPages.Keys){if($book.ActiveSheet.Name -in @($script:researchPages[$id],($script:researchPages[$id]+'详情'))){$active=$id}}
        $script:researchActive=$active;$pages=[ordered]@{}
        foreach($id in $script:researchPages.Keys){$pages[$id]=Read-ResearchChoice ($book.Worksheets.Item($script:researchPages[$id])) ($book.Worksheets.Item($script:researchPages[$id]+'详情')) $w.ui_controls.$id $id}
        $selection=[ordered]@{active_page=$active;pages=$pages};$signature=ConvertTo-Json -InputObject $selection -Depth 12 -Compress
        if($Once){$script:researchSignature=$signature;$script:researchRequest=$w.request_id}
        elseif($signature -ne $script:researchSignature) {
            $excel.ScreenUpdating=$false;$script:researchRequest=[guid]::NewGuid().ToString('N');$selection.request_id=$script:researchRequest
            $tmp=$selectionFile+'.tmp';[IO.File]::WriteAllText($tmp,($selection | ConvertTo-Json -Depth 12),[Text.UTF8Encoding]::new($false));Move-Item -LiteralPath $tmp -Destination $selectionFile -Force
            $script:researchSignature=$signature
            foreach($name in $script:researchPages.Values){$s=$book.Worksheets.Item($name);$s.Range('A10:F33').ClearContents();$d=$book.Worksheets.Item($name+'详情');$start=if($name -eq '期现'){11}else{15};$d.Range('A'+$start+':K1804').ClearContents();if($start -eq 15){$d.Range('A9:H12').ClearContents()};$s.Range('A6').Formula='正在加载当前选择…'}
            $script:researchRendered=$null;$script:workspaceChanged=$true
        }
        if($w.request_id -ne $script:researchRequest){return}
        $revision=ConvertTo-Json -InputObject $w.excel_pages -Depth 35 -Compress;if($revision -eq $script:researchRendered){return}
        $excel.ScreenUpdating=$false
        foreach($id in $script:researchPages.Keys) {
            $p=$w.excel_pages.$id;if(-not $p){continue};$s=$book.Worksheets.Item($script:researchPages[$id]);$d=$book.Worksheets.Item($script:researchPages[$id]+'详情')
            $start=if($id -eq 'basis'){11}else{15}
            $s.Range('A10:F33').ClearContents();$d.Range('A'+$start+':K1804').ClearContents()
            Write-ResearchRows $s 10 1 $p.summary 6;Write-ResearchRows $d $start 1 $p.details 11
            if($p.details.Count -gt 0){[void]$d.Range('A'+$start+':K'+[string]($start-1+$p.details.Count)).Rows.AutoFit()}
            $s.Range('A6').Formula=[string]$p.status;$d.Range('A8').Formula=[string]$p.context
            if($id -ne 'basis'){foreach($item in @(@(9,'pair_construction','双腿构造'),@(10,'direction','方向与单位'),@(11,'explanation','指标意义'),@(12,'limitations','使用限制'))){
                $value=[string]$p.explanations.($item[1]);$d.Range('A'+$item[0]).Formula=if($value){[string]$item[2]+'：'+$value}else{''}
            }}
        }
        $script:researchRendered=$revision;$script:workspaceChanged=$true
    }finally{$excel.ScreenUpdating=$screenBefore}
}
