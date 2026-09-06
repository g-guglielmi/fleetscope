using System.Text;
using System.Text.Json.Nodes;
using FleetScope.Agent;
using FleetScope.Agent.Security;
using Xunit;

namespace FleetScope.Agent.Tests;

/// <summary>
/// Cross-checks the agent against the server's Python signer (tools/sign/sign.py):
/// the vector file was produced by Python with a deterministic test key, so the
/// canonical bytes and signatures must match exactly or agents would reject every
/// manifest the dashboard serves.
/// </summary>
public class SigningTests
{
    private static readonly JsonObject Vector =
        (JsonObject)JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "vectors", "signing.json")))!;

    private static string Pub => Vector["pub"]!.GetValue<string>();

    [Fact]
    public void CanonicalFormMatchesPythonByteForByte()
    {
        var doc = (JsonObject)Vector["signedDoc"]!.DeepClone();
        doc.Remove("signature");
        var expected = Vector["canonical"]!.GetValue<string>();
        Assert.Equal(expected, Encoding.UTF8.GetString(Json.Canonical(doc)));
    }

    [Fact]
    public void VerifiesPythonSignedDocument()
    {
        var doc = (JsonObject)Vector["signedDoc"]!.DeepClone();
        Assert.True(Signing.VerifyDocument(doc, Pub, out var reason), reason);
    }

    [Fact]
    public void VerifiesPythonSignedManifest()
    {
        var manifest = (JsonObject)Vector["signedManifest"]!.DeepClone();
        Assert.True(Signing.VerifyDocument(manifest, Pub, out var reason), reason);
    }

    [Fact]
    public void RejectsTamperedManifest()
    {
        var manifest = (JsonObject)Vector["signedManifest"]!.DeepClone();
        manifest["checks"]![0]!["timeoutSeconds"] = 181;
        Assert.False(Signing.VerifyDocument(manifest, Pub, out var reason));
        Assert.Contains("does not verify", reason);
    }

    [Fact]
    public void RejectsWrongKeyUnsignedAndMalformed()
    {
        var manifest = (JsonObject)Vector["signedManifest"]!.DeepClone();
        var otherKey = Convert.ToBase64String(new byte[32]);
        Assert.False(Signing.VerifyDocument(manifest, otherKey, out _));

        var unsigned = (JsonObject)manifest.DeepClone();
        unsigned.Remove("signature");
        Assert.False(Signing.VerifyDocument(unsigned, Pub, out var r1));
        Assert.Equal("document is unsigned", r1);

        var nulled = (JsonObject)manifest.DeepClone();
        nulled["signature"] = null;
        Assert.False(Signing.VerifyDocument(nulled, Pub, out _));

        var garbage = (JsonObject)manifest.DeepClone();
        garbage["signature"] = "ed25519:not-base64!!";
        Assert.False(Signing.VerifyDocument(garbage, Pub, out var r2));
        Assert.Contains("base64", r2);
    }

    [Fact]
    public void Sha256HexIsLowercase()
    {
        Assert.Equal("e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855", Signing.Sha256Hex(Array.Empty<byte>()));
    }
}
