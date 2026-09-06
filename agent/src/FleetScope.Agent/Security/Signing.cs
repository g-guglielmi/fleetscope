using System.Security.Cryptography;
using System.Text.Json.Nodes;
using Org.BouncyCastle.Crypto.Parameters;
using Org.BouncyCastle.Crypto.Signers;

namespace FleetScope.Agent.Security;

/// <summary>Ed25519 verification of dashboard-served documents (docs/AGENT.md §7.2).</summary>
public static class Signing
{
    private const string Prefix = "ed25519:";

    /// <summary>
    /// Verifies <c>doc.signature</c> over the canonical JSON of the document without its
    /// <c>signature</c> member, using the pinned base64 public key.
    /// </summary>
    public static bool VerifyDocument(JsonObject doc, string publicKeyBase64, out string reason)
    {
        var sig = doc["signature"]?.GetValue<string>();
        if (string.IsNullOrEmpty(sig) || !sig.StartsWith(Prefix, StringComparison.Ordinal))
        {
            reason = "document is unsigned";
            return false;
        }
        byte[] sigBytes, pub;
        try
        {
            sigBytes = Convert.FromBase64String(sig[Prefix.Length..]);
            pub = Convert.FromBase64String(publicKeyBase64);
        }
        catch (FormatException)
        {
            reason = "signature or public key is not valid base64";
            return false;
        }
        if (pub.Length != 32) { reason = "pinned public key is not 32 bytes"; return false; }
        if (sigBytes.Length != 64) { reason = "signature is not 64 bytes"; return false; }

        var body = (JsonObject)doc.DeepClone();
        body.Remove("signature");
        var message = Json.Canonical(body);

        bool ok;
        try
        {
            var verifier = new Ed25519Signer();
            verifier.Init(false, new Ed25519PublicKeyParameters(pub, 0));
            verifier.BlockUpdate(message, 0, message.Length);
            ok = verifier.VerifySignature(sigBytes);
        }
        catch (Exception ex)
        {
            reason = $"signature does not verify against the pinned key ({ex.GetType().Name})";
            return false;
        }
        if (!ok)
        {
            reason = "signature does not verify against the pinned key";
            return false;
        }
        reason = "";
        return true;
    }

    public static string Sha256Hex(byte[] data) => Convert.ToHexString(SHA256.HashData(data)).ToLowerInvariant();

    public static bool IsPlausibleKey(string base64)
    {
        try { return Convert.FromBase64String(base64).Length == 32; } catch { return false; }
    }
}
