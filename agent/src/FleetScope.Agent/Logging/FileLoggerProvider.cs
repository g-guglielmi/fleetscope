using Microsoft.Extensions.Logging;

namespace FleetScope.Agent.Logging;

/// <summary>Daily rolling text log under the data dir; 14 days retained (docs/AGENT.md §4.3).</summary>
public sealed class FileLoggerProvider : ILoggerProvider
{
    private readonly string _dir;
    private readonly object _lock = new();
    private DateTime _lastCleanup = DateTime.MinValue;

    public FileLoggerProvider(string dir) => _dir = dir;

    public ILogger CreateLogger(string categoryName) => new FileLogger(this, categoryName);

    internal void Write(string line)
    {
        lock (_lock)
        {
            try
            {
                Directory.CreateDirectory(_dir);
                File.AppendAllText(Path.Combine(_dir, $"agent-{DateTime.Now:yyyyMMdd}.log"), line + Environment.NewLine);
                if ((DateTime.Now - _lastCleanup).TotalHours >= 1)
                {
                    Cleanup();
                    _lastCleanup = DateTime.Now;
                }
            }
            catch { /* logging must never take the agent down */ }
        }
    }

    private void Cleanup()
    {
        foreach (var f in Directory.EnumerateFiles(_dir, "agent-*.log"))
            if (File.GetLastWriteTime(f) < DateTime.Now.AddDays(-14))
                try { File.Delete(f); } catch { }
    }

    public void Dispose() { }

    private sealed class FileLogger : ILogger
    {
        private readonly FileLoggerProvider _provider;
        private readonly string _category;

        public FileLogger(FileLoggerProvider provider, string category)
        {
            _provider = provider;
            _category = category.Contains('.') ? category[(category.LastIndexOf('.') + 1)..] : category;
        }

        public IDisposable? BeginScope<TState>(TState state) where TState : notnull => null;

        public bool IsEnabled(LogLevel logLevel) => logLevel >= LogLevel.Information;

        public void Log<TState>(LogLevel logLevel, EventId eventId, TState state, Exception? exception, Func<TState, Exception?, string> formatter)
        {
            if (!IsEnabled(logLevel)) return;
            var line = $"{DateTime.Now:yyyy-MM-dd HH:mm:ss.fff} [{Abbrev(logLevel)}] {_category}: {formatter(state, exception)}";
            if (exception is not null) line += Environment.NewLine + exception;
            _provider.Write(line);
        }

        private static string Abbrev(LogLevel l) => l switch
        {
            LogLevel.Trace => "TRC", LogLevel.Debug => "DBG", LogLevel.Information => "INF",
            LogLevel.Warning => "WRN", LogLevel.Error => "ERR", LogLevel.Critical => "CRT", _ => "???",
        };
    }
}
