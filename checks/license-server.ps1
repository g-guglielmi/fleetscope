<# FLEETSCOPE
{
  "name": "license-server",
  "version": "1.0.0",
  "description": "Citrix License Server pools (product, count, Subscription Advantage date) and server version, via remote CIM.",
  "requires": ["winrm-client"],
  "timeoutSeconds": 300,
  "settingsSchema": {
    "servers": { "type": "hostList", "required": true, "label": "License servers", "help": "FQDNs; the service account needs remote CIM rights (local Administrators)." }
  }
}
#>
#requires -Version 5.1
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$fsInput = [Console]::In.ReadToEnd() | ConvertFrom-Json
$fsWarnings = New-Object System.Collections.ArrayList
function Warn([string]$m) { [void]$fsWarnings.Add($m); [Console]::Error.WriteLine("WARN $m") }
function Emit($components, $certificates, $licenses, $facts) {
    @{ schema = 1; components = @($components); certificates = @($certificates); licenses = @($licenses)
       warnings = @($fsWarnings); facts = $facts } | ConvertTo-Json -Depth 10 -Compress | Write-Output
}
function ToIso($v) { if (-not $v) { return $null }; try { ([datetime]$v).ToUniversalTime().ToString('o') } catch { $null } }

$components = @(); $licenses = @(); $ok = 0

foreach ($srv in @($fsInput.settings.servers)) {
    $session = $null
    try {
        $session = New-CimSession -ComputerName $srv -ErrorAction Stop
        $pools = Get-CimInstance -CimSession $session -Namespace 'ROOT\CitrixLicensing' -ClassName 'Citrix_GT_License_Pool' -ErrorAction Stop
        foreach ($p in @($pools)) {
            $licenses += [pscustomobject]@{
                product = $p.PLD; edition = $p.LicenseType; model = $p.LicenseModel; count = [int]$p.Count
                subscriptionAdvantageDate = ToIso $p.SubscriptionDate
                expires = ToIso $p.ExpirationDate
            }
        }
        # Server version + OS: the license service binary carries the product version.
        $os = Get-CimInstance -CimSession $session -ClassName Win32_OperatingSystem -ErrorAction SilentlyContinue
        $svc = Get-CimInstance -CimSession $session -ClassName Win32_Service -Filter "Name='Citrix Licensing'" -ErrorAction SilentlyContinue
        $ver = $null
        if ($svc -and $svc.PathName) {
            $exe = ($svc.PathName -replace '^"([^"]+)".*$', '$1')
            $file = Get-CimInstance -CimSession $session -ClassName CIM_DataFile -Filter ("Name='{0}'" -f ($exe -replace '\\', '\\\\')) -ErrorAction SilentlyContinue
            if ($file) { $ver = $file.Version }
        }
        $components += [pscustomobject]@{
            type = 'license-server'; hostname = $srv; product = 'Citrix License Server'
            version = $ver; build = $ver
            osVersion = if ($os) { "$($os.Caption) $($os.Version)" } else { $null }
            extra = @{ pools = @($pools).Count }
        }
        $ok++
    } catch { Warn "License server '$srv': $($_.Exception.Message)" }
    finally { if ($session) { Remove-CimSession $session -ErrorAction SilentlyContinue } }
}

Emit $components @() $licenses @{ serversQueried = @($fsInput.settings.servers).Count; serversOk = $ok }
if ($ok -eq 0 -and @($fsInput.settings.servers).Count -gt 0) { exit 2 }
exit 0
