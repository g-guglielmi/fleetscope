using System.Text.Json;
using System.Text.Json.Nodes;

namespace FleetScope.Agent;

/// <summary>Non-secret local state (state.json). Secrets live DPAPI-encrypted under secrets\.</summary>
public sealed class AgentState
{
    public string DashboardUrl { get; set; } = "";
    public bool Insecure { get; set; }
    /// <summary>Base64 Ed25519 public key pinned at install; every manifest/release must verify against it.</summary>
    public string SigningKey { get; set; } = "";
    public string Hostname { get; set; } = Environment.MachineName;

    public string? ClientSlug { get; set; }
    public string? ClientName { get; set; }
    public string? SiteSlug { get; set; }
    public string? SiteName { get; set; }
    public DateTimeOffset? EnrolledAt { get; set; }
    public string? InstalledVersion { get; set; }

    public int CheckinSeconds { get; set; } = 120;
    public DateTimeOffset? LastCheckin { get; set; }
    public string? LastCheckinError { get; set; }
    public DateTimeOffset? LastCollection { get; set; }
    /// <summary>{ at, checks: [...] } — the last collection's per-check diagnostics, echoed at check-in.</summary>
    public JsonObject? LastRun { get; set; }

    /// <summary>Credential name the service logon was last configured from, and its version.</summary>
    public string? ServiceAccount { get; set; }
    public int? ServiceAccountVersion { get; set; }
    public string? PendingServiceAccount { get; set; }
    /// <summary>Set by <c>service-account set</c>: the logon is managed on this VM, not from the dashboard.</summary>
    public bool ServiceAccountLocal { get; set; }
    /// <summary>Enrolled with <c>install --no-service</c>: there is no Windows service to manage.</summary>
    public bool NoService { get; set; }
    public bool RestartPending { get; set; }

    public string? ReleaseVersion { get; set; }
    public bool ManifestValid { get; set; }
    public string? ManifestError { get; set; }

    public static AgentState Load()
    {
        var path = AgentPaths.StateFile;
        if (!File.Exists(path)) return new AgentState();
        try
        {
            return JsonSerializer.Deserialize<AgentState>(File.ReadAllText(path), Json.Options) ?? new AgentState();
        }
        catch (JsonException)
        {
            return new AgentState();
        }
    }

    public void Save()
    {
        Directory.CreateDirectory(AgentPaths.DataDir);
        var tmp = AgentPaths.StateFile + ".tmp";
        File.WriteAllText(tmp, JsonSerializer.Serialize(this, Json.Pretty));
        File.Move(tmp, AgentPaths.StateFile, overwrite: true);
    }

    public bool IsEnrolled => !string.IsNullOrEmpty(DashboardUrl) && !string.IsNullOrEmpty(SiteSlug);
}
