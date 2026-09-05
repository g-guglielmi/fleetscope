<# FLEETSCOPE
{
  "name": "netscaler",
  "version": "1.0.0",
  "description": "NetScaler ADC/Gateway firmware build and SSL certificate expiry via the NITRO REST API. Needs only a read-only NITRO user.",
  "requires": [],
  "timeoutSeconds": 180,
  "settingsSchema": {
    "targets": {
      "type": "list", "required": true, "label": "NetScalers",
      "item": {
        "host": { "type": "url", "required": true, "label": "NITRO URL", "help": "https://<nsip or fqdn>" },
        "credential": { "type": "credentialRef", "kind": "device", "required": true, "label": "Credential" },
        "skipCertificateCheck": { "type": "bool", "label": "Skip TLS certificate validation", "help": "For appliances reached by IP or with a self-signed management certificate." }
      }
    }
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

[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
$components = @(); $certs = @(); $ok = 0

foreach ($t in @($fsInput.settings.targets)) {
    $base = "$($t.host)".TrimEnd('/')
    $hostName = ([Uri]$base).Host
    $cred = $fsInput.credentials.PSObject.Properties[$t.credential]
    if (-not $cred) { Warn "NetScaler ${hostName}: credential '$($t.credential)' was not delivered."; continue }
    $cred = $cred.Value

    # Windows PowerShell 5.1 has no -SkipCertificateCheck; scope a callback to this process.
    if ($t.skipCertificateCheck) { [Net.ServicePointManager]::ServerCertificateValidationCallback = { $true } }
    else { [Net.ServicePointManager]::ServerCertificateValidationCallback = $null }

    $headers = $null
    try {
        $login = @{ login = @{ username = $cred.username; password = $cred.password } } | ConvertTo-Json -Compress
        $sess = Invoke-RestMethod -Method Post -Uri "$base/nitro/v1/config/login" -Body $login -ContentType 'application/json'
        $headers = @{ Cookie = "NITRO_AUTH_TOKEN=$($sess.sessionid)" }

        $ver = Invoke-RestMethod -Uri "$base/nitro/v1/config/nsversion" -Headers $headers
        # e.g. "NetScaler NS13.1: Build 49.15.nc, Date: ..." -> "13.1-49.15" for advisory matching.
        $raw = "$($ver.nsversion.version)"
        $normalized = if ($raw -match 'NS(\d+\.\d+).*?Build\s+(\d+\.\d+)') { "$($Matches[1])-$($Matches[2])" } else { $raw }

        $hw = $null
        try { $hw = (Invoke-RestMethod -Uri "$base/nitro/v1/config/nshardware" -Headers $headers).nshardware } catch {}
        $ha = $null
        try { $ha = (Invoke-RestMethod -Uri "$base/nitro/v1/config/hanode" -Headers $headers).hanode | Where-Object { $_.id -eq 0 } } catch {}

        $components += [pscustomobject]@{
            type = 'netscaler'; hostname = $hostName; product = 'Citrix NetScaler (ADC)'
            version = $normalized; build = $normalized; osVersion = $null
            extra = @{ rawVersion = $raw
                       model = if ($hw) { $hw.hwdescription } else { $null }
                       serial = if ($hw) { $hw.serialno } else { $null }
                       haState = if ($ha) { $ha.state } else { $null } }
        }

        $ssl = Invoke-RestMethod -Uri "$base/nitro/v1/config/sslcertkey" -Headers $headers
        foreach ($c in @($ssl.sslcertkey)) {
            if (-not $c.clientcertnotafter) { continue }
            try { $na = ([datetime]$c.clientcertnotafter).ToUniversalTime().ToString('o') } catch { $na = $null }
            if (-not $na) { continue }
            $certs += [pscustomobject]@{
                source = 'netscaler'; hostname = $hostName; subject = $c.subject; issuer = $c.issuer
                notAfter = $na; thumbprint = $c.certkey
            }
        }
        $ok++
    } catch {
        Warn "NetScaler ${hostName}: $($_.Exception.Message)"
    } finally {
        if ($headers) { try { Invoke-RestMethod -Method Post -Uri "$base/nitro/v1/config/logout" -Headers $headers -Body '{"logout":{}}' -ContentType 'application/json' | Out-Null } catch {} }
        [Net.ServicePointManager]::ServerCertificateValidationCallback = $null
    }
}

Emit $components $certs @() @{ targets = @($fsInput.settings.targets).Count; targetsOk = $ok }
if ($ok -eq 0 -and @($fsInput.settings.targets).Count -gt 0) { exit 2 }
exit 0
