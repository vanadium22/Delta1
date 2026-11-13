Option Explicit
Dim shell, fso, root, launcher, target, icon, desktop, shortcutPath, shortcut, quiet
Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)
launcher = fso.BuildPath(root, ChrW(&H542F) & ChrW(&H52A8) & ChrW(&H770B) & ChrW(&H677F) & ".vbs")
target = fso.BuildPath(shell.ExpandEnvironmentStrings("%SystemRoot%"), "System32\wscript.exe")
icon = fso.BuildPath(root, "dashboard\assets\company_overview.ico")
If Not fso.FileExists(launcher) Or Not fso.FileExists(target) Or Not fso.FileExists(icon) Then
    WScript.Echo "Delta1 launcher or icon is missing."
    WScript.Quit 1
End If
quiet = False
If WScript.Arguments.Count = 2 Then
    If WScript.Arguments(0) = "--test-dir" Then desktop = fso.GetAbsolutePathName(WScript.Arguments(1)): quiet = True
End If
If Not quiet Then desktop = shell.SpecialFolders("Desktop")
If Not fso.FolderExists(desktop) Then WScript.Echo "Shortcut folder is unavailable.": WScript.Quit 1
shortcutPath = fso.BuildPath(desktop, "Delta1 Dashboard.lnk")
If fso.FileExists(shortcutPath) Then
    If Not quiet Then MsgBox "Delta1 Dashboard.lnk already exists; it was not changed.", 48, "Delta1"
    WScript.Quit 2
End If
Set shortcut = shell.CreateShortcut(shortcutPath)
shortcut.TargetPath = target
shortcut.Arguments = """" & launcher & """"
shortcut.WorkingDirectory = root
shortcut.IconLocation = icon & ",0"
shortcut.Description = "Delta1 dashboard"
shortcut.Save
If Not fso.FileExists(shortcutPath) Then WScript.Quit 1
If quiet Then WScript.Echo "shortcut created" Else MsgBox "Delta1 desktop shortcut created.", 64, "Delta1"
