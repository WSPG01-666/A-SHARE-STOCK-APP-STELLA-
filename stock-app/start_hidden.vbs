' STELLAR Server Auto-Start (hidden, no console window)
' Launched by Windows Task Scheduler at user logon

Set objShell = CreateObject("WScript.Shell")
Set objFSO = CreateObject("Scripting.FileSystemObject")

strProjectDir = objFSO.GetParentFolderName(WScript.ScriptFullName)
strPython = "C:\Users\鄂A陈奕迅\AppData\Local\Programs\Python\Python312\python.exe"
strApp = strProjectDir & "\app.py"

' Run hidden (0 = hidden window, False = don't wait)
objShell.Run """" & strPython & """ """ & strApp & """", 0, False

WScript.Quit 0
