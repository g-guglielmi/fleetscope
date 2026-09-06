using System.Diagnostics;
using System.Text;

namespace FleetScope.Agent.Checks;

public sealed record PsResult(int ExitCode, string StdOut, string StdErr, bool TimedOut, TimeSpan Duration);

/// <summary>
/// Runs Windows PowerShell 5.1 (the CVAD SDK's host) as a child process. Input goes
/// over stdin, results come back on stdout; a hung check is killed with its tree.
/// </summary>
public static class PowerShellRunner
{
    public static string ExePath =>
        Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.System), "WindowsPowerShell", "v1.0", "powershell.exe");

    public static bool IsAvailable => File.Exists(ExePath);

    public static Task<PsResult> RunFileAsync(string scriptPath, string stdin, TimeSpan timeout, CancellationToken ct)
        => RunAsync($"-NoProfile -NonInteractive -ExecutionPolicy Bypass -File \"{scriptPath}\"", stdin, timeout, ct);

    public static Task<PsResult> RunScriptAsync(string script, TimeSpan timeout, CancellationToken ct)
    {
        var encoded = Convert.ToBase64String(Encoding.Unicode.GetBytes(script));
        return RunAsync($"-NoProfile -NonInteractive -ExecutionPolicy Bypass -EncodedCommand {encoded}", null, timeout, ct);
    }

    private static async Task<PsResult> RunAsync(string arguments, string? stdin, TimeSpan timeout, CancellationToken ct)
    {
        var utf8 = new UTF8Encoding(false);
        var psi = new ProcessStartInfo(ExePath, arguments)
        {
            RedirectStandardInput = stdin is not null,
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
            StandardOutputEncoding = utf8,
            StandardErrorEncoding = utf8,
        };
        if (stdin is not null) psi.StandardInputEncoding = utf8;

        var sw = Stopwatch.StartNew();
        using var p = new Process { StartInfo = psi };
        p.Start();

        var stdoutTask = p.StandardOutput.ReadToEndAsync(ct);
        var stderrTask = p.StandardError.ReadToEndAsync(ct);
        if (stdin is not null)
        {
            await p.StandardInput.WriteAsync(stdin);
            p.StandardInput.Close();
        }

        using var timeoutCts = CancellationTokenSource.CreateLinkedTokenSource(ct);
        timeoutCts.CancelAfter(timeout);
        var timedOut = false;
        try
        {
            await p.WaitForExitAsync(timeoutCts.Token);
        }
        catch (OperationCanceledException)
        {
            timedOut = true;
            try { p.Kill(entireProcessTree: true); } catch { /* already gone */ }
            ct.ThrowIfCancellationRequested();
        }

        var stdout = await stdoutTask;
        var stderr = await stderrTask;
        return new PsResult(timedOut ? -1 : p.ExitCode, stdout, stderr, timedOut, sw.Elapsed);
    }
}
