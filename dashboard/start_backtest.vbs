Option Explicit
Dim shell, filesystem, folder, command
Set shell = CreateObject("WScript.Shell")
Set filesystem = CreateObject("Scripting.FileSystemObject")
folder = filesystem.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & folder & "\start_backtest.ps1"""
shell.Run command, 0, False
