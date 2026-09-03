#requires -Version 5.1
<#
    FleetScope Collector (remote mode)
    ----------------------------------
    Runs on a management VM as a domain service account and collects a Citrix
    site's component/versions, certificates and license info, then PUSHes a
    single JSON payload to the dashboard ingest API.

    Reach model (nothing is network-scanned; targets are either auto-discovered
    from a Delivery Controller or declared in the config):
      - Controllers / VDAs / hypervisor connections: Citrix Remote PowerShell SDK,
        pointed at a DDC with -AdminAddress (enumerates the whole site).
      - StoreFront version + IIS certs: PowerShell Remoting (WinRM) to each SF server.
      - License pools: remote CIM (WinRM) to each license server.
      - NetScaler firmware + SSL certs: NITRO REST.

    Windows targets use the service account's identity (Kerberos) — no Windows
    credentials are stored in the config. NetScaler still uses its own creds.
#>

$script:CollectorVersion = '1.1.0'

function Write-CollectorLog {
    param([string]$Message, [string]$Level = 'INFO')
    Write-Host ("{0} [{1}] {2}" -f (Get-Date -Format s), $Level, $Message)
}

function Test-FileWritable {
    # True if the current account can open the file for writing.
    param([string]$Path)
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::Write, [System.IO.FileShare]::ReadWrite)
        $fs.Close()
        return $true
    } catch {
        return $false
    }
}

function ConvertTo-IsoUtc {
    # Best-effort: return ISO-8601 UTC, or $null if the value isn't a real date.
    param($Value)
    if (-not $Value) { return $null }
    try { return ([datetime]$Value).ToUniversalTime().ToString('o') } catch { return $null }
}

# ----------------------------------------------------------------------------
# Citrix broker (Remote PowerShell SDK, -AdminAddress)
# ----------------------------------------------------------------------------

function Initialize-CitrixBroker {
    if (Get-Command Get-BrokerController -ErrorAction SilentlyContinue) { return $true }
    try { Import-Module Citrix.Broker.Commands -ErrorAction Stop } catch {}
    if (-not (Get-Command Get-BrokerController -ErrorAction SilentlyContinue)) {
        try { Add-PSSnapin Citrix.Broker.Admin.V2 -ErrorAction Stop } catch {}
    }
    return [bool](Get-Command Get-BrokerController -ErrorAction SilentlyContinue)
}

function Resolve-BrokerAddress {
    param([string[]]$Addresses)
    foreach ($a in $Addresses) {
        try {
            Get-BrokerSite -AdminAddress $a -ErrorAction Stop | Out-Null
            return $a
        } catch {
            Write-CollectorLog "Delivery Controller '$a' not reachable: $_" 'WARN'
        }
    }
    return $null
}

function Get-FSControllers {
    param([string]$AdminAddress)
    try {
        Get-BrokerController -AdminAddress $AdminAddress -ErrorAction Stop | ForEach-Object {
            [pscustomobject]@{
                type='controller'; hostname=$_.DNSName
                product='Citrix Virtual Apps and Desktops'
                version=$_.ControllerVersion; build=$_.ControllerVersion
                osVersion=$_.OSVersion; extra=@{ state="$($_.State)" }
            }
        }
    } catch { Write-CollectorLog "Controller query failed: $_" 'WARN'; @() }
}

function Get-FSVdas {
    param([string]$AdminAddress)
    try {
        # Group by AgentVersion so we report unique VDA versions, not every machine.
        Get-BrokerMachine -AdminAddress $AdminAddress -MaxRecordCount 100000 -ErrorAction Stop |
            Where-Object { $_.AgentVersion } |
            Group-Object AgentVersion | ForEach-Object {
                $s = $_.Group[0]
                [pscustomobject]@{
                    type='vda'; hostname=$s.DNSName; product='Citrix VDA'
                    version=$_.Name; build=$_.Name; osVersion=$s.OSType
                    extra=@{ machineCount=$_.Count }
                }
            }
    } catch { Write-CollectorLog "VDA query failed: $_" 'WARN'; @() }
}

function Get-FSHypervisors {
    param([string]$AdminAddress)
    # Type comes free from the DDC. Version needs a per-hypervisor query
    # (PowerCLI / Hyper-V) and is left null for now.
    try {
        Get-BrokerHypervisorConnection -AdminAddress $AdminAddress -ErrorAction Stop | ForEach-Object {
            [pscustomobject]@{
                type='hypervisor'; hostname=$_.Name; product="$($_.HypervisorType)"
                version=$null; build=$null; osVersion=$null
                extra=@{ state="$($_.State)" }
            }
        }
    } catch { Write-CollectorLog "Hypervisor connection query failed: $_" 'WARN'; @() }
}

# ----------------------------------------------------------------------------
# StoreFront (remote via WinRM): version, OS, IIS certificates
# ----------------------------------------------------------------------------

function Get-FSStoreFront {
    param([string[]]$Servers)
    $components=@(); $certs=@()
    foreach ($srv in $Servers) {
        try {
            $data = Invoke-Command -ComputerName $srv -ErrorAction Stop -ScriptBlock {
                $mod = Get-Module -ListAvailable Citrix.StoreFront | Sort-Object Version -Descending | Select-Object -First 1
                $os = Get-CimInstance Win32_OperatingSystem
                $c = Get-ChildItem Cert:\LocalMachine\My | Where-Object { $_.HasPrivateKey } | ForEach-Object {
                    [pscustomobject]@{
                        subject=$_.Subject; issuer=$_.Issuer
                        notAfter=$_.NotAfter.ToUniversalTime().ToString('o'); thumbprint=$_.Thumbprint
                    }
                }
                [pscustomobject]@{
                    version = if ($mod) { $mod.Version.ToString() } else { $null }
                    os = "$($os.Caption) $($os.Version)"; certs = $c
                }
            }
            $components += [pscustomobject]@{
                type='storefront'; hostname=$srv; product='Citrix StoreFront'
                version=$data.version; build=$data.version; osVersion=$data.os; extra=@{}
            }
            foreach ($c in @($data.certs)) {
                $certs += [pscustomobject]@{
                    source='storefront'; hostname=$srv; subject=$c.subject
                    issuer=$c.issuer; notAfter=$c.notAfter; thumbprint=$c.thumbprint
                }
            }
        } catch { Write-CollectorLog "StoreFront '$srv' query failed: $_" 'WARN' }
    }
    return @{ components=$components; certificates=$certs }
}

# ----------------------------------------------------------------------------
# License server (remote CIM via WinRM)
# ----------------------------------------------------------------------------

function Get-FSLicenses {
    param([string[]]$Servers)
    $out=@()
    foreach ($srv in $Servers) {
        $session=$null
        try {
            $session = New-CimSession -ComputerName $srv -ErrorAction Stop
            Get-CimInstance -CimSession $session -Namespace 'ROOT\CitrixLicensing' `
                -ClassName 'Citrix_GT_License_Pool' -ErrorAction Stop | ForEach-Object {
                    $out += [pscustomobject]@{
                        product=$_.PLD; edition=$_.LicenseType; model=$null; count=[int]$_.Count
                        subscriptionAdvantageDate = ConvertTo-IsoUtc $_.SubscriptionDate
                        expires = $null
                    }
                }
        } catch { Write-CollectorLog "License server '$srv' query failed: $_" 'WARN' }
        finally { if ($session) { Remove-CimSession $session -ErrorAction SilentlyContinue } }
    }
    return $out
}

# ----------------------------------------------------------------------------
# NetScaler (NITRO REST)
# ----------------------------------------------------------------------------

function Get-FSNetScaler {
    param([pscustomobject]$Config)

    $password = if ($Config.passwordEnv) { [Environment]::GetEnvironmentVariable($Config.passwordEnv) } else { $null }
    if (-not $password) {
        Write-CollectorLog "No password for NetScaler $($Config.host) (env $($Config.passwordEnv))." 'WARN'
        return @{ components = @(); certificates = @() }
    }

    $irmArgs = @{ ContentType = 'application/json' }
    if ($Config.skipCertificateCheck -and $PSVersionTable.PSVersion.Major -ge 6) {
        $irmArgs['SkipCertificateCheck'] = $true
    }

    $components = @(); $certs = @()
    try {
        $login = @{ login = @{ username = $Config.username; password = $password } } | ConvertTo-Json
        $sess = Invoke-RestMethod -Method Post -Uri "$($Config.host)/nitro/v1/config/login" -Body $login @irmArgs
        $headers = @{ 'Cookie' = "NITRO_AUTH_TOKEN=$($sess.sessionid)" }

        $ver = Invoke-RestMethod -Uri "$($Config.host)/nitro/v1/config/nsversion" -Headers $headers @irmArgs
        # NITRO returns e.g. "NetScaler NS13.1: Build 49.15.nc, Date: ...".
        # Normalize to a comparable "13.1-49.15" for advisory matching.
        $raw = $ver.nsversion.version
        $normalized = if ($raw -match 'NS(\d+\.\d+).*Build\s+(\d+\.\d+)') { "$($Matches[1])-$($Matches[2])" } else { $raw }
        $components += [pscustomobject]@{
            type = 'netscaler'; hostname = ([Uri]$Config.host).Host
            product = 'Citrix NetScaler (ADC)'
            version = $normalized; build = $normalized
            osVersion = $null; extra = @{ rawVersion = $raw }
        }

        $ssl = Invoke-RestMethod -Uri "$($Config.host)/nitro/v1/config/sslcertkey" -Headers $headers @irmArgs
        foreach ($c in $ssl.sslcertkey) {
            if ($c.clientcertnotafter) {
                $certs += [pscustomobject]@{
                    source = 'netscaler'; hostname = ([Uri]$Config.host).Host
                    subject = $c.subject; issuer = $c.issuer
                    notAfter = ([datetime]$c.clientcertnotafter).ToUniversalTime().ToString('o')
                    thumbprint = $c.certkey
                }
            }
        }

        Invoke-RestMethod -Method Post -Uri "$($Config.host)/nitro/v1/config/logout" `
            -Headers $headers -Body '{"logout":{}}' @irmArgs | Out-Null
    } catch {
        Write-CollectorLog "NetScaler $($Config.host) query failed: $_" 'WARN'
    }
    return @{ components = $components; certificates = $certs }
}

# ----------------------------------------------------------------------------
# Orchestration
# ----------------------------------------------------------------------------

function Invoke-FleetScopeCollection {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$ConfigPath)

    if (-not (Test-Path $ConfigPath)) { throw "Config not found: $ConfigPath" }
    $cfg = Get-Content $ConfigPath -Raw | ConvertFrom-Json

    $components = @(); $certificates = @(); $licenses = @()

    $ddcs = @($cfg.citrix.deliveryControllers) | Where-Object { $_ }
    if ($ddcs.Count -gt 0) {
        if (Initialize-CitrixBroker) {
            $addr = Resolve-BrokerAddress -Addresses $ddcs
            if ($addr) {
                Write-CollectorLog "Querying Citrix site via Delivery Controller $addr"
                $components += Get-FSControllers  -AdminAddress $addr
                $components += Get-FSVdas         -AdminAddress $addr
                $components += Get-FSHypervisors  -AdminAddress $addr
            } else {
                Write-CollectorLog 'No reachable Delivery Controller.' 'WARN'
            }
        } else {
            Write-CollectorLog 'Citrix Remote PowerShell SDK not found on this host.' 'WARN'
        }
    }

    $sf = @($cfg.storefrontServers) | Where-Object { $_ }
    if ($sf.Count -gt 0) {
        $r = Get-FSStoreFront -Servers $sf
        $components += $r.components; $certificates += $r.certificates
    }

    $ls = @($cfg.licenseServers) | Where-Object { $_ }
    if ($ls.Count -gt 0) { $licenses += Get-FSLicenses -Servers $ls }

    foreach ($ns in @($cfg.netscalers)) {
        if (-not $ns) { continue }
        $r = Get-FSNetScaler -Config $ns
        $components += $r.components; $certificates += $r.certificates
    }

    $payload = [pscustomobject]@{
        collectorVersion = $script:CollectorVersion
        client       = $cfg.client
        site         = $cfg.site
        probe        = $env:COMPUTERNAME
        collectedAt  = (Get-Date).ToUniversalTime().ToString('o')
        components   = @($components)
        certificates = @($certificates)
        licenses     = @($licenses)
    }

    $resp = Send-FleetScope -Config $cfg -Payload $payload

    # First push enrolls this probe: swap the temporary enrollment token for the
    # permanent per-probe token the server returns, persisting it to the config.
    # If we cannot save it, the probe keeps re-enrolling and will start failing
    # once the enrollment token expires or is revoked -- so make that loud.
    if ($resp -and $resp.collectorToken) {
        $warn = ("Enrolled but the permanent probe token could NOT be saved to '{0}'. " +
            "This probe will keep re-enrolling and will FAIL once the enrollment token " +
            "expires or is revoked. Grant the scheduled task's account write access to " +
            "the config, or move it to a writable location." -f $ConfigPath)

        if (-not (Test-FileWritable -Path $ConfigPath)) {
            Write-CollectorLog $warn 'ERROR'
        } else {
            try {
                $cfg.token = $resp.collectorToken
                $cfg | ConvertTo-Json -Depth 10 | Set-Content -Path $ConfigPath -Encoding UTF8 -ErrorAction Stop
                Write-CollectorLog "Enrolled: saved permanent probe token to $ConfigPath"
            } catch {
                Write-CollectorLog ("$warn Underlying error: $_") 'ERROR'
            }
        }
    }
}

function Send-FleetScope {
    param([pscustomobject]$Config, [pscustomobject]$Payload)

    $json = $Payload | ConvertTo-Json -Depth 10
    $uri = "$($Config.dashboardUrl.TrimEnd('/'))/api/ingest"
    Write-CollectorLog ("Pushing {0} components, {1} certs, {2} licenses -> {3}" -f `
        $Payload.components.Count, $Payload.certificates.Count, $Payload.licenses.Count, $uri)
    try {
        $resp = Invoke-RestMethod -Method Post -Uri $uri -Body $json -ContentType 'application/json' `
            -Headers @{ Authorization = "Bearer $($Config.token)" }
        Write-CollectorLog ("Ingest OK: snapshot {0}, {1} findings" -f $resp.snapshotId, $resp.findings)
        return $resp
    } catch {
        Write-CollectorLog "Ingest FAILED: $_" 'ERROR'
        throw
    }
}

Export-ModuleMember -Function Invoke-FleetScopeCollection, Send-FleetScope
