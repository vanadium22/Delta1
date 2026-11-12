Option Explicit
Dim shell, fso, root, command, env, selfTest
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
Set env = shell.Environment("PROCESS")
env("DELTA1_DATA_ROOT") = fso.BuildPath(root, "data")
env("DELTA1_OUTPUTS_ROOT") = fso.BuildPath(root, "outputs")
env("SWHY_DELTA1_PYTHON") = fso.BuildPath(root, "runtime\python\python.exe")
env.Remove("SWHY_HISTORY_PYTHON")
env.Remove("DELTA1_APP_PYTHON")
env.Remove("DELTA1_APP_OVERLAY")
env.Remove("PYTHONPATH")
shell.CurrentDirectory = root
selfTest = False
If WScript.Arguments.Count > 0 Then selfTest = (WScript.Arguments(0) = "--self-test")
If selfTest Then
    If Not fso.FileExists(fso.BuildPath(root, "runtime\python\python.exe")) Then WScript.Quit 1
    If Not fso.FileExists(fso.BuildPath(root, "dashboard\start_presentation.vbs")) Then WScript.Quit 1
    WScript.Echo "portable launcher paths ok"
    WScript.Quit 0
End If
command = "wscript.exe //nologo """ & fso.BuildPath(root, "dashboard\start_presentation.vbs") & """"
shell.Run command, 0, False
