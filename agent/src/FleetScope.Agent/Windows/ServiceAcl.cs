namespace FleetScope.Agent.Windows;

/// <summary>
/// Lets the service account manage its own service (docs/AGENT.md §4.4): query and
/// change config (password rotation), start/stop, interrogate — nothing else on the box.
/// </summary>
internal static class ServiceAcl
{
    // CC query config · DC change config · LC query status · SW enumerate dependents
    // RP start · WP stop · LO interrogate · CR user control · RC read security
    private const string Rights = "CCDCLCSWRPWPLOCRRC";

    public static void GrantServiceControl(string serviceName, string account)
    {
        var sid = Lsa.ResolveSid(account).Value;
        var sddl = Exec.RunOrThrow("sc.exe", $"sdshow {serviceName}", "reading the service security descriptor").Trim();
        if (sddl.Contains(sid, StringComparison.OrdinalIgnoreCase)) return;

        var dacl = sddl.IndexOf("D:", StringComparison.Ordinal);
        if (dacl < 0) throw new InvalidOperationException($"unexpected service SDDL: {sddl}");
        var firstAce = sddl.IndexOf('(', dacl);
        if (firstAce < 0) throw new InvalidOperationException($"unexpected service SDDL: {sddl}");

        var updated = sddl.Insert(firstAce, $"(A;;{Rights};;;{sid})");
        Exec.RunOrThrow("sc.exe", $"sdset {serviceName} {updated}", "granting the service account control of its service");
    }
}
