using System.Text.Json.Nodes;

namespace FleetScope.Agent.Checks;

/// <summary>
/// Detects what the management VM offers. Keys match the <c>requires</c> entries in
/// check headers; a check whose requirement is missing is skipped and reported,
/// never run to fail (docs/AGENT.md §4.8, §5.1).
/// </summary>
public static class Prerequisites
{
    public const string PowerShell = "powershell";
    public const string CvadSdk = "cvad-sdk";
    public const string WinRmClient = "winrm-client";

    private const string Script = """
        $o = [ordered]@{}
        $o['powershell'] = $PSVersionTable.PSVersion.ToString()
        $sdk = $null
        try {
            $s = Get-PSSnapin -Registered -Name Citrix.Broker.Admin.V2 -ErrorAction SilentlyContinue
            if ($s) { $sdk = "$($s.Version)" }
        } catch {}
        if (-not $sdk) {
            $m = Get-Module -ListAvailable -Name Citrix.Broker.Commands -ErrorAction SilentlyContinue | Select-Object -First 1
            if ($m) { $sdk = $m.Version.ToString() }
        }
        $o['cvad-sdk'] = $sdk
        $svc = Get-Service -Name WinRM -ErrorAction SilentlyContinue
        $o['winrm-client'] = [bool]($svc -and $svc.Status -eq 'Running')
        $o | ConvertTo-Json -Compress
        """;

    public static async Task<Dictionary<string, object?>> DetectAsync(CancellationToken ct)
    {
        var result = new Dictionary<string, object?>();
        if (!PowerShellRunner.IsAvailable)
        {
            result[PowerShell] = null;
            return result;
        }
        var r = await PowerShellRunner.RunScriptAsync(Script, TimeSpan.FromSeconds(60), ct);
        if (r.ExitCode != 0 || string.IsNullOrWhiteSpace(r.StdOut))
        {
            result[PowerShell] = null;
            return result;
        }
        if (JsonNode.Parse(r.StdOut.Trim()) is JsonObject obj)
        {
            foreach (var kv in obj)
                result[kv.Key] = kv.Value switch
                {
                    null => null,
                    JsonValue v when v.TryGetValue<bool>(out var b) => b,
                    JsonValue v when v.TryGetValue<string>(out var s) => s,
                    var other => other.ToJsonString(),
                };
        }
        return result;
    }

    /// <summary>A requirement is met when it is reported and is neither null nor false.</summary>
    public static bool IsMet(IReadOnlyDictionary<string, object?> detected, string requirement)
        => detected.TryGetValue(requirement, out var v) && v is not null && v is not false;

    public static string Describe(string requirement) => requirement switch
    {
        CvadSdk => "CVAD PowerShell SDK (install from the CVAD product ISO; the Remote PowerShell SDK is the Cloud variant and does not apply)",
        WinRmClient => "WinRM service",
        PowerShell => "Windows PowerShell 5.1",
        _ => requirement,
    };
}
