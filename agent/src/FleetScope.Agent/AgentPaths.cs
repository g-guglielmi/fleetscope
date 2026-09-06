namespace FleetScope.Agent;

/// <summary>On-disk layout (docs/AGENT.md §4.3).</summary>
public static class AgentPaths
{
    public const string ServiceName = "FleetScopeAgent";
    public const string ServiceDisplayName = "FleetScope Agent";
    public const string ServiceDescription = "Collects Citrix farm inventory for the FleetScope dashboard using server-managed, signed check modules.";

    /// <summary>Binary home. Overridable with FLEETSCOPE_INSTALL_DIR (self-update tests).</summary>
    public static string InstallDir { get; set; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.ProgramFiles), "FleetScope", "Agent");

    public static string ExePath => Path.Combine(InstallDir, "FleetScopeAgent.exe");

    /// <summary>State root. Overridable with FLEETSCOPE_DATA_DIR (tests, side-by-side runs).</summary>
    public static string DataDir { get; set; } =
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.CommonApplicationData), "FleetScope");

    public static string StateFile => Path.Combine(DataDir, "state.json");
    public static string RunNowFlag => Path.Combine(DataDir, "run-now.flag");
    public static string UpdateMarker => Path.Combine(DataDir, "update.json");
    public static string SecretsDir => Path.Combine(DataDir, "secrets");
    public static string TokenFile => Path.Combine(SecretsDir, "agent.token");
    public static string CredentialsDir => Path.Combine(SecretsDir, "credentials");
    public static string ChecksDir => Path.Combine(DataDir, "checks");
    public static string LogsDir => Path.Combine(DataDir, "logs");
    public static string UpdatesDir => Path.Combine(DataDir, "updates");

    public static void EnsureDirs()
    {
        foreach (var d in new[] { DataDir, SecretsDir, CredentialsDir, ChecksDir, LogsDir, UpdatesDir })
            Directory.CreateDirectory(d);
    }
}
