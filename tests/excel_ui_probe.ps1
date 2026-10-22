param([string]$Root,[string]$Work)
$ErrorActionPreference='Stop'
$excel=$null;$book=$null;$Once=$false;$selectionFile=Join-Path $Work 'selection.json'
try {
 . (Join-Path $Root 'dashboard/excel_numeric/research.ps1')
 $excel=New-Object -ComObject Excel.Application
 $excel.DisplayAlerts=$false;$excel.Visible=$false
 $target=Join-Path $Work 'verified.xlsx'
 Copy-Item -LiteralPath (Join-Path $Root 'dashboard/excel_numeric/template.xlsx') -Destination $target
 $book=$excel.Workbooks.Open($target)
 $book.Worksheets.Item('期现').Activate()
 $last=''
 while(-not (Test-Path (Join-Path $Work 'stop'))) {
  $file=Join-Path $Work 'command.json'
  if(Test-Path $file){
   $cmd=Get-Content $file -Raw -Encoding UTF8 | ConvertFrom-Json
   if($cmd.id -ne $last){
    $last=$cmd.id
    foreach($edit in $cmd.edits){$sheet=$book.Worksheets.Item($edit.sheet);if($null -eq $edit.value){$sheet.Range($edit.cell).ClearContents()}else{$sheet.Range($edit.cell).Formula=[string]$edit.value}}
    if($cmd.page){$book.Worksheets.Item($cmd.page).Activate()}
    $feed=Get-Content (Join-Path $Work 'feed.json') -Raw -Encoding UTF8 | ConvertFrom-Json
    Sync-Workspace $feed
    $states=[ordered]@{}
    foreach($name in $script:researchPages.Values){
     $s=$book.Worksheets.Item($name);$d=$book.Worksheets.Item($name+'详情')
     $rows=@();for($r=10;$r -le 33;$r++){$line=@();for($c=1;$c -le 6;$c++){$line+=,$s.Cells.Item($r,$c).Value2};if($null -ne $line[0]){$rows+=,$line}}
     $states[$name]=[ordered]@{family=$s.Range('B3').Value2;input=$s.Range('E3').Value2;timing=$s.Range('B4').Value2;scope=$s.Range('E4').Value2;status=$s.Range('A6').Value2;rows=$rows;p=$d.Range('E5').Value2;offset=$d.Range('H4').Value2;limit=$d.Range('B5').Value2;old_row=$s.Range('A34').Value2;detail=$d.Range('A11').Value2;nav=$s.Range('A7').Hyperlinks.Item(1).SubAddress;input_validation=$s.Range('E3').Validation.Formula1}
    }
    $book.Save()
    $response=[ordered]@{id=$cmd.id;hwnd=$excel.Hwnd;full_name=$book.FullName;visible=$excel.Visible;active_sheet=$book.ActiveSheet.Name;scroll=$book.Windows.Item(1).ScrollRow;selection=$excel.ActiveCell.Address();pages=$states;chart_count=$book.Worksheets.Item('概览').ChartObjects().Count}
    if(Test-Path $selectionFile){$response.request=Get-Content $selectionFile -Raw -Encoding UTF8 | ConvertFrom-Json}
    $json=$response|ConvertTo-Json -Depth 30
    [IO.File]::WriteAllText((Join-Path $Work ('response_'+$cmd.id+'.json')),$json,[Text.UTF8Encoding]::new($false))
   }
  }
  Start-Sleep -Milliseconds 100
 }
} catch { [IO.File]::WriteAllText((Join-Path $Work 'error.txt'),($_.Exception.ToString()+' '+$_.ScriptStackTrace));exit 1 }
finally {if($book){$book.Close($false)};if($excel){$excel.Quit();[void][Runtime.InteropServices.Marshal]::ReleaseComObject($excel)}}
