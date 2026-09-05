<# FLEETSCOPE
{
  "name": "storefront",
  "version": "1.0.0",
  "description": "StoreFront version, Windows version and IIS certificates (with private key) of each StoreFront server, via PowerShell Remoting.",
  "requires": ["winrm-client"],
  "timeoutSeconds": 300,
  "settingsSchema": {
    "servers": { "type": "hostList", "required": true, "label": "StoreFront servers", "help": "FQDNs reachable over WinRM with the agent's service account." }
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

$components = @(); $certs = @(); $ok = 0

foreach ($srv in @($fsInput.settings.servers)) {
    try {
        $data = Invoke-Command -ComputerName $srv -ErrorAction Stop -ScriptBlock {
            $mod = Get-Module -ListAvailable Citrix.StoreFront | Sort-Object Version -Descending | Select-Object -First 1
            if (-not $mod) {
                # Fallback: the installed product entry.
                $reg = Get-ItemProperty 'HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall\*' -ErrorAction SilentlyContinue |
                    Where-Object { $_.DisplayName -like 'Citrix StoreFront*' } | Select-Object -First 1
                $ver = if ($reg) { $reg.DisplayVersion } else { $null }
            } else { $ver = $mod.Version.ToString() }
            $os = Get-CimInstance Win32_OperatingSystem
            $c = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.HasPrivateKey } | ForEach-Object {
                [pscustomobject]@{
                    subject = $_.Subject; issuer = $_.Issuer
                    notAfter = $_.NotAfter.ToUniversalTime().ToString('o'); thumbprint = $_.Thumbprint
                }
            }
            [pscustomobject]@{ version = $ver; os = "$($os.Caption) $($os.Version)"; certs = @($c) }
        }
        $components += [pscustomobject]@{
            type = 'storefront'; hostname = $srv; product = 'Citrix StoreFront'
            version = $data.version; build = $data.version; osVersion = $data.os; extra = @{}
        }
        foreach ($c in @($data.certs)) {
            $certs += [pscustomobject]@{
                source = 'storefront'; hostname = $srv; subject = $c.subject
                issuer = $c.issuer; notAfter = $c.notAfter; thumbprint = $c.thumbprint
            }
        }
        $ok++
    } catch { Warn "StoreFront '$srv': $($_.Exception.Message)" }
}

Emit $components $certs @() @{ serversQueried = @($fsInput.settings.servers).Count; serversOk = $ok }
if ($ok -eq 0 -and @($fsInput.settings.servers).Count -gt 0) { exit 2 }
exit 0
