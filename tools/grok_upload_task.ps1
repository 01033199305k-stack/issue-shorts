# 작업 스케줄러에 「썰가챠 Grok 업로드」(3분마다 tools/grok_upload.py) 등록. 다시 실행하면 덮어쓴다.
# 지우기: Unregister-ScheduledTask -TaskName '썰가챠 Grok 업로드' -Confirm:$false
$py = (Get-Command pythonw.exe).Source
$script = Join-Path $PSScriptRoot 'grok_upload.py'
$action = New-ScheduledTaskAction -Execute $py -Argument "`"$script`""   # 창 없이. 기록: 다운로드\썰가챠\grok_upload.log
$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date) -RepetitionInterval (New-TimeSpan -Minutes 3)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopIfGoingOnBatteries -AllowStartIfOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 20) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName '썰가챠 Grok 업로드' -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Get-ScheduledTask -TaskName '썰가챠 Grok 업로드' | Select-Object TaskName, State
