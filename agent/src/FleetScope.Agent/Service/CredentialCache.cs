using System.Text.Json;
using FleetScope.Agent.Api;
using FleetScope.Agent.Security;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Service;

public sealed class CachedCredential
{
    public string Name { get; set; } = "";
    public string Kind { get; set; } = "";
    public string Username { get; set; } = "";
    public string Password { get; set; } = "";
    public int Version { get; set; }
    /// <summary>Set with <c>credential set --local</c>: never overwritten by the dashboard.</summary>
    public bool Local { get; set; }
}

/// <summary>DPAPI-encrypted cache of dashboard-delivered credentials (docs/AGENT.md §4.5).</summary>
public sealed class CredentialCache
{
    private static string Dir => AgentPaths.CredentialsDir;

    private static string PathFor(string name)
        => Path.Combine(Dir, string.Concat(name.Where(c => char.IsLetterOrDigit(c) || c is '-' or '_')) + ".bin");

    public CachedCredential? Get(string name)
    {
        var json = Dpapi.ReadProtected(PathFor(name));
        return json is null ? null : JsonSerializer.Deserialize<CachedCredential>(json, Json.Options);
    }

    public void Put(CachedCredential c) => Dpapi.WriteProtected(PathFor(c.Name), JsonSerializer.Serialize(c, Json.Options));

    public void Remove(string name)
    {
        var p = PathFor(name);
        if (File.Exists(p)) File.Delete(p);
    }

    public IEnumerable<CachedCredential> All()
    {
        if (!Directory.Exists(Dir)) yield break;
        foreach (var f in Directory.EnumerateFiles(Dir, "*.bin"))
        {
            CachedCredential? c = null;
            try
            {
                var json = Dpapi.ReadProtected(f);
                if (json is not null) c = JsonSerializer.Deserialize<CachedCredential>(json, Json.Options);
            }
            catch { /* unreadable entry: skip, it will be re-fetched */ }
            if (c is not null) yield return c;
        }
    }

    /// <summary>What to report at check-in: version held per name (-1 = locally managed).</summary>
    public Dictionary<string, int> Versions()
        => All().ToDictionary(c => c.Name, c => c.Local ? -1 : c.Version);

    /// <summary>Fetch changed/new credentials, drop ones no longer referenced. Local overrides are untouched.</summary>
    public async Task<int> SyncAsync(DashboardClient api, IReadOnlyList<CredentialRef> referenced, ILogger log, CancellationToken ct)
    {
        var changed = 0;
        var wanted = referenced.Select(r => r.Name).ToHashSet(StringComparer.Ordinal);

        foreach (var r in referenced)
        {
            var current = Get(r.Name);
            if (current?.Local == true) continue;
            if (current is not null && current.Version == r.Version) continue;
            var got = await api.GetCredentialAsync(r.Name, ct);
            Put(new CachedCredential { Name = got.Name, Kind = got.Kind, Username = got.Username, Password = got.Password, Version = got.Version });
            log.LogInformation("credential {Name} cached at v{Version}", got.Name, got.Version);
            changed++;
        }

        foreach (var c in All().ToList())
        {
            if (wanted.Contains(c.Name) || c.Local) continue;
            Remove(c.Name);
            log.LogInformation("credential {Name} is no longer referenced; removed from cache", c.Name);
        }
        return changed;
    }
}
