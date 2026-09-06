using System.Diagnostics;
using System.Security.Principal;
using System.Text;
using System.Text.Json;
using FleetScope.Agent.Api;
using FleetScope.Agent.Checks;
using FleetScope.Agent.Security;
using FleetScope.Agent.Service;
using FleetScope.Agent.Windows;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Cli;

/// <summary>Command-line surface (docs/AGENT.md §4.2).</summary>
public static class CommandLine
{
    private const string Usage = """
        FleetScope Agent

          FleetScopeAgent.exe install --url <https://dashboard> --token <enrollment token> --site "<site name>"
                                      --signing-key <base64 public key> [--service-account DOMAIN\user] [--insecure] [--no-service]
          FleetScopeAgent.exe status
          FleetScopeAgent.exe run-now
          FleetScopeAgent.exe test <check-name>
          FleetScopeAgent.exe service-account set DOMAIN\user
          FleetScopeAgent.exe credential set <name> --local
          FleetScopeAgent.exe credential list
          FleetScopeAgent.exe prereqs install [--citrix-sdk-source <path>]
          FleetScopeAgent.exe uninstall [--purge]
          FleetScopeAgent.exe run           (service loop in this console, for debugging)
          FleetScopeAgent.exe version
        """;

    public static async Task<int> RunAsync(string[] argv)
    {
        var args = Args.Parse(argv);
        try
        {
            switch (args.Command)
            {
                case null or "help" or "--help" or "-h": Console.WriteLine(Usage); return 0;
                case "version": Console.WriteLine(AgentInfo.Version); return 0;
                case "install": return await InstallAsync(args);
                case "uninstall": return Uninstall(args);
                case "status": return await StatusAsync();
                case "run-now": return RunNow();
                case "test": return await TestAsync(args);
                case "service-account": return ServiceAccount(args);
                case "credential": return Credential(args);
                case "prereqs": return Prereqs(args);
                default:
                    Console.Error.WriteLine($"unknown command '{args.Command}'");
                    Console.WriteLine(Usage);
                    return 2;
            }
        }
        catch (DashboardException ex)
        {
            Console.Error.WriteLine($"error: dashboard returned {ex.Status}: {ex.Message}");
            return 1;
        }
        catch (Exception ex)
        {
            Console.Error.WriteLine($"error: {ex.Message}");
            return 1;
        }
    }

    // ------------------------------------------------------------------ install

    private static async Task<int> InstallAsync(Args a)
    {
        var url = a.Require("url").TrimEnd('/');
        var enrollmentToken = a.Require("token");
        var site = a.Require("site");
        var signingKey = a.Require("signing-key");
        var insecure = a.Has("insecure");
        var accountOverride = a.Get("service-account");
        var sdkSource = a.Get("citrix-sdk-source");

        if (!Signing.IsPlausibleKey(signingKey))
            return Fail("--signing-key must be the base64 Ed25519 public key shown in the dashboard's install command");
        if (url.StartsWith("http://", StringComparison.OrdinalIgnoreCase) && !insecure)
            return Fail("the dashboard URL must be https:// (or pass --insecure for a lab)");
        if (!url.StartsWith("http", StringComparison.OrdinalIgnoreCase))
            return Fail("--url must start with https://");
        // --no-service: enroll and configure only, then run the loop with `FleetScopeAgent.exe run`
        // (development, or an environment with its own scheduler). No admin rights needed.
        var noService = a.Has("no-service");
        if (!noService) RequireAdmin();
        if (!PowerShellRunner.IsAvailable)
            Console.WriteLine($"WARNING: Windows PowerShell not found at {PowerShellRunner.ExePath}; checks cannot run.");

        using var log = ConsoleLogger();
        var ct = CancellationToken.None;

        // 1. directories + ACLs (SYSTEM and Administrators only; the service account is added once known)
        AgentPaths.EnsureDirs();
        if (!noService)
        {
            Exec.RunOrThrow("icacls.exe", $"\"{AgentPaths.DataDir}\" /inheritance:r /grant:r \"*S-1-5-18:(OI)(CI)F\" \"*S-1-5-32-544:(OI)(CI)F\"", "securing the data directory");

            // 2. binary
            if (ServiceManager.Exists(AgentPaths.ServiceName))
            {
                Console.WriteLine("Stopping the existing FleetScope Agent service…");
                ServiceManager.Stop(AgentPaths.ServiceName, TimeSpan.FromSeconds(60));
            }
            CopySelfToInstallDir();
        }

        // 3. enroll
        var state = new AgentState
        {
            DashboardUrl = url, Insecure = insecure, SigningKey = signingKey,
            Hostname = AgentInfo.Hostname, InstalledVersion = AgentInfo.Version,
        };
        using var api = new DashboardClient(url, insecure, AgentInfo.UserAgent);
        Console.WriteLine($"Enrolling {state.Hostname} into site \"{site}\" at {url}…");
        var enrolled = await api.EnrollAsync(enrollmentToken, site, state.Hostname, AgentInfo.Version, AgentInfo.OsVersion, ct);
        Dpapi.WriteProtected(AgentPaths.TokenFile, enrolled.AgentToken);
        api.SetToken(enrolled.AgentToken);
        state.ClientSlug = enrolled.Client.Slug; state.ClientName = enrolled.Client.Name;
        state.SiteSlug = enrolled.Site.Slug; state.SiteName = enrolled.Site.Name;
        state.CheckinSeconds = enrolled.CheckinSeconds;
        state.EnrolledAt = DateTimeOffset.UtcNow;
        state.Save();
        Console.WriteLine($"Enrolled: client \"{state.ClientName}\", site \"{state.SiteName}\".");

        // 4. first check-in: configuration, manifest, credentials
        var prerequisites = await Prerequisites.DetectAsync(ct);
        var checkin = await api.CheckinAsync(new CheckinRequest
        {
            AgentVersion = AgentInfo.Version, Hostname = state.Hostname, OsVersion = AgentInfo.OsVersion,
            Prerequisites = prerequisites,
        }, ct);
        var reason = "no manifest served";
        if (checkin.Manifest is not null && Signing.VerifyDocument(checkin.Manifest, signingKey, out reason))
            state.ManifestValid = true;
        else
        {
            state.ManifestError = reason;
            Console.WriteLine($"WARNING: the check manifest did not verify ({state.ManifestError}). The agent will enroll and check in, but will NOT run checks until the dashboard serves a manifest signed with the pinned key.");
        }
        var credentials = new CredentialCache();
        await credentials.SyncAsync(api, checkin.Credentials, log.CreateLogger("install"), ct);

        if (noService)
        {
            state.NoService = true;
            state.Save();
            Console.WriteLine();
            Console.WriteLine($"Enrolled without installing a service (data dir {AgentPaths.DataDir}).");
            PrintPrerequisites(prerequisites, checkin);
            Console.WriteLine("Run the agent loop in this console with: FleetScopeAgent.exe run");
            return 0;
        }

        // 5. service account
        string account; string? password;
        if (accountOverride is not null)
        {
            account = accountOverride;
            password = IsGmsa(account) ? null : ReadPassword($"Password for {account}: ");
            state.ServiceAccountLocal = true;
        }
        else
        {
            var name = checkin.Config.Agent.ServiceAccount;
            if (string.IsNullOrEmpty(name))
                return Fail($"no service account is configured for site \"{state.SiteName}\". In the dashboard set \"Run agent as\" on the site (a windows credential), or pass --service-account here.");
            var cred = credentials.Get(name)
                ?? throw new InvalidOperationException($"credential '{name}' was not delivered by the dashboard");
            account = cred.Username;
            password = IsGmsa(account) ? null : cred.Password;
            state.ServiceAccount = name;
            state.ServiceAccountVersion = cred.Version;
        }

        // 6. rights for the account
        Console.WriteLine($"Configuring the service to run as {account}…");
        Lsa.GrantServiceLogonRight(account);
        Exec.RunOrThrow("icacls.exe", $"\"{AgentPaths.DataDir}\" /grant \"{account}:(OI)(CI)M\"", "granting the service account access to the data directory");

        // 7. the service
        ServiceManager.CreateOrUpdate(AgentPaths.ServiceName, AgentPaths.ServiceDisplayName, $"\"{AgentPaths.ExePath}\"", account, password);
        ServiceManager.ApplyPolicies(AgentPaths.ServiceName, AgentPaths.ServiceDescription);
        ServiceAcl.GrantServiceControl(AgentPaths.ServiceName, account);
        EnsureEventSource();
        state.Save();

        // 8. prerequisites
        if (sdkSource is not null)
            Console.WriteLine("NOTE: --citrix-sdk-source is accepted but prerequisite installation ships in a later version; install the CVAD SDK from the media manually for now.");

        // 9. start
        Console.WriteLine("Starting the service…");
        ServiceManager.Start(AgentPaths.ServiceName, TimeSpan.FromSeconds(60));

        Console.WriteLine();
        Console.WriteLine($"FleetScope Agent {AgentInfo.Version} installed and running as {account}.");
        PrintPrerequisites(prerequisites, checkin);
        Console.WriteLine("The first collection runs now; results appear in the dashboard within a minute.");
        return 0;
    }

    private static void CopySelfToInstallDir()
    {
        var self = Environment.ProcessPath ?? throw new InvalidOperationException("cannot determine the running executable");
        var target = AgentPaths.ExePath;
        if (string.Equals(Path.GetFullPath(self), Path.GetFullPath(target), StringComparison.OrdinalIgnoreCase)) return;
        Directory.CreateDirectory(AgentPaths.InstallDir);
        File.Copy(self, target, overwrite: true);
        Console.WriteLine($"Installed binary to {target}");
    }

    private static void EnsureEventSource()
    {
        try
        {
            if (!EventLog.SourceExists(AgentPaths.ServiceName))
                EventLog.CreateEventSource(AgentPaths.ServiceName, "Application");
        }
        catch (Exception ex)
        {
            Console.WriteLine($"note: could not register the event log source ({ex.Message}); file logging is unaffected");
        }
    }

    private static void PrintPrerequisites(IReadOnlyDictionary<string, object?> prerequisites, CheckinResponse checkin)
    {
        Console.WriteLine("Prerequisites:");
        foreach (var kv in prerequisites)
            Console.WriteLine($"  {(kv.Value is null or false ? "[ ]" : "[x]")} {Prerequisites.Describe(kv.Key)}{(kv.Value is string s ? $"  ({s})" : "")}");
        var missing = checkin.Config.Checks.Where(c => c.Value.Enabled)
            .Select(c => (c.Key, Reqs: Collector.ParseManifest(checkin.Manifest).FirstOrDefault(e => e.Name == c.Key)?.Requires ?? new List<string>()))
            .SelectMany(c => c.Reqs.Where(r => !Prerequisites.IsMet(prerequisites, r)).Select(r => (c.Key, r)))
            .ToList();
        foreach (var (check, req) in missing)
            Console.WriteLine($"  ! check '{check}' will be skipped until '{req}' is available");
    }

    // ------------------------------------------------------------------ uninstall

    private static int Uninstall(Args a)
    {
        RequireAdmin();
        if (ServiceManager.Exists(AgentPaths.ServiceName))
        {
            Console.WriteLine("Stopping service…");
            ServiceManager.Stop(AgentPaths.ServiceName, TimeSpan.FromSeconds(60));
            ServiceManager.Delete(AgentPaths.ServiceName);
            Console.WriteLine("Service removed.");
        }
        else Console.WriteLine("Service was not installed.");

        if (a.Has("purge"))
        {
            if (Directory.Exists(AgentPaths.DataDir)) { Directory.Delete(AgentPaths.DataDir, recursive: true); Console.WriteLine($"Removed {AgentPaths.DataDir}"); }
            var self = Environment.ProcessPath ?? "";
            if (Directory.Exists(AgentPaths.InstallDir) && !self.StartsWith(AgentPaths.InstallDir, StringComparison.OrdinalIgnoreCase))
            { Directory.Delete(AgentPaths.InstallDir, recursive: true); Console.WriteLine($"Removed {AgentPaths.InstallDir}"); }
            else if (Directory.Exists(AgentPaths.InstallDir))
                Console.WriteLine($"Delete {AgentPaths.InstallDir} manually (this executable is running from it).");
        }
        else Console.WriteLine($"State and cached credentials kept in {AgentPaths.DataDir} (use --purge to remove).");
        return 0;
    }

    // ------------------------------------------------------------------ status

    private static async Task<int> StatusAsync()
    {
        var state = AgentState.Load();
        Console.WriteLine($"FleetScope Agent {AgentInfo.Version} on {AgentInfo.Hostname} ({AgentInfo.OsVersion})");
        Console.WriteLine($"  Service:          {ServiceManager.Status(AgentPaths.ServiceName)?.ToString() ?? "not installed"}");
        if (!state.IsEnrolled) { Console.WriteLine("  Enrolled:         no"); return 0; }
        Console.WriteLine($"  Dashboard:        {state.DashboardUrl}{(state.Insecure ? "  (INSECURE: TLS not verified)" : "")}");
        Console.WriteLine($"  Client / site:    {state.ClientName} / {state.SiteName}");
        Console.WriteLine($"  Enrolled:         {Fmt(state.EnrolledAt)}");
        Console.WriteLine($"  Last check-in:    {Fmt(state.LastCheckin)}{(state.LastCheckinError is null ? "" : $"  ERROR: {state.LastCheckinError}")}");
        Console.WriteLine($"  Last collection:  {Fmt(state.LastCollection)}");
        Console.WriteLine($"  Manifest:         {(state.ManifestValid ? "signed, verified" : $"REJECTED ({state.ManifestError ?? "unknown"})")}");
        Console.WriteLine($"  Service account:  {(state.ServiceAccountLocal ? "managed locally" : state.ServiceAccount is null ? "n/a" : $"{state.ServiceAccount} v{state.ServiceAccountVersion}")}{(state.RestartPending ? "  (password updated; restart pending)" : "")}");
        if (state.PendingServiceAccount is not null) Console.WriteLine($"  ! dashboard wants service account '{state.PendingServiceAccount}' — run: service-account set");
        if (state.ReleaseVersion is not null && state.ReleaseVersion != AgentInfo.Version) Console.WriteLine($"  Release:          {state.ReleaseVersion} available (self-update not enabled in this version)");
        if (state.LastRun?["checks"] is System.Text.Json.Nodes.JsonArray checks)
        {
            Console.WriteLine("  Last run:");
            foreach (var c in checks)
                Console.WriteLine($"    {c?["name"],-16} {c?["status"],-8} {(c?["durationMs"] is null ? "" : $"{c!["durationMs"]} ms")} {c?["error"] ?? ""} {string.Join(" | ", (c?["warnings"] as System.Text.Json.Nodes.JsonArray)?.Select(w => w?.ToString()) ?? Array.Empty<string>())}".TrimEnd());
        }
        var prereqs = await Prerequisites.DetectAsync(CancellationToken.None);
        Console.WriteLine("  Prerequisites:");
        foreach (var kv in prereqs)
            Console.WriteLine($"    {(kv.Value is null or false ? "[ ]" : "[x]")} {Prerequisites.Describe(kv.Key)}{(kv.Value is string s ? $"  ({s})" : "")}");
        Console.WriteLine($"  Credentials held: {string.Join(", ", new CredentialCache().Versions().Select(kv => $"{kv.Key} v{kv.Value}"))}");
        return 0;
    }

    // ------------------------------------------------------------------ run-now / test

    private static int RunNow()
    {
        var state = AgentState.Load();
        if (!state.IsEnrolled) return Fail("agent is not enrolled");
        File.WriteAllText(AgentPaths.RunNowFlag, DateTimeOffset.UtcNow.ToString("o"));
        Console.WriteLine("Collection requested; the service starts it within a few seconds.");
        return 0;
    }

    private static async Task<int> TestAsync(Args a)
    {
        var check = a.Positional.FirstOrDefault() ?? throw new ArgumentException("usage: test <check-name>");
        var state = AgentState.Load();
        var token = Dpapi.ReadProtected(AgentPaths.TokenFile);
        if (!state.IsEnrolled || token is null) return Fail("agent is not enrolled");
        using var log = ConsoleLogger();
        var ct = CancellationToken.None;

        using var api = new DashboardClient(state.DashboardUrl, state.Insecure, AgentInfo.UserAgent);
        api.SetToken(token);
        var prerequisites = await Prerequisites.DetectAsync(ct);
        var checkin = await api.CheckinAsync(new CheckinRequest
        {
            AgentVersion = AgentInfo.Version, Hostname = state.Hostname, OsVersion = AgentInfo.OsVersion, Prerequisites = prerequisites,
        }, ct);
        if (!checkin.Config.Checks.TryGetValue(check, out var cfg) || !cfg.Enabled)
            return Fail($"check '{check}' is not enabled for this site (enabled: {string.Join(", ", checkin.Config.Checks.Where(c => c.Value.Enabled).Select(c => c.Key))})");

        var credentials = new CredentialCache();
        await credentials.SyncAsync(api, checkin.Credentials, log.CreateLogger("test"), ct);
        var collector = new Collector(api, credentials, log.CreateLogger("test"));
        var result = await collector.CollectAsync(state, checkin, prerequisites, ingest: false, onlyCheck: check, ct);

        foreach (var o in result.Outcomes)
        {
            Console.WriteLine($"== {o.Name} v{o.Version}: {o.Status} ({o.DurationMs ?? 0} ms)");
            if (o.Error is not null) Console.WriteLine($"   error: {o.Error}");
            foreach (var w in o.Warnings) Console.WriteLine($"   warn:  {w}");
            if (o.Output is not null) Console.WriteLine(o.Output.ToJsonString(Json.Pretty));
        }
        if (result.ManifestError is not null) Console.WriteLine($"manifest: {result.ManifestError}");
        Console.WriteLine("(nothing was pushed to the dashboard)");
        return result.Outcomes.All(o => o.Status is "ok" or "warn") ? 0 : 1;
    }

    // ------------------------------------------------------------------ service-account / credential / prereqs

    private static int ServiceAccount(Args a)
    {
        if (a.Positional.Count < 2 || a.Positional[0] != "set") throw new ArgumentException("usage: service-account set DOMAIN\\user");
        RequireAdmin();
        var account = a.Positional[1];
        var password = IsGmsa(account) ? null : ReadPassword($"Password for {account}: ");
        Lsa.GrantServiceLogonRight(account);
        Exec.RunOrThrow("icacls.exe", $"\"{AgentPaths.DataDir}\" /grant \"{account}:(OI)(CI)M\"", "granting data directory access");
        ServiceManager.SetLogon(AgentPaths.ServiceName, account, password);
        ServiceAcl.GrantServiceControl(AgentPaths.ServiceName, account);
        var state = AgentState.Load();
        state.ServiceAccountLocal = true;
        state.PendingServiceAccount = null;
        state.RestartPending = true;
        state.Save();
        Console.WriteLine($"Service logon set to {account}. Restart the service to apply: Restart-Service {AgentPaths.ServiceName}");
        return 0;
    }

    private static int Credential(Args a)
    {
        var cache = new CredentialCache();
        switch (a.Positional.FirstOrDefault())
        {
            case "list":
                foreach (var c in cache.All()) Console.WriteLine($"{c.Name,-24} {c.Kind,-8} {c.Username,-32} {(c.Local ? "local" : $"v{c.Version}")}");
                return 0;
            case "set":
                RequireAdmin();
                var name = a.Positional.ElementAtOrDefault(1) ?? throw new ArgumentException("usage: credential set <name> --local");
                if (!a.Has("local")) return Fail("credentials are managed in the dashboard; pass --local to override this name on this agent only");
                Console.Write("Username: ");
                var user = Console.ReadLine()?.Trim() ?? "";
                var pass = ReadPassword("Password: ");
                cache.Put(new CachedCredential { Name = name, Kind = a.Get("kind") ?? "device", Username = user, Password = pass, Version = 0, Local = true });
                Console.WriteLine($"Stored local override for '{name}' (the dashboard's value is ignored for this name on this agent).");
                return 0;
            case "remove":
                RequireAdmin();
                cache.Remove(a.Positional.ElementAtOrDefault(1) ?? throw new ArgumentException("usage: credential remove <name>"));
                Console.WriteLine("Removed (a dashboard-managed credential of the same name is re-fetched at the next check-in).");
                return 0;
            default:
                throw new ArgumentException("usage: credential list | set <name> --local | remove <name>");
        }
    }

    private static int Prereqs(Args a)
    {
        Console.WriteLine("Prerequisite installation ships in a later agent version.");
        Console.WriteLine("Until then, install the CVAD PowerShell SDK from the CVAD product ISO on this VM:");
        Console.WriteLine(@"  x64\Citrix Desktop Delivery Controller\Broker_PowerShellSnapIn_x64.msi   (match the site's version)");
        Console.WriteLine("The separately downloadable \"Remote PowerShell SDK\" is the Citrix Cloud variant and does not apply.");
        return 0;
    }

    // ------------------------------------------------------------------ helpers

    private static void RequireAdmin()
    {
        using var id = WindowsIdentity.GetCurrent();
        if (!new WindowsPrincipal(id).IsInRole(WindowsBuiltInRole.Administrator))
            throw new InvalidOperationException("this command must run from an elevated (Administrator) prompt");
    }

    private static bool IsGmsa(string account) => account.TrimEnd().EndsWith('$');

    private static int Fail(string message)
    {
        Console.Error.WriteLine($"error: {message}");
        return 1;
    }

    private static string Fmt(DateTimeOffset? t) => t is null ? "never" : t.Value.ToLocalTime().ToString("yyyy-MM-dd HH:mm:ss");

    private static ILoggerFactory ConsoleLogger()
        => LoggerFactory.Create(b => b.SetMinimumLevel(LogLevel.Information).AddSimpleConsole(o => { o.SingleLine = true; o.TimestampFormat = "HH:mm:ss "; }));

    private static string ReadPassword(string prompt)
    {
        Console.Write(prompt);
        var sb = new StringBuilder();
        while (true)
        {
            var key = Console.ReadKey(intercept: true);
            if (key.Key == ConsoleKey.Enter) { Console.WriteLine(); return sb.ToString(); }
            if (key.Key == ConsoleKey.Backspace) { if (sb.Length > 0) sb.Length--; continue; }
            if (!char.IsControl(key.KeyChar)) sb.Append(key.KeyChar);
        }
    }
}

/// <summary>Tiny argument parser: <c>command [positional…] [--name value|--flag]…</c>.</summary>
internal sealed class Args
{
    public string? Command { get; private init; }
    public List<string> Positional { get; } = new();
    private readonly Dictionary<string, string?> _options = new(StringComparer.OrdinalIgnoreCase);

    public static Args Parse(string[] argv)
    {
        var a = new Args { Command = argv.Length > 0 && !argv[0].StartsWith("--") ? argv[0].ToLowerInvariant() : null };
        for (var i = a.Command is null ? 0 : 1; i < argv.Length; i++)
        {
            var tok = argv[i];
            if (tok.StartsWith("--", StringComparison.Ordinal))
            {
                var name = tok[2..];
                var eq = name.IndexOf('=');
                if (eq >= 0) { a._options[name[..eq]] = name[(eq + 1)..]; continue; }
                if (i + 1 < argv.Length && !argv[i + 1].StartsWith("--", StringComparison.Ordinal)) { a._options[name] = argv[++i]; continue; }
                a._options[name] = null;
            }
            else a.Positional.Add(tok);
        }
        return a;
    }

    public bool Has(string name) => _options.ContainsKey(name);
    public string? Get(string name) => _options.TryGetValue(name, out var v) ? v : null;
    public string Require(string name) => Get(name) ?? throw new ArgumentException($"--{name} is required");
}
