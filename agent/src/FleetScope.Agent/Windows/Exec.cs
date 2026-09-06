using System.Diagnostics;

namespace FleetScope.Agent.Windows;

/// <summary>Runs a system tool (sc.exe, icacls) and captures its output. Never used with secrets on the command line.</summary>
internal static class Exec
{
    public static (int Code, string Output) Run(string exe, string arguments)
    {
        var path = Path.IsPathRooted(exe) ? exe : Path.Combine(Environment.SystemDirectory, exe);
        var psi = new ProcessStartInfo(path, arguments)
        {
            RedirectStandardOutput = true,
            RedirectStandardError = true,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        using var p = Process.Start(psi) ?? throw new InvalidOperationException($"could not start {exe}");
        var stdout = p.StandardOutput.ReadToEnd();
        var stderr = p.StandardError.ReadToEnd();
        p.WaitForExit();
        return (p.ExitCode, (stdout + stderr).Trim());
    }

    public static string RunOrThrow(string exe, string arguments, string what)
    {
        var (code, output) = Run(exe, arguments);
        if (code != 0) throw new InvalidOperationException($"{what} failed ({exe} exit {code}): {output}");
        return output;
    }
}
