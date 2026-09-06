using System.Text.Json.Nodes;
using FleetScope.Agent.Api;
using FleetScope.Agent.Security;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Checks;

public sealed class CheckOutcome
{
    public string Name { get; init; } = "";
    public string Version { get; init; } = "";
    public string Status { get; set; } = "error";  // ok | warn | error | skipped
    public long? DurationMs { get; set; }
    public List<string> Warnings { get; } = new();
    public string? Error { get; set; }
    public JsonObject? Output { get; set; }

    public JsonObject ToDiagnostic() => new()
    {
        ["name"] = Name,
        ["version"] = Version,
        ["status"] = Status,
        ["durationMs"] = DurationMs,
        ["warnings"] = new JsonArray(Warnings.Select(w => (JsonNode?)w).ToArray()),
        ["error"] = Error,
    };
}

/// <summary>Caches, verifies and executes check modules (docs/AGENT.md §5).</summary>
public sealed class CheckRunner
{
    private readonly DashboardClient _api;
    private readonly ILogger _log;

    public CheckRunner(DashboardClient api, ILogger log)
    {
        _api = api;
        _log = log;
    }

    /// <summary>Returns the path of a cached module whose SHA-256 matches the manifest, downloading if needed.</summary>
    public async Task<string> EnsureModuleAsync(ManifestEntry entry, CancellationToken ct)
    {
        var dir = Path.Combine(AgentPaths.ChecksDir, Safe(entry.Name), Safe(entry.Version));
        var path = Path.Combine(dir, "check.ps1");
        if (File.Exists(path) && Signing.Sha256Hex(await File.ReadAllBytesAsync(path, ct)) == entry.Sha256)
            return path;

        var (body, _) = await _api.GetCheckAsync(entry.Name, ct);
        var actual = Signing.Sha256Hex(body);
        if (!string.Equals(actual, entry.Sha256, StringComparison.OrdinalIgnoreCase))
            throw new InvalidOperationException(
                $"check '{entry.Name}' downloaded with sha256 {actual[..12]}… but the signed manifest says {entry.Sha256[..12]}…; refusing to run it");

        Directory.CreateDirectory(dir);
        await File.WriteAllBytesAsync(path, body, ct);
        _log.LogInformation("check {Name} v{Version} cached ({Bytes} bytes)", entry.Name, entry.Version, body.Length);
        return path;
    }

    public async Task<CheckOutcome> RunAsync(ManifestEntry entry, string path, JsonObject input, CancellationToken ct)
    {
        var outcome = new CheckOutcome { Name = entry.Name, Version = entry.Version };

        // Verify the exact bytes right before execution: the cache is not trusted either.
        if (Signing.Sha256Hex(await File.ReadAllBytesAsync(path, ct)) != entry.Sha256)
        {
            outcome.Error = "cached module no longer matches the signed manifest";
            return outcome;
        }

        var timeout = TimeSpan.FromSeconds(Math.Max(30, entry.TimeoutSeconds));
        var r = await PowerShellRunner.RunFileAsync(path, input.ToJsonString(Json.Options), timeout, ct);
        outcome.DurationMs = (long)r.Duration.TotalMilliseconds;

        if (r.TimedOut)
        {
            outcome.Error = $"timed out after {entry.TimeoutSeconds}s";
            return outcome;
        }

        var json = ExtractJson(r.StdOut);
        if (json is null)
        {
            outcome.Error = $"exit code {r.ExitCode}, no JSON on stdout. stderr: {Tail(r.StdErr)}";
            return outcome;
        }
        json.Remove("credentials");  // defensive: never let a secret echo back into the inventory
        outcome.Output = json;

        if (json["warnings"] is JsonArray warnings)
            foreach (var w in warnings)
                if (w is not null) outcome.Warnings.Add(w.ToString());

        if (r.ExitCode == 0)
            outcome.Status = outcome.Warnings.Count > 0 ? "warn" : "ok";
        else
        {
            outcome.Status = "error";
            outcome.Error = r.ExitCode == 2
                ? "no target could be queried"
                : $"exit code {r.ExitCode}: {Tail(r.StdErr)}";
        }
        return outcome;
    }

    /// <summary>The check's JSON is the last object on stdout; tolerate stray text before it.</summary>
    internal static JsonObject? ExtractJson(string stdout)
    {
        if (string.IsNullOrWhiteSpace(stdout)) return null;
        var first = stdout.IndexOf('{');
        if (first >= 0)
        {
            try { if (JsonNode.Parse(stdout[first..].Trim()) is JsonObject o) return o; } catch { }
        }
        // Enumerable.Reverse spelled out: on newer compilers array.Reverse() binds to the
        // void MemoryExtensions.Reverse(Span<T>) overload instead.
        foreach (var line in Enumerable.Reverse(stdout.Split('\n')))
        {
            var t = line.Trim();
            if (!t.StartsWith('{')) continue;
            try { if (JsonNode.Parse(t) is JsonObject o) return o; } catch { }
        }
        return null;
    }

    private static string Tail(string s, int max = 400)
    {
        s = s.Trim();
        return s.Length <= max ? s : "…" + s[^max..];
    }

    private static string Safe(string s) => string.Concat(s.Where(c => char.IsLetterOrDigit(c) || c is '-' or '_' or '.'));
}
