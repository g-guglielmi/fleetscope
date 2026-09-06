using FleetScope.Agent.Api;
using FleetScope.Agent.Checks;
using FleetScope.Agent.Security;
using FleetScope.Agent.Windows;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Service;

/// <summary>
/// The service loop (docs/AGENT.md §4.6): check in every few minutes, keep the
/// credential cache and the service logon in sync, and run a collection when it
/// is due or requested.
/// </summary>
public sealed class AgentWorker : BackgroundService
{
    private static readonly TimeSpan PrerequisiteRefresh = TimeSpan.FromMinutes(30);
    private readonly ILogger<AgentWorker> _log;

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
            }
            catch (Exception ex)
            {
                _log.LogError(ex, "check-in cycle failed");
                state.LastCheckinError = ex.Message;
                TrySave(state);
            }

            if (restartRequested)
            {
                _log.LogWarning("restart requested from the dashboard; exiting so the service recovery policy restarts the agent");
                await Task.Delay(500, CancellationToken.None);
                Environment.Exit(3);
            }

            await SleepAsync(TimeSpan.FromSeconds(state.CheckinSeconds), ct);
        }
    }

    /// <summary>
    /// Keeps the Windows service logon in sync with the dashboard-managed service
    /// account (docs/AGENT.md §4.4): a new password version is written to the SCM
    /// without restarting; a different account needs an elevated local change.
    /// </summary>
    private bool _logonUpdateFailed;

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
