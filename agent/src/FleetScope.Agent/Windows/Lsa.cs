using System.ComponentModel;
using System.Runtime.InteropServices;
using System.Security.Principal;

namespace FleetScope.Agent.Windows;

/// <summary>
/// Grants "Log on as a service" (SeServiceLogonRight). The Services MMC does this
/// silently; CreateService does not, which is the classic reason a freshly
/// configured service fails with error 1069.
/// </summary>
internal static class Lsa
{
    private const int POLICY_CREATE_ACCOUNT = 0x00000010;
    private const int POLICY_LOOKUP_NAMES = 0x00000800;
    private const string ServiceLogonRight = "SeServiceLogonRight";

    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_UNICODE_STRING
    {
        public ushort Length;
        public ushort MaximumLength;
        public IntPtr Buffer;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct LSA_OBJECT_ATTRIBUTES
    {
        public int Length;
        public IntPtr RootDirectory;
        public IntPtr ObjectName;
        public int Attributes;
        public IntPtr SecurityDescriptor;
        public IntPtr SecurityQualityOfService;
    }

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint LsaOpenPolicy(IntPtr systemName, ref LSA_OBJECT_ATTRIBUTES objectAttributes, int desiredAccess, out IntPtr policyHandle);

    [DllImport("advapi32.dll", SetLastError = true)]
    private static extern uint LsaAddAccountRights(IntPtr policyHandle, IntPtr accountSid, LSA_UNICODE_STRING[] userRights, int countOfRights);

    [DllImport("advapi32.dll")]
    private static extern uint LsaClose(IntPtr objectHandle);

    [DllImport("advapi32.dll")]
    private static extern uint LsaNtStatusToWinError(uint status);

    public static SecurityIdentifier ResolveSid(string account)
        => (SecurityIdentifier)new NTAccount(account).Translate(typeof(SecurityIdentifier));

    public static void GrantServiceLogonRight(string account)
    {
        var sid = ResolveSid(account);
        var sidBytes = new byte[sid.BinaryLength];
        sid.GetBinaryForm(sidBytes, 0);

        var attrs = new LSA_OBJECT_ATTRIBUTES { Length = Marshal.SizeOf<LSA_OBJECT_ATTRIBUTES>() };
        var status = LsaOpenPolicy(IntPtr.Zero, ref attrs, POLICY_CREATE_ACCOUNT | POLICY_LOOKUP_NAMES, out var policy);
        if (status != 0) throw new Win32Exception((int)LsaNtStatusToWinError(status), "LsaOpenPolicy failed");

        var sidPtr = Marshal.AllocHGlobal(sidBytes.Length);
        var rightPtr = Marshal.StringToHGlobalUni(ServiceLogonRight);
        try
        {
            Marshal.Copy(sidBytes, 0, sidPtr, sidBytes.Length);
            var rights = new[]
            {
                new LSA_UNICODE_STRING
                {
                    Buffer = rightPtr,
                    Length = (ushort)(ServiceLogonRight.Length * sizeof(char)),
                    MaximumLength = (ushort)((ServiceLogonRight.Length + 1) * sizeof(char)),
                },
            };
            status = LsaAddAccountRights(policy, sidPtr, rights, rights.Length);
            if (status != 0) throw new Win32Exception((int)LsaNtStatusToWinError(status), "LsaAddAccountRights failed");
        }
        finally
        {
            Marshal.FreeHGlobal(rightPtr);
            Marshal.FreeHGlobal(sidPtr);
            LsaClose(policy);
        }
    }
}
