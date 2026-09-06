using System.Text.Json.Nodes;

namespace FleetScope.Agent.Api;

// Wire shapes of /api/agent/* (docs/AGENT.md §6.2). Property names map to camelCase via Json.Options.

public sealed class NamedRef
{
    public string Slug { get; set; } = "";
    public string Name { get; set; } = "";
}

public sealed class EnrollResponse
{
    public string AgentToken { get; set; } = "";
    public NamedRef Client { get; set; } = new();
    public NamedRef Site { get; set; } = new();
    public int CheckinSeconds { get; set; } = 120;
}

public sealed class CheckinRequest
{
    public string? AgentVersion { get; set; }
    public string? Hostname { get; set; }
    public string? OsVersion { get; set; }
    public Dictionary<string, object?> Prerequisites { get; set; } = new();
    public Dictionary<string, int> CredentialVersions { get; set; } = new();
    public JsonNode? LastRun { get; set; }
}

public sealed class CredentialRef
{
    public string Name { get; set; } = "";
    public string Kind { get; set; } = "";
    public int Version { get; set; }
}

public sealed class CheckConfig
{
    public bool Enabled { get; set; }
    public JsonObject? Settings { get; set; }
}

public sealed class AgentSection
{
    public string? ServiceAccount { get; set; }
}

public sealed class SiteConfig
{
    public int IntervalMinutes { get; set; } = 360;
    public bool AutoUpdate { get; set; } = true;
    public AgentSection Agent { get; set; } = new();
    public JsonObject? Prerequisites { get; set; }
    public Dictionary<string, CheckConfig> Checks { get; set; } = new();
}

public sealed class CheckinResponse
{
    public string? ServerTime { get; set; }
    public int CheckinSeconds { get; set; } = 120;
    public NamedRef? Client { get; set; }
    public NamedRef? Site { get; set; }
    public SiteConfig Config { get; set; } = new();
    /// <summary>Kept raw: the signature covers the exact document.</summary>
    public JsonObject? Manifest { get; set; }
    public JsonObject? Release { get; set; }
    public List<CredentialRef> Credentials { get; set; } = new();
    public List<string> Actions { get; set; } = new();
}

public sealed class ManifestEntry
{
    public string Name { get; set; } = "";
    public string Version { get; set; } = "";
    public string? Description { get; set; }
    public string File { get; set; } = "";
    public string Sha256 { get; set; } = "";
    public string Shell { get; set; } = "powershell";
    public List<string> Requires { get; set; } = new();
    public int TimeoutSeconds { get; set; } = 300;
}

public sealed class CredentialResponse
{
    public string Name { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Username { get; set; } = "";
    public string Password { get; set; } = "";
    public int Version { get; set; }
}

public sealed class IngestResult
{
    public bool Ok { get; set; }
    public int SnapshotId { get; set; }
    public int Components { get; set; }
    public int Certificates { get; set; }
    public int Licenses { get; set; }
    public int Findings { get; set; }
}
