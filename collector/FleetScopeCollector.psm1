#requires -Version 5.1
<#
    FleetScope Collector
    ------------------------
    Collects Citrix farm component/versions, certificates and license info and
    PUSHes a single JSON payload to the dashboard ingest API.

    Each collector is bound to one client/site via its bearer token. Run via a
    scheduled task (see Install-Collector.ps1). Citrix/hypervisor sections are
    guarded so the module still runs where an SDK is absent.
#>

$script:CollectorVersion = '1.0.0'

function Write-CollectorLog {
    param([string]$Message, [string]$Level = 'INFO')
    Write-Host ("{0} [{1}] {2}" -f (Get-Date -Format s), $Level, $Message)
}

# ----------------------------------------------------------------------------
# Individual collectors — each returns objects matching the ingest contract.
# ----------------------------------------------------------------------------

function Get-FSOperatingSystem {
    try {
        $os = Get-CimInstance Win32_OperatingSystem -ErrorAction Stop
        return ("{0} {1}" -f $os.Caption, $os.Version)
    } catch {
        Write-CollectorLog "OS query failed: $_" 'WARN'
        return $null
    }
}

function Get-FSControllers {
    # Requires the Citrix Broker PowerShell SDK (Citrix.Broker.Admin.V2).
    if (-not (Get-Command Get-BrokerController -ErrorAction SilentlyContinue)) {
        Write-CollectorLog 'Broker SDK not present; skipping controllers.' 'WARN'
        return @()
    }
    try {
        Get-BrokerController | ForEach-Object {
            [pscustomobject]@{
                type      = 'controller'
                hostname  = $_.DNSName
                product   = 'Citrix Virtual Apps and Desktops'
                version   = $_.ControllerVersion
                build     = $_.ControllerVersion
                osVersion = $_.OSVersion
                extra     = @{ state = "$($_.State)"; sid = "$($_.SID)" }
            }
        }
    } catch { Write-CollectorLog "Controller query failed: $_" 'WARN'; @() }
}

function Get-FSVdas {
    if (-not (Get-Command Get-BrokerMachine -ErrorAction SilentlyContinue)) {
        Write-CollectorLog 'Broker SDK not present; skipping VDAs.' 'WARN'
        return @()
    }
    try {
        # Group by AgentVersion so we report unique VDA versions, not every machine.
        Get-BrokerMachine -MaxRecordCount 100000 |
            Where-Object { $_.AgentVersion } |
            Group-Object AgentVersion | ForEach-Object {
                $sample = $_.Group[0]
                [pscustomobject]@{
                    type      = 'vda'
                    hostname  = $sample.DNSName
                    product   = 'Citrix VDA'
                    version   = $_.Name
                    build     = $_.Name
                    osVersion = $sample.OSType
                    extra     = @{ machineCount = $_.Count }
                }
            }
    } catch { Write-CollectorLog "VDA query failed: $_" 'WARN'; @() }
}

function Get-FSStoreFront {
    if (-not (Get-Module -ListAvailable -Name Citrix.StoreFront)) {
        Write-CollectorLog 'StoreFront module not present; skipping.' 'WARN'
        return @()
    }
    try {
        Import-Module Citrix.StoreFront -ErrorAction Stop
        $v = (Get-Module Citrix.StoreFront).Version.ToString()
        [pscustomobject]@{
            type = 'storefront'; hostname = $env:COMPUTERNAME
            product = 'Citrix StoreFront'; version = $v; build = $v
            osVersion = (Get-FSOperatingSystem); extra = @{}
        }
    } catch { Write-CollectorLog "StoreFront query failed: $_" 'WARN'; @() }
}

function Get-FSLicenses {
    # Citrix License Server exposes pools via WMI.
    try {
        $pools = Get-CimInstance -Namespace 'ROOT\CitrixLicensing' `
            -ClassName 'Citrix_GT_License_Pool' -ErrorAction Stop
        $pools | ForEach-Object {
            [pscustomobject]@{
                product = $_.PLD
                edition = $_.LicenseType
                model   = $null
                count   = [int]$_.Count
                subscriptionAdvantageDate = $_.SubscriptionDate
                expires = if ($_.LicenseExpirationDate -and $_.LicenseExpirationDate -ne 'permanent') { $_.LicenseExpirationDate } else { $null }
            }
        }
    } catch { Write-CollectorLog "License query failed (not a license server?): $_" 'WARN'; @() }
}

function Get-FSLocalCertificates {
    # StoreFront/IIS TLS certs bound on this host.
    try {
        Get-ChildItem Cert:\LocalMachine\My -ErrorAction Stop |
            Where-Object { $_.HasPrivateKey -and $_.NotAfter } | ForEach-Object {
                [pscustomobject]@{
                    source   = 'storefront'
                    hostname = $env:COMPUTERNAME
                    subject  = $_.Subject
                    issuer   = $_.Issuer
                    notAfter = $_.NotAfter.ToUniversalTime().ToString('o')
                    thumbprint = $_.Thumbprint
                }
            }
    } catch { Write-CollectorLog "Local cert query failed: $_" 'WARN'; @() }
}

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

    if ($cfg.collect.controllers) { $components += Get-FSControllers }
    if ($cfg.collect.vdas)        { $components += Get-FSVdas }
    if ($cfg.collect.storefront)  { $components += Get-FSStoreFront }
    if ($cfg.collect.license)     { $licenses   += Get-FSLicenses }
    if ($cfg.collect.localCertificates) { $certificates += Get-FSLocalCertificates }

    foreach ($ns in @($cfg.netscalers)) {
        if (-not $ns) { continue }
        $res = Get-FSNetScaler -Config $ns
        $components += $res.components
        $certificates += $res.certificates
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

    Send-FleetScope -Config $cfg -Payload $payload
}

function Send-FleetScope {
    param([pscustomobject]$Config, [pscustomobject]$Payload)

    $json = $Payload | ConvertTo-Json -Depth 10
    $uri = "$($Config.dashboardUrl.TrimEnd('/'))/api/ingest"
    Write-CollectorLog ("Pushing {0} components, {1} certs, {2} licenses -> {3}" -f `
        $Payload.components.Count, $Payload.certificates.Count, $Payload.licenses.Count, $uri)
    try {
        $resp = Invoke-RestMethod -Method Post -Uri $uri -Body $json -ContentType 'application/json' `
            -Headers @{ Authorization = "Bearer $($Config.ingestKey)" }
        Write-CollectorLog ("Ingest OK: snapshot {0}, {1} findings" -f $resp.snapshotId, $resp.findings)
    } catch {
        Write-CollectorLog "Ingest FAILED: $_" 'ERROR'
        throw
    }
}

Export-ModuleMember -Function Invoke-FleetScopeCollection, Send-FleetScope
