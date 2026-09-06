using System.ComponentModel;
using System.Runtime.InteropServices;
using System.ServiceProcess;

namespace FleetScope.Agent.Windows;

/// <summary>
/// Service Control Manager operations. Account passwords go through the Win32 API
/// directly (never on an sc.exe command line where they would show in process lists).
/// </summary>
internal static class ServiceManager
{
    private const uint SC_MANAGER_ALL_ACCESS = 0xF003F;
    private const uint SERVICE_ALL_ACCESS = 0xF01FF;
    private const uint SERVICE_CHANGE_CONFIG = 0x0002;
    private const uint SERVICE_WIN32_OWN_PROCESS = 0x00000010;
    private const uint SERVICE_AUTO_START = 0x00000002;
    private const uint SERVICE_ERROR_NORMAL = 0x00000001;
    private const uint SERVICE_NO_CHANGE = 0xFFFFFFFF;

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode, EntryPoint = "OpenSCManagerW")]
    private static extern IntPtr OpenSCManager(string? machineName, string? databaseName, uint desiredAccess);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode, EntryPoint = "OpenServiceW")]
    private static extern IntPtr OpenService(IntPtr scManager, string serviceName, uint desiredAccess);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode, EntryPoint = "CreateServiceW")]
    private static extern IntPtr CreateService(IntPtr scManager, string serviceName, string displayName, uint desiredAccess,
        uint serviceType, uint startType, uint errorControl, string binaryPathName, string? loadOrderGroup, IntPtr tagId,
        string? dependencies, string? serviceStartName, string? password);

    [DllImport("advapi32.dll", SetLastError = true, CharSet = CharSet.Unicode, EntryPoint = "ChangeServiceConfigW")]
    private static extern bool ChangeServiceConfig(IntPtr service, uint serviceType, uint startType, uint errorControl,
        string? binaryPathName, string? loadOrderGroup, IntPtr tagId, string? dependencies, string? serviceStartName,
        string? password, string? displayName);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool DeleteService(IntPtr service);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern bool CloseServiceHandle(IntPtr handle);

    public static bool Exists(string name)
        => ServiceController.GetServices().Any(s => s.ServiceName.Equals(name, StringComparison.OrdinalIgnoreCase));

    public static ServiceControllerStatus? Status(string name)
    {
        if (!Exists(name)) return null;
        using var sc = new ServiceController(name);
        return sc.Status;
    }

    /// <summary>Creates the service, or re-points an existing one at the binary and account.</summary>
    public static void CreateOrUpdate(string name, string displayName, string binaryPath, string account, string? password)
    {
        var scm = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
        if (scm == IntPtr.Zero) throw Win32("OpenSCManager");
        try
        {
            var svc = OpenService(scm, name, SERVICE_ALL_ACCESS);
            if (svc == IntPtr.Zero)
            {
                svc = CreateService(scm, name, displayName, SERVICE_ALL_ACCESS, SERVICE_WIN32_OWN_PROCESS, SERVICE_AUTO_START,
                    SERVICE_ERROR_NORMAL, binaryPath, null, IntPtr.Zero, null, account, password);
                if (svc == IntPtr.Zero) throw Win32("CreateService");
            }
            else if (!ChangeServiceConfig(svc, SERVICE_WIN32_OWN_PROCESS, SERVICE_AUTO_START, SERVICE_ERROR_NORMAL,
                         binaryPath, null, IntPtr.Zero, null, account, password, displayName))
            {
                CloseServiceHandle(svc);
                throw Win32("ChangeServiceConfig");
            }
            CloseServiceHandle(svc);
        }
        finally
        {
            CloseServiceHandle(scm);
        }
    }

    /// <summary>Changes only the logon account/password. Password null = gMSA / no change.</summary>
    public static void SetLogon(string name, string account, string? password)
    {
        var scm = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
        if (scm == IntPtr.Zero) throw Win32("OpenSCManager");
        try
        {
            var svc = OpenService(scm, name, SERVICE_CHANGE_CONFIG);
            if (svc == IntPtr.Zero) throw Win32("OpenService");
            try
            {
                if (!ChangeServiceConfig(svc, SERVICE_NO_CHANGE, SERVICE_NO_CHANGE, SERVICE_NO_CHANGE,
                        null, null, IntPtr.Zero, null, account, password, null))
                    throw Win32("ChangeServiceConfig");
            }
            finally
            {
                CloseServiceHandle(svc);
            }
        }
        finally
        {
            CloseServiceHandle(scm);
        }
    }

    public static void Delete(string name)
    {
        var scm = OpenSCManager(null, null, SC_MANAGER_ALL_ACCESS);
        if (scm == IntPtr.Zero) throw Win32("OpenSCManager");
        try
        {
            var svc = OpenService(scm, name, SERVICE_ALL_ACCESS);
            if (svc == IntPtr.Zero) return;
            try
            {
                if (!DeleteService(svc)) throw Win32("DeleteService");
            }
            finally
            {
                CloseServiceHandle(svc);
            }
        }
        finally
        {
            CloseServiceHandle(scm);
        }
    }

    public static void Start(string name, TimeSpan timeout)
    {
        using var sc = new ServiceController(name);
        sc.Refresh();
        if (sc.Status == ServiceControllerStatus.Running) return;
        if (sc.Status != ServiceControllerStatus.StartPending) sc.Start();
        sc.WaitForStatus(ServiceControllerStatus.Running, timeout);
    }

    public static void Stop(string name, TimeSpan timeout)
    {
        if (!Exists(name)) return;
        using var sc = new ServiceController(name);
        sc.Refresh();
        if (sc.Status == ServiceControllerStatus.Stopped) return;
        if (sc.CanStop && sc.Status != ServiceControllerStatus.StopPending) sc.Stop();
        sc.WaitForStatus(ServiceControllerStatus.Stopped, timeout);
    }

    /// <summary>Description, capped recovery (restart 1 min, 5 min, then stop — no account lockout loops), delayed auto-start.</summary>
    public static void ApplyPolicies(string name, string description)
    {
        Exec.RunOrThrow("sc.exe", $"description {name} \"{description}\"", "setting the service description");
        Exec.RunOrThrow("sc.exe", $"failure {name} reset= 86400 actions= restart/60000/restart/300000//", "setting the recovery policy");
        Exec.RunOrThrow("sc.exe", $"failureflag {name} 1", "enabling recovery on non-crash failures");
        Exec.RunOrThrow("sc.exe", $"config {name} start= delayed-auto", "setting delayed auto-start");
    }

    private static Win32Exception Win32(string call) => new(Marshal.GetLastWin32Error(), $"{call} failed");
}
