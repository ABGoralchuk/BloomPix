On Error Resume Next

Dim fso, shell, scriptDir, projectDir, desktopDir, shortcutPath, shortcut
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
projectDir = fso.GetParentFolderName(scriptDir)
desktopDir = shell.SpecialFolders("Desktop")

If desktopDir <> "" Then
    shortcutPath = fso.BuildPath(desktopDir, "BloomPix.lnk")
    Set shortcut = shell.CreateShortcut(shortcutPath)
    shortcut.TargetPath = fso.BuildPath(projectDir, "BloomPix_Start.bat")
    shortcut.WorkingDirectory = projectDir
    shortcut.IconLocation = fso.BuildPath(projectDir, "assets\bloompix.ico") & ", 0"
    shortcut.Description = "Launch BloomPix SEM Fat-Bloom Analyzer"
    shortcut.Save
End If
