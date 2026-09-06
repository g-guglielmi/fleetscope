using System.Text.Json.Nodes;
using FleetScope.Agent.Api;
using FleetScope.Agent.Checks;
using FleetScope.Agent.Security;
using FleetScope.Agent.Windows;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Service;

/// <summary>
/// The service loop (docs/AGENT.md §4.6): check in every few minutes, keep the
/// credential cache, the service logon and the binary itself in sync with the
/// dashboard, and run a collection when it is due or requested.
/// </summary>
public sealed class AgentWorker : BackgroundService
{
    private static readonly TimeSpan PrerequisiteRefresh = TimeSpan.FromMinutes(30);
    private readonly ILogger<AgentWorker> _log;

    private readonly DateTimeOffset _startedAt = DateTimeOffset.UtcNow;
    private bool _awaitingUpdateConfirm;
    private bool _logonUpdateFailed;
    private bool _prereqInstallAttempted;
    private string? _lastUpdateReason;

    public AgentWorker(ILogger<AgentWorker> log) => _log = log;

    protected override async Task ExecuteAsync(CancellationToken ct)
    {
        try
        {
            await RunAsync(ct);
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { }
        catch (Exception ex)
        {
            _log.LogCritical(ex, "agent loop crashed");
            Environment.ExitCode = 1;
            throw;
        }
    }

    private async Task RunAsync(CancellationToken ct)
    {
        AgentPaths.EnsureDirs();
        _log.LogInformation("FleetScope Agent {Version} starting (data dir {Dir})", AgentInfo.Version, AgentPaths.DataDir);

        var state = AgentState.Load();
        HandleUpdateMarker(state);

        var token = ReadToken();
        if (!state.IsEnrolled || token is null)
        {
            _log.LogError("agent is not enrolled — run: FleetScopeAgent.exe install --url <dashboard> --token <enrollment token> --site <site> --signing-key <key>");
            while (!ct.IsCancellationRequested) await Task.Delay(TimeSpan.FromMinutes(5), ct);
            return;
        }
        if (!PowerShellRunner.IsAvailable)
            _log.LogError("Windows PowerShell not found at {Path}; no check can run", PowerShellRunner.ExePath);

        using var api = new DashboardClient(state.DashboardUrl, state.Insecure, AgentInfo.UserAgent);
        api.SetToken(token);
        var credentials = new CredentialCache();
        var collector = new Collector(api, credentials, _log);

        var prerequisites = new Dictionary<string, object?>();
        var prerequisitesAt = DateTimeOffset.MinValue;

        while (!ct.IsCancellationRequested)
        {
            var now = DateTimeOffset.UtcNow;
            var restartRequested = false;
            try
            {
                if (now - prerequisitesAt > PrerequisiteRefresh)
                {
                    prerequisites = await Prerequisites.DetectAsync(ct);
                    prerequisitesAt = now;
                    _log.LogInformation("prerequisites: {Prereqs}",
                        string.Join(", ", prerequisites.Select(kv => $"{kv.Key}={kv.Value ?? "missing"}")));
                }

                var checkin = await api.CheckinAsync(new CheckinRequest
                {
                    AgentVersion = AgentInfo.Version,
                    Hostname = state.Hostname,
                    OsVersion = AgentInfo.OsVersion,
                    Prerequisites = prerequisites,
                    CredentialVersions = credentials.Versions(),
                    LastRun = state.LastRun?.DeepClone(),
                }, ct);

                state.LastCheckin = now;
                state.LastCheckinError = null;
                state.CheckinSeconds = Math.Clamp(checkin.CheckinSeconds, 30, 3600);
                if (checkin.Client is not null) { state.ClientSlug = checkin.Client.Slug; state.ClientName = checkin.Client.Name; }
                if (checkin.Site is not null) { state.SiteSlug = checkin.Site.Slug; state.SiteName = checkin.Site.Name; }
                state.ReleaseVersion = checkin.Release?["version"]?.GetValue<string>();

                ConfirmUpdateIfPending(state);

                if (checkin.Manifest is null)
                    (state.ManifestValid, state.ManifestError) = (false, "no manifest served");
                else if (Signing.VerifyDocument(checkin.Manifest, state.SigningKey, out var reason))
                    (state.ManifestValid, state.ManifestError) = (true, null);
                else
                {
                    if (state.ManifestValid || state.ManifestError != reason)
                        _log.LogError("check manifest REJECTED ({Reason}); checks will not run until the dashboard serves a manifest signed with the pinned key", reason);
                    (state.ManifestValid, state.ManifestError) = (false, reason);
                }

                await credentials.SyncAsync(api, checkin.Credentials, _log, ct);
                ApplyServiceAccount(state, checkin, credentials);
                await MaybeInstallPrerequisitesAsync(checkin, prerequisites, ct);

                if (await MaybeUpdateAsync(api, state, checkin, ct))
                {
                    await Task.Delay(500, CancellationToken.None);
                    Environment.Exit(UpdateManager.RestartExitCode);
                }

                var runNow = checkin.Actions.Contains("run-now") || ConsumeRunNowFlag();
                restartRequested = checkin.Actions.Contains("restart");
                var interval = TimeSpan.FromMinutes(Math.Max(15, checkin.Config.IntervalMinutes));
                var due = state.LastCollection is null || now - state.LastCollection.Value >= interval;

                if (runNow || due)
                {
                    _log.LogInformation("collection starting ({Reason})", runNow ? "requested" : "scheduled");
                    var result = await collector.CollectAsync(state, checkin, prerequisites, ingest: true, onlyCheck: null, ct);
                    state.LastCollection = now;
                    state.LastRun = result.ToLastRun();
                    foreach (var o in result.Outcomes)
                        _log.Log(o.Status is "ok" ? LogLevel.Information : LogLevel.Warning,
                            "check {Name}: {Status} in {Ms} ms{Detail}", o.Name, o.Status, o.DurationMs ?? 0,
                            o.Error is not null ? $" — {o.Error}" : o.Warnings.Count > 0 ? $" — {string.Join(" | ", o.Warnings)}" : "");
                    if (result.Ingest is not null)
                        _log.LogInformation("ingest ok: snapshot {Snapshot}, {Components} components, {Certs} certificates, {Lic} licenses, {Findings} findings",
                            result.Ingest.SnapshotId, result.Ingest.Components, result.Ingest.Certificates, result.Ingest.Licenses, result.Ingest.Findings);
                    else
                        _log.LogWarning("no check produced results; inventory left untouched, diagnostics reported at next check-in");
                }

                state.Save();
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested) { break; }
            catch (DashboardException ex) when (ex.Status == 401)
            {
                _log.LogError("the dashboard rejected this agent's token (401). It may have been revoked — re-run install with a new enrollment token.");
                state.LastCheckinError = "401 unauthorized";
                TrySave(state);
                MaybeRollback(state);
            }
            catch (Exception ex)
            {
                _log.LogError(ex, "check-in cycle failed");
                state.LastCheckinError = ex.Message;
                TrySave(state);
                MaybeRollback(state);
            }

            if (restartRequested)
            {
                _log.LogWarning("restart requested from the dashboard; exiting so the service recovery policy restarts the agent");
                await Task.Delay(500, CancellationToken.None);
                Environment.Exit(UpdateManager.RestartExitCode);
            }

            await SleepAsync(TimeSpan.FromSeconds(state.CheckinSeconds), ct);
        }
    }

    // ------------------------------------------------------------------ self-update

    /// <summary>On startup: are we a freshly swapped-in binary, or the survivor of a rollback?</summary>
    private void HandleUpdateMarker(AgentState state)
    {
        var marker = UpdateManager.LoadMarker();
        if (marker is null)
        {
            // No update in flight: stray leftovers are from a confirmed update whose delete raced a lock.
            if (File.Exists(UpdateManager.OldPath) || File.Exists(UpdateManager.FailedPath))
                UpdateManager.Cleanup();
            return;
        }
        if (marker.ToVersion == AgentInfo.Version)
        {
            _awaitingUpdateConfirm = true;
            _log.LogInformation("running freshly updated {Version} (from {From}); confirming after the first successful check-in", AgentInfo.Version, marker.FromVersion);
            return;
        }
        // We are not the version the update aimed for: it was rolled back, or the new binary never ran.
        _log.LogError("update to {To} did not take effect; running {Current} again", marker.ToVersion, AgentInfo.Version);
        state.LastUpdateNote = $"update to {marker.ToVersion} failed and was rolled back at {DateTimeOffset.UtcNow:u}";
        UpdateManager.Cleanup();
        TrySave(state);
    }

    private void ConfirmUpdateIfPending(AgentState state)
    {
        if (!_awaitingUpdateConfirm) return;
        _awaitingUpdateConfirm = false;
        UpdateManager.Cleanup();
        state.LastUpdateNote = $"updated to {AgentInfo.Version} at {DateTimeOffset.UtcNow:u}";
        _log.LogInformation("update to {Version} confirmed", AgentInfo.Version);
    }

    /// <summary>An unconfirmed update whose check-ins keep failing is rolled back after the deadline.</summary>
    private void MaybeRollback(AgentState state)
    {
        if (!_awaitingUpdateConfirm || DateTimeOffset.UtcNow - _startedAt < UpdateManager.ConfirmDeadline) return;
        _log.LogCritical("no successful check-in within {Minutes} minutes of updating to {Version}; rolling back to the previous binary",
            UpdateManager.ConfirmDeadline.TotalMinutes, AgentInfo.Version);
        try
        {
            if (UpdateManager.RollbackToOld(AgentPaths.ExePath))
            {
                // Marker stays: the restored binary logs the failure and cleans up.
                Environment.Exit(UpdateManager.RestartExitCode);
            }
            _log.LogError("rollback impossible: the previous binary is gone; continuing on {Version}", AgentInfo.Version);
        }
        catch (Exception ex)
        {
            _log.LogError(ex, "rollback failed; continuing on {Version}", AgentInfo.Version);
        }
        _awaitingUpdateConfirm = false;
        UpdateManager.DeleteMarker();
        state.LastUpdateNote = $"update to {AgentInfo.Version} unconfirmed and rollback impossible at {DateTimeOffset.UtcNow:u}";
        TrySave(state);
    }

    /// <summary>Returns true when the binary was swapped and the process must exit for restart.</summary>
    private async Task<bool> MaybeUpdateAsync(DashboardClient api, AgentState state, CheckinResponse checkin, CancellationToken ct)
    {
        if (_awaitingUpdateConfirm) return false;  // never chain updates before confirming the last one
        // Console (`--no-service`) agents have no SCM to restart them; opt-in for tests.
        if (state.NoService && !EnvTruthy("FLEETSCOPE_UPDATE_IN_CONSOLE")) return false;

        var processPath = Environment.ProcessPath ?? "";
        var fromInstallDir = processPath.Length > 0 &&
            string.Equals(Path.GetFullPath(processPath), Path.GetFullPath(AgentPaths.ExePath), StringComparison.OrdinalIgnoreCase);

        var (go, reason) = UpdateManager.Decide(checkin.Release, state.SigningKey, AgentInfo.Version, checkin.Config.AutoUpdate, fromInstallDir);
        if (!go)
        {
            if (reason is not ("up to date" or "no release published") && reason != _lastUpdateReason)
            {
                _log.LogWarning("{Reason}", reason);
                _lastUpdateReason = reason;
            }
            return false;
        }

        _log.LogInformation("{Reason}", reason);
        try
        {
            await UpdateManager.ApplyAsync(api, checkin.Release!, _log, ct);
            state.LastUpdateNote = $"updating to {state.ReleaseVersion} at {DateTimeOffset.UtcNow:u}";
            state.Save();
            return true;
        }
        catch (OperationCanceledException) when (ct.IsCancellationRequested) { throw; }
        catch (Exception ex)
        {
            _log.LogError(ex, "self-update failed; staying on {Version}", AgentInfo.Version);
            state.LastUpdateNote = $"update to {state.ReleaseVersion} failed at {DateTimeOffset.UtcNow:u}: {ex.Message}";
            return false;
        }
    }

    private static bool EnvTruthy(string name)
        => Environment.GetEnvironmentVariable(name) is "1" or "true" or "TRUE" or "True";

    // ------------------------------------------------------------------ prerequisites (unattended)

    /// <summary>docs/AGENT.md §4.8: install the CVAD SDK from configured media when the site opts in.</summary>
    private async Task MaybeInstallPrerequisitesAsync(CheckinResponse checkin, Dictionary<string, object?> prerequisites, CancellationToken ct)
    {
        if (_prereqInstallAttempted) return;
        var cfg = checkin.Config.Prerequisites;
        if (cfg?["unattended"]?.GetValue<bool>() != true) return;
        var source = cfg["citrixSdkSource"]?.GetValue<string>();
        if (string.IsNullOrWhiteSpace(source)) return;
        if (Prerequisites.IsMet(prerequisites, Prerequisites.CvadSdk)) return;

        _prereqInstallAttempted = true;  // once per process; a restart retries
        _log.LogWarning("attempting unattended CVAD SDK install from {Source}", source);
        var (ok, message) = PrereqInstaller.InstallCvadSdk(source);
        _log.Log(ok ? LogLevel.Information : LogLevel.Error, "unattended CVAD SDK install: {Message}", message);
        if (ok)
        {
            var refreshed = await Prerequisites.DetectAsync(ct);
            prerequisites.Clear();
            foreach (var kv in refreshed) prerequisites[kv.Key] = kv.Value;
        }
    }

    // ------------------------------------------------------------------ service account

    /// <summary>
    /// Keeps the Windows service logon in sync with the dashboard-managed service
    /// account (docs/AGENT.md §4.4): a new password version is written to the SCM
    /// without restarting; a different account needs an elevated local change.
    /// </summary>
    private void ApplyServiceAccount(AgentState state, CheckinResponse checkin, CredentialCache credentials)
    {
        if (state.ServiceAccountLocal || state.NoService) return;
        var name = checkin.Config.Agent.ServiceAccount;
        if (string.IsNullOrEmpty(name)) return;
        var cred = credentials.Get(name);
        if (cred is null) return;

        if (state.ServiceAccount is not null && state.ServiceAccount != name)
        {
            if (state.PendingServiceAccount != name)
                _log.LogWarning("dashboard changed the service account from {Old} to {New}; run (elevated) FleetScopeAgent.exe service-account set {User}",
                    state.ServiceAccount, name, cred.Username);
            state.PendingServiceAccount = name;
            return;
        }
        if (state.ServiceAccountVersion == cred.Version) return;
        if (cred.Username.TrimEnd().EndsWith('$'))
        {
            state.ServiceAccount = name;
            state.ServiceAccountVersion = cred.Version;
            return; // gMSA: nothing to rotate
        }
        if (!ServiceManager.Exists(AgentPaths.ServiceName)) return;
        try
        {
            ServiceManager.SetLogon(AgentPaths.ServiceName, cred.Username, cred.Password);
            state.ServiceAccount = name;
            state.ServiceAccountVersion = cred.Version;
            state.RestartPending = true;
            _logonUpdateFailed = false;
            _log.LogWarning("service logon password updated to credential {Name} v{Version}; it takes effect at the next agent restart", name, cred.Version);
        }
        catch (Exception ex)
        {
            if (!_logonUpdateFailed)
                _log.LogError(ex, "could not update the service logon password (the account needs change-config rights on the service; re-run install)");
            _logonUpdateFailed = true;
        }
    }

    // ------------------------------------------------------------------ misc

    private static string? ReadToken()
    {
        try { return Dpapi.ReadProtected(AgentPaths.TokenFile); }
        catch { return null; }
    }

    private static bool ConsumeRunNowFlag()
    {
        if (!File.Exists(AgentPaths.RunNowFlag)) return false;
        try { File.Delete(AgentPaths.RunNowFlag); } catch { }
        return true;
    }

    private void TrySave(AgentState state)
    {
        try { state.Save(); } catch (Exception ex) { _log.LogError(ex, "could not save state"); }
    }

    /// <summary>Sleeps in short slices so a local <c>run-now</c> is picked up quickly.</summary>
    private static async Task SleepAsync(TimeSpan total, CancellationToken ct)
    {
        var deadline = DateTimeOffset.UtcNow + total;
        while (DateTimeOffset.UtcNow < deadline && !ct.IsCancellationRequested)
        {
            if (File.Exists(AgentPaths.RunNowFlag)) return;
            var remaining = deadline - DateTimeOffset.UtcNow;
            await Task.Delay(remaining < TimeSpan.FromSeconds(5) ? remaining : TimeSpan.FromSeconds(5), ct);
        }
    }
}
