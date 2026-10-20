param([Parameter(Mandatory=$true)][string]$RunFile)
# Read only: attach to the recorded native window. Never GetObject(filename),
# Workbooks.Open, Activate, Select or start another Excel instance.
$ErrorActionPreference='Stop'
[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false)
Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;
public class NumericInspect {
    public delegate bool EnumProc(IntPtr hwnd, IntPtr param);
    [DllImport("user32.dll")] public static extern bool EnumChildWindows(IntPtr hwnd, EnumProc cb, IntPtr p);
    [DllImport("user32.dll")] public static extern int GetClassName(IntPtr hwnd, StringBuilder text, int n);
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindow(IntPtr hwnd);
    [DllImport("user32.dll")] public static extern bool IsWindowEnabled(IntPtr hwnd);
    [DllImport("oleacc.dll")] public static extern int AccessibleObjectFromWindow(IntPtr hwnd, uint id, ref Guid iid, [MarshalAs(UnmanagedType.Interface)] out object obj);
    public static object Window(long hwnd, uint expectedPid) {
        uint pid; GetWindowThreadProcessId(new IntPtr(hwnd), out pid);
        if (pid != expectedPid) throw new Exception("Recorded Excel window/process no longer matches");
        object result = null;
        EnumChildWindows(new IntPtr(hwnd), (h,p) => {
            var name = new StringBuilder(256); GetClassName(h,name,256);
            if (name.ToString() == "EXCEL7") {
                Guid iid = new Guid("00020400-0000-0000-C000-000000000046"); object obj;
                if (AccessibleObjectFromWindow(h,0xFFFFFFF0,ref iid,out obj) == 0) { result=obj; return false; }
            }
            return true;
        }, IntPtr.Zero);
        if (result == null) throw new Exception("Existing Excel native document unavailable (closed, hidden or busy)");
        return result;
    }
}
'@
$result=[ordered]@{ observed_at=[DateTimeOffset]::Now.ToString('o'); attached=$false }
$native=$null; $app=$null; $book=$null
try {
    $run=Get-Content -LiteralPath $RunFile -Raw -Encoding UTF8 | ConvertFrom-Json
    $result.run_id=$run.run_id; $result.output=$run.output
    if (-not [NumericInspect]::IsWindow([IntPtr][long]$run.hwnd)) { throw 'Recorded Excel window no longer exists' }
    $result.visible=[NumericInspect]::IsWindowVisible([IntPtr][long]$run.hwnd)
    $result.window_enabled=[NumericInspect]::IsWindowEnabled([IntPtr][long]$run.hwnd)
    if (-not $result.window_enabled) { throw 'Workbook window disabled: check its Excel modal dialog; no COM call was made' }
    $native=[NumericInspect]::Window([long]$run.hwnd,[uint32]$run.excel_pid)
    $app=$native.Application
    foreach ($candidate in $app.Workbooks) {
        if ([string]::Equals($candidate.FullName,$run.output,[StringComparison]::OrdinalIgnoreCase)) { $book=$candidate; break }
    }
    if (-not $book) { throw 'Recorded workbook is not open in the recorded Excel instance' }
    $sheet=$book.Worksheets.Item('数字看板')
    $result.attached=$true; $result.full_name=$book.FullName; $result.excel_pid=$run.excel_pid
    $result.hwnd=$run.hwnd; $result.visible=[NumericInspect]::IsWindowVisible([IntPtr][long]$run.hwnd)
    $result.caption=$book.Windows.Item(1).Caption
    $result.cells=[ordered]@{}
    foreach ($address in @('A3','A4','A5','C7','D7','E7','J7','K7','L7')) { $result.cells[$address]=$sheet.Range($address).Value2 }
    $result.saved=[bool]$book.Saved
    $result.active_sheet=$app.ActiveSheet.Name; $result.selection=$app.ActiveCell.Address()
    $result.scroll_row=$book.Windows.Item(1).ScrollRow
    $result.scroll_column=$book.Windows.Item(1).ScrollColumn
    try {
        $view=$book.Worksheets.Item('概览'); $metrics=$book.Worksheets.Item('指标')
        $result.view=[ordered]@{slot=$view.Range('E3').Value2;contract=$view.Range('E6').Value2;
            future=$view.Range('B8').Value2;spot=$view.Range('D8').Value2;annual=$view.Range('H8').Value2;
            source=$view.Range('B9').Value2;state=$view.Range('G3').Value2;identity=$view.Range('B41').Value2;
            percentile=$view.Range('B15').Value2;stress=$view.Range('H10').Value2;
            metric_slot=$metrics.Range('E3').Value2;metric_efficiency=$metrics.Range('D28').Value2;
            metric_time=$metrics.Range('E28').Value2}
    } catch { $result.view_error=$_.Exception.Message }
} catch { $result.error=$_.Exception.Message; $result.hresult=$_.Exception.HResult }
finally {
    # Release references only; the launcher owns the application.
    foreach ($obj in @($book,$app,$native)) {
        if ($obj -and [Runtime.InteropServices.Marshal]::IsComObject($obj)) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($obj) }
    }
}
$result | ConvertTo-Json -Depth 8 -Compress
