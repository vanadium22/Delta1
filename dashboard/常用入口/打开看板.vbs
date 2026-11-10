Option Explicit
Dim shell, fso, dashboard, script, command, arg
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
dashboard = fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName))
script = fso.BuildPath(dashboard, "start_app.ps1")
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & script & """ -Edition presentation"
For Each arg In WScript.Arguments
    command = command & " """ & Replace(arg, """", """""") & """"
Next
shell.Run command, 0, False
