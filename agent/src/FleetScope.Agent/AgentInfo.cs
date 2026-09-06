using System.Reflection;
using System.Runtime.InteropServices;
using Microsoft.Win32;

namespace FleetScope.Agent;

public static class AgentInfo
{
    public static string Version { get; } = ReadVersion();
    public static string UserAgent => $"FleetScopeAgent/{Version}";
    public static string Hostname => Environment.MachineName;
    public static string OsVersion { get; } = ReadOs();

    private static string ReadVersion()
    {
        var info = typeof(AgentInfo).Assembly.GetCustomAttribute<AssemblyInformationalVersionAttribute>()?.InformationalVersion;
        if (string.IsNullOrWhiteSpace(info)) return typeof(AgentInfo).Assembly.GetName().Version?.ToString(3) ?? "0.0.0";
        var plus = info.IndexOf('+');  // strip the source-link hash
        return plus > 0 ? info[..plus] : info;
    }

    private static string ReadOs()
    {
        try
        {
            const string key = @"HKEY_LOCAL_MACHINE\SOFTWARE\Microsoft\Windows NT\CurrentVersion";
            var name = Registry.GetValue(key, "ProductName", null) as string;
            var build = Registry.GetValue(key, "CurrentBuildNumber", null) as string;
            var display = Registry.GetValue(key, "DisplayVersion", null) as string;
            var v = Environment.OSVersion.Version;
            var parts = new[] { name, display, $"{v.Major}.{v.Minor}.{build ?? v.Build.ToString()}" }
                .Where(p => !string.IsNullOrWhiteSpace(p));
            return string.Join(" ", parts);
        }
        catch
        {
            return RuntimeInformation.OSDescription;
        }
    }
}
