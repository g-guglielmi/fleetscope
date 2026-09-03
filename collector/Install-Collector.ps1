#requires -Version 5.1
<#
    Installs the FleetScope collector as a scheduled task that runs
    Invoke-FleetScopeCollection on an interval.

    Usage (elevated):
        .\Install-Collector.ps1 -ConfigPath 'C:\ProgramData\FleetScope\config.json' -IntervalHours 6
#>
[CmdletBinding()]
param(
    [string]$ConfigPath = 'C:\ProgramData\FleetScope\config.json',
    [int]$IntervalHours = 6,
    [string]$TaskName = 'FleetScopeCollector'
)

$ErrorActionPreference = 'Stop'
$moduleSource = Join-Path $PSScriptRoot 'FleetScopeCollector.psm1'
$installDir = 'C:\Program Files\FleetScope'

New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item $moduleSource -Destination $installDir -Force

if (-not (Test-Path $ConfigPath)) {
    Write-Warning "Config not found at $ConfigPath. Copy config.example.json there and fill in the token."
}

$modulePath = Join-Path $installDir 'FleetScopeCollector.psm1'
$command = "Import-Module '$modulePath'; Invoke-FleetScopeCollection -ConfigPath '$ConfigPath'"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$command`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)
$principal = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd

Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger `
    -Principal $principal -Settings $settings -Force | Out-Null

Write-Host "Installed scheduled task '$TaskName' (every $IntervalHours h). Config: $ConfigPath"
