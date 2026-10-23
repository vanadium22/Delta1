Option Explicit
Dim shell, fso, script, command, arg
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
script = fso.BuildPath(fso.GetParentFolderName(WScript.ScriptFullName), "start_app.ps1")
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -WindowStyle Hidden -ExecutionPolicy Bypass -File """ & script & """ -Edition presentation"
For Each arg In WScript.Arguments
    command = command & " """ & Replace(arg, """", """""") & """"
Next
shell.Run command, 0, False
