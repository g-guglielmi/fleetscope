namespace FleetScope.Agent.Windows;

/// <summary>
/// Installs the CVAD PowerShell SDK from media the operator points at — never from
/// Citrix directly (docs/AGENT.md §4.8). The Broker snap-in MSI is all the
/// citrix-site check needs; it lives on the CVAD ISO under
/// x64\Citrix Desktop Delivery Controller\.
/// </summary>
public static class PrereqInstaller
{
    private const string BrokerMsi = "Broker_PowerShellSnapIn_x64.msi";

    public static (bool Ok, string Message) InstallCvadSdk(string source)
    {
        var msi = ResolveMsi(source);
        if (msi is null)
            return (false, $"{BrokerMsi} not found under '{source}' (point --citrix-sdk-source at the CVAD ISO root, the 'Citrix Desktop Delivery Controller' folder, or an .msi file)");
        var (code, output) = Exec.Run("msiexec.exe", $"/i \"{msi}\" /qn /norestart");
        return code switch
        {
            0 => (true, $"installed {Path.GetFileName(msi)}"),
            3010 => (true, $"installed {Path.GetFileName(msi)} (a reboot is required before it loads)"),
            1603 or 1925 or 5 => (false, $"msiexec exit {code} installing {msi}: needs an elevated/administrator context. {Trim(output)}"),
            _ => (false, $"msiexec exit {code} installing {msi}: {Trim(output)}"),
        };
    }

    internal static string? ResolveMsi(string source)
    {
        if (File.Exists(source) && source.EndsWith(".msi", StringComparison.OrdinalIgnoreCase))
            return source;
        if (!Directory.Exists(source)) return null;
        // The known layouts first; a full recursive search only as a last resort.
        foreach (var dir in new[] { source, Path.Combine(source, "x64", "Citrix Desktop Delivery Controller") })
        {
            var candidate = Path.Combine(dir, BrokerMsi);
            if (File.Exists(candidate)) return candidate;
        }
        try
        {
            return Directory.EnumerateFiles(source, BrokerMsi, SearchOption.AllDirectories).FirstOrDefault();
        }
        catch
        {
            return null;
        }
    }

    private static string Trim(string s) => s.Length <= 300 ? s : s[..300] + "…";
}
