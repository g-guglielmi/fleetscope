using System.Security.Cryptography;
using System.Text;

namespace FleetScope.Agent.Security;

/// <summary>
/// Machine-scope DPAPI (docs/AGENT.md §4.5): files can be written from any elevated
/// prompt and read by the service, and cannot be decrypted on another machine.
/// Access is bounded by the NTFS ACL the installer puts on the secrets directory.
/// </summary>
public static class Dpapi
{
    private static readonly byte[] Entropy = Encoding.UTF8.GetBytes("FleetScope.Agent.v1");

    public static void WriteProtected(string path, string plaintext)
    {
        Directory.CreateDirectory(Path.GetDirectoryName(path)!);
        var ct = ProtectedData.Protect(Encoding.UTF8.GetBytes(plaintext), Entropy, DataProtectionScope.LocalMachine);
        var tmp = path + ".tmp";
        File.WriteAllBytes(tmp, ct);
        File.Move(tmp, path, overwrite: true);
    }

    public static string? ReadProtected(string path)
    {
        if (!File.Exists(path)) return null;
        var pt = ProtectedData.Unprotect(File.ReadAllBytes(path), Entropy, DataProtectionScope.LocalMachine);
        return Encoding.UTF8.GetString(pt);
    }
}
