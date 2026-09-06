using FleetScope.Agent.Cli;
using FleetScope.Agent.Logging;
using FleetScope.Agent.Service;
using Microsoft.Extensions.DependencyInjection;
using Microsoft.Extensions.Hosting;
using Microsoft.Extensions.Hosting.WindowsServices;
using Microsoft.Extensions.Logging;

namespace FleetScope.Agent;

public static class Program
{
    public static async Task<int> Main(string[] args)
    {
        var dataDir = Environment.GetEnvironmentVariable("FLEETSCOPE_DATA_DIR");
        if (!string.IsNullOrWhiteSpace(dataDir)) AgentPaths.DataDir = dataDir;

        // No arguments under the SCM = run as the service. `run` = same loop in a console (debugging).
        if (WindowsServiceHelpers.IsWindowsService() || (args.Length == 1 && args[0].Equals("run", StringComparison.OrdinalIgnoreCase)))
            return await RunServiceAsync(args);

        return await CommandLine.RunAsync(args);
    }

    private static async Task<int> RunServiceAsync(string[] args)
    {
        var builder = Host.CreateApplicationBuilder(new HostApplicationBuilderSettings
        {
            Args = args,
            ContentRootPath = AppContext.BaseDirectory,
        });
        builder.Services.AddWindowsService(o => o.ServiceName = AgentPaths.ServiceName);

        builder.Logging.ClearProviders();
        builder.Logging.SetMinimumLevel(LogLevel.Information);
        builder.Logging.AddFilter("Microsoft", LogLevel.Warning);
        builder.Logging.AddProvider(new FileLoggerProvider(AgentPaths.LogsDir));
        if (!WindowsServiceHelpers.IsWindowsService())
            builder.Logging.AddSimpleConsole(o => { o.TimestampFormat = "HH:mm:ss "; o.SingleLine = true; });
        try
        {
            // Source is created by `install` (needs admin); warnings and errors also go to the Application log.
            builder.Logging.AddEventLog(o =>
            {
                o.SourceName = AgentPaths.ServiceName;
                o.LogName = "Application";
                o.Filter = (_, level) => level >= LogLevel.Warning;
            });
        }
        catch { /* event log unavailable: file log still works */ }

        builder.Services.AddHostedService<AgentWorker>();

        using var host = builder.Build();
        await host.RunAsync();
        return Environment.ExitCode;
    }
}
