<# FLEETSCOPE
{
  "name": "citrix-site",
  "version": "1.0.0",
  "description": "Delivery Controllers, VDA versions and hypervisor connections of an on-prem CVAD site, via the CVAD PowerShell SDK pointed at a Delivery Controller.",
  "requires": ["cvad-sdk"],
  "timeoutSeconds": 300,
  "settingsSchema": {
    "deliveryControllers": { "type": "hostList", "required": true, "label": "Delivery Controllers", "help": "FQDNs; the first one that answers is used." }
  }
}
#>
#requires -Version 5.1
# FleetScope check contract (docs/AGENT.md §5): JSON in on stdin, JSON out on
# stdout, exit 0. Anything written to stderr is captured as diagnostics.
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
$fsInput = [Console]::In.ReadToEnd() | ConvertFrom-Json
$fsWarnings = New-Object System.Collections.ArrayList
function Warn([string]$m) { [void]$fsWarnings.Add($m); [Console]::Error.WriteLine("WARN $m") }
function Emit($components, $certificates, $licenses, $facts) {
    @{ schema = 1; components = @($components); certificates = @($certificates); licenses = @($licenses)
       warnings = @($fsWarnings); facts = $facts } | ConvertTo-Json -Depth 10 -Compress | Write-Output
}

$components = @(); $facts = @{}

# --- CVAD SDK snap-in / module (installed from the CVAD ISO) ---
if (-not (Get-Command Get-BrokerController -ErrorAction SilentlyContinue)) {
    try { Import-Module Citrix.Broker.Commands -ErrorAction Stop } catch {}
}
if (-not (Get-Command Get-BrokerController -ErrorAction SilentlyContinue)) {
    try { Add-PSSnapin Citrix.Broker.Admin.V2 -ErrorAction Stop } catch {}
}
if (-not (Get-Command Get-BrokerController -ErrorAction SilentlyContinue)) {
    Warn 'CVAD PowerShell SDK (Citrix.Broker.Admin.V2) not available on this host.'
    Emit @() @() @() @{ sdk = $null }
    exit 2
}
$sdk = (Get-Command Get-BrokerController).Version
$facts.sdkVersion = "$sdk"

# --- Pick the first Delivery Controller that answers ---
$addr = $null
foreach ($ddc in @($fsInput.settings.deliveryControllers)) {
    try { Get-BrokerSite -AdminAddress $ddc -ErrorAction Stop | Out-Null; $addr = $ddc; break }
    catch { Warn "Delivery Controller '$ddc' not reachable: $($_.Exception.Message)" }
}
if (-not $addr) { Warn 'No reachable Delivery Controller.'; Emit @() @() @() $facts; exit 2 }
$facts.adminAddress = $addr

try {
    $site = Get-BrokerSite -AdminAddress $addr
    $facts.siteName = $site.Name
    $facts.siteVersion = "$($site.BrokerServiceVersion)"
} catch { Warn "Get-BrokerSite: $($_.Exception.Message)" }

# --- Controllers ---
try {
    foreach ($c in Get-BrokerController -AdminAddress $addr -ErrorAction Stop) {
        $components += [pscustomobject]@{
            type = 'controller'; hostname = $c.DNSName; product = 'Citrix Virtual Apps and Desktops'
            version = "$($c.ControllerVersion)"; build = "$($c.ControllerVersion)"
            osVersion = $c.OSVersion; extra = @{ state = "$($c.State)"; desktopsRegistered = $c.DesktopsRegistered }
        }
    }
} catch { Warn "Controller query failed: $($_.Exception.Message)" }

# --- VDAs, grouped by agent version so we report versions, not every machine ---
try {
    Get-BrokerMachine -AdminAddress $addr -MaxRecordCount 100000 -ErrorAction Stop |
        Where-Object { $_.AgentVersion } |
        Group-Object AgentVersion | ForEach-Object {
            $sample = $_.Group[0]
            $components += [pscustomobject]@{
                type = 'vda'; hostname = $sample.DNSName; product = 'Citrix VDA'
                version = $_.Name; build = $_.Name; osVersion = "$($sample.OSType)"
                extra = @{ machineCount = $_.Count
                           sessionSupport = "$($sample.SessionSupport)"
                           registered = @($_.Group | Where-Object { $_.RegistrationState -eq 'Registered' }).Count }
            }
        }
} catch { Warn "VDA query failed: $($_.Exception.Message)" }

# --- Hypervisor connections (type is free; version needs a per-hypervisor check) ---
try {
    foreach ($h in Get-BrokerHypervisorConnection -AdminAddress $addr -ErrorAction Stop) {
        $components += [pscustomobject]@{
            type = 'hypervisor'; hostname = $h.Name; product = "$($h.HypervisorType)"
            version = $null; build = $null; osVersion = $null
            extra = @{ state = "$($h.State)"; uid = "$($h.Uid)" }
        }
    }
} catch { Warn "Hypervisor connection query failed: $($_.Exception.Message)" }

Emit $components @() @() $facts
exit 0
