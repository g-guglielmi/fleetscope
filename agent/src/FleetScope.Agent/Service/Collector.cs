using System.Text.Json;
using System.Text.Json.Nodes;
using FleetScope.Agent.Api;
using FleetScope.Agent.Checks;
using FleetScope.Agent.Security;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Service;

public sealed class CollectionResult
{
    public DateTimeOffset At { get; init; } = DateTimeOffset.UtcNow;
    public List<CheckOutcome> Outcomes { get; } = new();
    public JsonObject? Payload { get; set; }
    public IngestResult? Ingest { get; set; }
    public bool ManifestValid { get; set; }
    public string? ManifestError { get; set; }

    /// <summary>At least one check produced results worth pushing.</summary>
    public bool Collected => Outcomes.Any(o => o.Status is "ok" or "warn");

    public JsonObject ToLastRun() => new()
    {
        ["at"] = At.UtcDateTime.ToString("o"),
        ["manifestValid"] = ManifestValid,
        ["manifestError"] = ManifestError,
        ["checks"] = new JsonArray(Outcomes.Select(o => (JsonNode?)o.ToDiagnostic()).ToArray()),
    };
}

/// <summary>One collection cycle: verify manifest, run every enabled check, push one ingest (docs/AGENT.md §4.6).</summary>
public sealed class Collector
{
    private readonly DashboardClient _api;
    private readonly CredentialCache _credentials;
    private readonly CheckRunner _runner;
    private readonly ILogger _log;

    public Collector(DashboardClient api, CredentialCache credentials, ILogger log)
    {
        _api = api;
        _credentials = credentials;
        _runner = new CheckRunner(api, log);
        _log = log;
    }

    public static List<ManifestEntry> ParseManifest(JsonObject? manifest)
        => manifest?["checks"]?.Deserialize<List<ManifestEntry>>(Json.Options) ?? new List<ManifestEntry>();

    public async Task<CollectionResult> CollectAsync(
        AgentState state, CheckinResponse checkin, IReadOnlyDictionary<string, object?> prerequisites,
        bool ingest, string? onlyCheck, CancellationToken ct)
    {
        var result = new CollectionResult();

        if (checkin.Manifest is null)
            result.ManifestError = "the dashboard returned no check manifest";
        else if (!Signing.VerifyDocument(checkin.Manifest, state.SigningKey, out var reason))
            result.ManifestError = $"check manifest rejected: {reason}";
        else
            result.ManifestValid = true;

        var entries = ParseManifest(checkin.Manifest);

        foreach (var (name, cfg) in checkin.Config.Checks)
        {
            if (!cfg.Enabled) continue;
            if (onlyCheck is not null && !name.Equals(onlyCheck, StringComparison.OrdinalIgnoreCase)) continue;

            var entry = entries.FirstOrDefault(e => e.Name == name);
            if (entry is null)
            {
                result.Outcomes.Add(new CheckOutcome { Name = name, Version = "", Error = "enabled in the site configuration but not present in the manifest" });
                continue;
            }
            if (result.ManifestError is not null)
            {
                result.Outcomes.Add(new CheckOutcome { Name = name, Version = entry.Version, Error = result.ManifestError });
                continue;
            }

            var unmet = entry.Requires.Where(r => !Prerequisites.IsMet(prerequisites, r)).ToList();
            if (unmet.Count > 0)
            {
                var o = new CheckOutcome { Name = name, Version = entry.Version, Status = "skipped" };
                foreach (var r in unmet) o.Warnings.Add($"requirement '{r}' not met on {state.Hostname}: {Prerequisites.Describe(r)}");
                result.Outcomes.Add(o);
                continue;
            }

            try
            {
                var path = await _runner.EnsureModuleAsync(entry, ct);
                var input = BuildInput(state, name, cfg.Settings);
                result.Outcomes.Add(await _runner.RunAsync(entry, path, input, ct));
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
            catch (Exception ex)
            {
                _log.LogError(ex, "check {Name} failed to run", name);
                result.Outcomes.Add(new CheckOutcome { Name = name, Version = entry.Version, Error = ex.Message });
            }
        }

        result.Payload = BuildPayload(state, result);
        if (ingest && result.Collected)
            result.Ingest = await _api.IngestAsync(result.Payload, ct);
        return result;
    }

    /// <summary>Names every <c>credential</c> value inside a check's settings refers to.</summary>
    internal static HashSet<string> ReferencedCredentials(JsonNode? settings)
    {
        var names = new HashSet<string>(StringComparer.Ordinal);
        Walk(settings);
        return names;

        void Walk(JsonNode? node)
        {
            switch (node)
            {
                case JsonObject o:
                    foreach (var kv in o)
                    {
                        if (kv.Key == "credential" && kv.Value is JsonValue v && v.TryGetValue<string>(out var s) && s.Length > 0)
                            names.Add(s);
                        else
                            Walk(kv.Value);
                    }
                    break;
                case JsonArray a:
                    foreach (var item in a) Walk(item);
                    break;
            }
        }
    }

    private JsonObject BuildInput(AgentState state, string check, JsonObject? settings)
    {
        var creds = new JsonObject();
        foreach (var name in ReferencedCredentials(settings))
        {
            var c = _credentials.Get(name);
            if (c is null)
            {
                _log.LogWarning("check {Check} references credential {Name} which is not cached yet", check, name);
                continue;
            }
            creds[name] = new JsonObject { ["username"] = c.Username, ["password"] = c.Password };
        }
        return new JsonObject
        {
            ["schema"] = 1,
            ["check"] = check,
            ["site"] = new JsonObject { ["client"] = state.ClientName, ["site"] = state.SiteName },
            ["settings"] = settings?.DeepClone() ?? new JsonObject(),
            ["credentials"] = creds,
        };
    }

    private static JsonObject BuildPayload(AgentState state, CollectionResult result)
    {
        var components = new JsonArray();
        var certificates = new JsonArray();
        var licenses = new JsonArray();
        foreach (var o in result.Outcomes)
        {
            if (o.Output is null) continue;
            Append(components, o.Output["components"]);
            Append(certificates, o.Output["certificates"]);
            Append(licenses, o.Output["licenses"]);
        }
        return new JsonObject
        {
            ["collectorVersion"] = AgentInfo.Version,
            ["client"] = state.ClientName,
            ["site"] = state.SiteName ?? state.SiteSlug,
            ["probe"] = state.Hostname,
            ["collectedAt"] = result.At.UtcDateTime.ToString("o"),
            ["components"] = components,
            ["certificates"] = certificates,
            ["licenses"] = licenses,
            ["diagnostics"] = new JsonArray(result.Outcomes.Select(o => (JsonNode?)o.ToDiagnostic()).ToArray()),
        };

        static void Append(JsonArray target, JsonNode? source)
        {
            if (source is not JsonArray arr) return;
            foreach (var item in arr)
                if (item is not null) target.Add(item.DeepClone());
        }
    }
}
