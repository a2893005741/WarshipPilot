Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
shell.CurrentDirectory = root
command = "cmd.exe /d /c """ & root & "\WarshipPilot.bat"""
For Each argument In WScript.Arguments
  command = command & " """ & Replace(argument, """", """""") & """"
Next
shell.Run command, 0, False
