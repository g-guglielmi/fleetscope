#requires -Version 5.1
<#
    Installs the FleetScope collector as a scheduled task on a management VM.

    It runs as a DOMAIN SERVICE ACCOUNT (a gMSA is recommended) so it can reach
    the Citrix servers over Kerberos (Broker Remote SDK, WinRM, CIM). It must NOT
    run as SYSTEM — SYSTEM authenticates as the computer account and cannot query
    the other servers.

    The account needs: Citrix Delegated Admin "Read Only Administrator", and
    WinRM/remote-CIM rights on the StoreFront and license servers.

    Usage (elevated):
      gMSA (Task Scheduler fetches the managed password itself):
        .\Install-Collector.ps1 -ServiceAccount 'CONTOSO\svc-fleetscope$'
      Regular domain account (Windows needs its password to register the task):
        .\Install-Collector.ps1 -Credential (Get-Credential 'CONTOSO\svc-fleetscope')
#>
[CmdletBinding(DefaultParameterSetName = 'Gmsa')]
param(
    # gMSA, e.g. CONTOSO\svc-fleetscope$
    [Parameter(Mandatory, ParameterSetName = 'Gmsa')][string]$ServiceAccount,
    # Regular domain account + password
    [Parameter(Mandatory, ParameterSetName = 'Password')][pscredential]$Credential,
    [string]$ConfigPath = 'C:\ProgramData\FleetScope\config.json',
    [int]$IntervalHours = 6,
    [string]$TaskName = 'FleetScopeCollector'
)

if ($Credential) { $ServiceAccount = $Credential.UserName }

$ErrorActionPreference = 'Stop'
$moduleSource = Join-Path $PSScriptRoot 'FleetScopeCollector.psm1'
$installDir = 'C:\Program Files\FleetScope'

New-Item -ItemType Directory -Force -Path $installDir | Out-Null
Copy-Item $moduleSource -Destination $installDir -Force

# Config dir: create it and grant the service account Modify so the enrollment
# write-back (permanent token) can persist.
$cfgDir = Split-Path $ConfigPath -Parent
New-Item -ItemType Directory -Force -Path $cfgDir | Out-Null
& icacls $cfgDir /grant ("${ServiceAccount}:(OI)(CI)M") | Out-Null

if (-not (Test-Path $ConfigPath)) {
    Write-Warning "Config not found at $ConfigPath. Copy config.example.json there and fill in the token + targets."
}

$modulePath = Join-Path $installDir 'FleetScopeCollector.psm1'
$command = "Import-Module '$modulePath'; Invoke-FleetScopeCollection -ConfigPath '$ConfigPath'"
$action = New-ScheduledTaskAction -Execute 'powershell.exe' `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -Command `"$command`""

$trigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(2) `
    -RepetitionInterval (New-TimeSpan -Hours $IntervalHours)

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd
$register = @{ TaskName = $TaskName; Action = $action; Trigger = $trigger; Settings = $settings; Force = $true }

if ($Credential) {
    # Regular account: Task Scheduler stores the password so the task can run
    # whether or not the user is logged on.
    $register['User'] = $ServiceAccount
    $register['Password'] = $Credential.GetNetworkCredential().Password
    $register['RunLevel'] = 'Highest'
} else {
    # gMSA: LogonType Password makes Task Scheduler fetch the managed password itself.
    $register['Principal'] = New-ScheduledTaskPrincipal -UserId $ServiceAccount -LogonType Password -RunLevel Highest
}

Register-ScheduledTask @register | Out-Null

Write-Host "Installed '$TaskName' running as $ServiceAccount (every $IntervalHours h). Config: $ConfigPath"
