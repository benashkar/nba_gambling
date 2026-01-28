# Setup Scheduled Tasks for NBA Player Props Scraper
# Run times: 6 AM, 12 PM, 4 PM CST

$batFile = "C:\Users\cashk\OneDrive\Projects\NBAGambling\run_player_props.bat"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable

# Task 1: 6 AM
$taskName1 = "NBA Player Props 6AM"
$action1 = New-ScheduledTaskAction -Execute $batFile
$trigger1 = New-ScheduledTaskTrigger -Daily -At 6:00AM

Unregister-ScheduledTask -TaskName $taskName1 -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName1 -Action $action1 -Trigger $trigger1 -Settings $settings -Description "Scrape NBA player props at 6 AM CST"
Write-Host "Created: $taskName1"

# Task 2: 12 PM
$taskName2 = "NBA Player Props 12PM"
$action2 = New-ScheduledTaskAction -Execute $batFile
$trigger2 = New-ScheduledTaskTrigger -Daily -At 12:00PM

Unregister-ScheduledTask -TaskName $taskName2 -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName2 -Action $action2 -Trigger $trigger2 -Settings $settings -Description "Scrape NBA player props at 12 PM CST"
Write-Host "Created: $taskName2"

# Task 3: 4 PM
$taskName3 = "NBA Player Props 4PM"
$action3 = New-ScheduledTaskAction -Execute $batFile
$trigger3 = New-ScheduledTaskTrigger -Daily -At 4:00PM

Unregister-ScheduledTask -TaskName $taskName3 -Confirm:$false -ErrorAction SilentlyContinue
Register-ScheduledTask -TaskName $taskName3 -Action $action3 -Trigger $trigger3 -Settings $settings -Description "Scrape NBA player props at 4 PM CST"
Write-Host "Created: $taskName3"

Write-Host ""
Write-Host "All scheduled tasks created successfully!"
Write-Host ""
Get-ScheduledTask | Where-Object {$_.TaskName -like "NBA*"} | Format-Table TaskName, State -AutoSize
