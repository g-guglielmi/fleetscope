using System.Text.Json;
using System.Text.Json.Nodes;
using FleetScope.Agent.Api;
using FleetScope.Agent.Security;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Service;

/// <summary>Written when the binary is swapped; the next process uses it to confirm or roll back.</summary>
public sealed class UpdateMarker
{
    public string FromVersion { get; set; } = "";
    public string ToVersion { get; set; } = "";
    public DateTimeOffset At { get; set; }
}

/// <summary>
/// Self-update (docs/AGENT.md §4.7): the check-in carries a signed release descriptor;
/// when it names a newer version and the site allows auto-update, the running binary is
/// renamed aside, the verified download takes its place, and the process exits so the
/// service recovery policy restarts it. The new process confirms by checking in once;
/// if it cannot within <see cref="ConfirmDeadline"/>, it swaps the old binary back.
/// </summary>
public static class UpdateManager
{
    /// <summary>10 minutes; FLEETSCOPE_CONFIRM_DEADLINE_SECONDS shortens it for tests.</summary>
    public static readonly TimeSpan ConfirmDeadline =
        int.TryParse(Environment.GetEnvironmentVariable("FLEETSCOPE_CONFIRM_DEADLINE_SECONDS"), out var s) && s > 0
            ? TimeSpan.FromSeconds(s)
            : TimeSpan.FromMinutes(10);
    /// <summary>Exit code that asks the SCM recovery policy (or the operator) for a restart.</summary>
    public const int RestartExitCode = 3;

    public static string OldPath => AgentPaths.ExePath + ".old";
    public static string FailedPath => AgentPaths.ExePath + ".failed";

    // ---- marker ----

    public static UpdateMarker? LoadMarker()
    {
        if (!File.Exists(AgentPaths.UpdateMarker)) return null;
        try { return JsonSerializer.Deserialize<UpdateMarker>(File.ReadAllText(AgentPaths.UpdateMarker), Json.Options); }
        catch (JsonException) { return null; }
    }

    public static void SaveMarker(UpdateMarker m)
        => File.WriteAllText(AgentPaths.UpdateMarker, JsonSerializer.Serialize(m, Json.Pretty));

    public static void DeleteMarker()
    {
        if (File.Exists(AgentPaths.UpdateMarker)) TryDelete(AgentPaths.UpdateMarker);
    }

    // ---- decision ----

    /// <summary>"1.2.3", "v1.2.3", "0.2.0-dev", "1.2.3+abc" all parse; garbage returns null.</summary>
    public static Version? ParseVersion(string? s)
    {
        if (string.IsNullOrWhiteSpace(s)) return null;
        s = s.Trim().TrimStart('v', 'V');
        var cut = s.IndexOfAny(new[] { '-', '+' });
        if (cut > 0) s = s[..cut];
        if (!s.Contains('.')) s += ".0";
        return Version.TryParse(s, out var v) ? v : null;
    }

    public static (bool Go, string Reason) Decide(
        JsonObject? release, string signingKey, string currentVersion, bool autoUpdate, bool runningFromInstallDir)
    {
        if (release is null) return (false, "no release published");
        var ver = release["version"]?.GetValue<string>();
        var target = ParseVersion(ver);
        if (target is null) return (false, $"release version '{ver}' is not parseable");
        var current = ParseVersion(currentVersion);
        if (current is not null && target <= current) return (false, "up to date");
        if (!autoUpdate) return (false, $"update {ver} available but auto-update is off for this site");
        if (!runningFromInstallDir) return (false, $"update {ver} available but the agent is not running from {AgentPaths.ExePath}");
        if (!Signing.VerifyDocument(release, signingKey, out var why))
            return (false, $"update {ver} REFUSED: {why}");
        return (true, $"updating {currentVersion} -> {ver}");
    }

    // ---- apply ----

    /// <summary>Download, verify against the signed descriptor, swap, write the marker. Caller exits afterwards.</summary>
    public static async Task ApplyAsync(DashboardClient api, JsonObject release, ILogger log, CancellationToken ct)
    {
        var version = release["version"]!.GetValue<string>();
        var expected = release["sha256"]?.GetValue<string>() ?? "";
        Directory.CreateDirectory(AgentPaths.UpdatesDir);
        var staged = Path.Combine(AgentPaths.UpdatesDir, $"FleetScopeAgent.{version}.exe");

        log.LogInformation("downloading agent {Version}…", version);
        await api.DownloadReleaseAsync(staged, ct);
        var actual = Signing.Sha256Hex(await File.ReadAllBytesAsync(staged, ct));
        if (!actual.Equals(expected, StringComparison.OrdinalIgnoreCase))
        {
            TryDelete(staged);
            throw new InvalidOperationException(
                $"downloaded agent sha256 {actual[..12]}… does not match the signed release {expected[..12]}…; refusing the update");
        }

        SwapNewBinary(AgentPaths.ExePath, staged);
        SaveMarker(new UpdateMarker { FromVersion = AgentInfo.Version, ToVersion = version, At = DateTimeOffset.UtcNow });
        log.LogWarning("agent binary replaced with {Version}; exiting so the service restarts on the new build", version);
    }

    /// <summary>Rename the (possibly running — Windows allows it) exe aside, move the staged binary into place.</summary>
    public static void SwapNewBinary(string exePath, string stagedPath)
    {
        var old = exePath + ".old";
        if (File.Exists(old)) File.Delete(old);
        File.Move(exePath, old);
        try
        {
            File.Move(stagedPath, exePath);
        }
        catch
        {
            File.Move(old, exePath);   // undo, we are still the valid binary
            throw;
        }
    }

    /// <summary>The unconfirmed new binary puts itself aside and restores the previous one.</summary>
    public static bool RollbackToOld(string exePath)
    {
        var old = exePath + ".old";
        if (!File.Exists(old)) return false;
        var failed = exePath + ".failed";
        if (File.Exists(failed)) File.Delete(failed);
        File.Move(exePath, failed);
        try
        {
            File.Move(old, exePath);
        }
        catch
        {
            File.Move(failed, exePath);
            throw;
        }
        return true;
    }

    /// <summary>Drop marker, leftovers and staged downloads (after a confirm, or when cleaning a failed update).</summary>
    public static void Cleanup()
    {
        DeleteMarker();
        TryDelete(OldPath);
        TryDelete(FailedPath);
        if (Directory.Exists(AgentPaths.UpdatesDir))
            foreach (var f in Directory.EnumerateFiles(AgentPaths.UpdatesDir, "FleetScopeAgent.*.exe"))
                TryDelete(f);
    }

    private static void TryDelete(string path)
    {
        try { if (File.Exists(path)) File.Delete(path); } catch { /* e.g. still locked; next confirm retries */ }
    }
}
