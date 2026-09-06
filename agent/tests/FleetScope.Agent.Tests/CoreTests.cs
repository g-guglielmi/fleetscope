using System.Text;
using System.Text.Json.Nodes;
using FleetScope.Agent;
using FleetScope.Agent.Api;
using FleetScope.Agent.Checks;
using FleetScope.Agent.Cli;
using FleetScope.Agent.Service;
using Xunit;

namespace FleetScope.Agent.Tests;

public class CanonicalJsonTests
{
    [Fact]
    public void SortsKeysAndStripsWhitespace()
    {
        var node = JsonNode.Parse("""{ "b": [1, 2, {"z": 1, "a": 2}], "a": "x", "n": 300, "t": true, "nul": null }""");
        var canonical = Encoding.UTF8.GetString(Json.Canonical(node));
        Assert.Equal("""{"a":"x","b":[1,2,{"a":2,"z":1}],"n":300,"nul":null,"t":true}""", canonical);
    }

    [Fact]
    public void KeepsNumericTextAndUnicode()
    {
        var node = JsonNode.Parse("""{"f": 1.5, "neg": -7, "s": "é ü"}""");
        Assert.Equal("""{"f":1.5,"neg":-7,"s":"é ü"}""", Encoding.UTF8.GetString(Json.Canonical(node)));
    }
}

public class CheckRunnerTests
{
    [Fact]
    public void ExtractsJsonAfterNoise()
    {
        var o = CheckRunner.ExtractJson("Loading module...\nWARNING: something\n{\"schema\":1,\"components\":[]}\n");
        Assert.NotNull(o);
        Assert.Equal(1, o!["schema"]!.GetValue<int>());
    }

    [Fact]
    public void ExtractsLastLineWhenEarlierBraceIsNotJson()
    {
        var o = CheckRunner.ExtractJson("text with { brace\n{\"schema\":1}");
        Assert.NotNull(o);
    }

    [Fact]
    public void ReturnsNullWithoutJson()
    {
        Assert.Null(CheckRunner.ExtractJson(""));
        Assert.Null(CheckRunner.ExtractJson("no json here"));
    }

    [Fact]
    public void DiagnosticShapeMatchesIngestContract()
    {
        var o = new CheckOutcome { Name = "netscaler", Version = "1.0.0", Status = "warn", DurationMs = 1200 };
        o.Warnings.Add("x");
        var d = o.ToDiagnostic();
        Assert.Equal("netscaler", d["name"]!.GetValue<string>());
        Assert.Equal("warn", d["status"]!.GetValue<string>());
        Assert.Equal(1200, d["durationMs"]!.GetValue<long>());
        Assert.Single(d["warnings"]!.AsArray());
        Assert.Null(d["error"]);
    }
}

public class CollectorTests
{
    [Fact]
    public void FindsCredentialReferencesAnywhereInSettings()
    {
        var settings = JsonNode.Parse("""
            {"targets":[{"host":"https://a","credential":"ns-a"},{"host":"https://b","credential":"ns-b"}],
             "nested":{"deeper":{"credential":"svc"}},"credential":""}
            """);
        var names = Collector.ReferencedCredentials(settings);
        Assert.Equal(new[] { "ns-a", "ns-b", "svc" }, names.OrderBy(n => n));
    }

    [Fact]
    public void ParsesManifestEntries()
    {
        var manifest = JsonNode.Parse("""
            {"schema":1,"checks":[{"name":"netscaler","version":"1.0.0","file":"netscaler.ps1","sha256":"abc","requires":[],"timeoutSeconds":180,"settingsSchema":{}}]}
            """) as JsonObject;
        var entries = Collector.ParseManifest(manifest);
        var e = Assert.Single(entries);
        Assert.Equal("netscaler", e.Name);
        Assert.Equal(180, e.TimeoutSeconds);
        Assert.Equal("powershell", e.Shell);
    }
}

public class PrerequisiteTests
{
    [Fact]
    public void RequirementIsMetOnlyWhenTruthy()
    {
        var p = new Dictionary<string, object?> { ["cvad-sdk"] = null, ["winrm-client"] = true, ["powershell"] = "5.1", ["x"] = false };
        Assert.False(Prerequisites.IsMet(p, "cvad-sdk"));
        Assert.True(Prerequisites.IsMet(p, "winrm-client"));
        Assert.True(Prerequisites.IsMet(p, "powershell"));
        Assert.False(Prerequisites.IsMet(p, "x"));
        Assert.False(Prerequisites.IsMet(p, "missing"));
    }
}

public class ArgsTests
{
    [Fact]
    public void ParsesCommandOptionsAndPositionals()
    {
        var a = Args.Parse(new[] { "install", "--url", "https://x", "--insecure", "--site=Bolzano", "extra" });
        Assert.Equal("install", a.Command);
        Assert.Equal("https://x", a.Get("url"));
        Assert.True(a.Has("insecure"));
        Assert.Equal("Bolzano", a.Get("site"));
        Assert.Equal(new[] { "extra" }, a.Positional);
        Assert.Throws<ArgumentException>(() => a.Require("token"));
    }
}

public class AgentStateTests
{
    [Fact]
    public void RoundTripsThroughDisk()
    {
        var dir = Path.Combine(Path.GetTempPath(), "fs-agent-test-" + Guid.NewGuid().ToString("N"));
        var previous = AgentPaths.DataDir;
        AgentPaths.DataDir = dir;
        try
        {
            var s = new AgentState { DashboardUrl = "https://fs.test", SiteSlug = "bolzano", SigningKey = "k", CheckinSeconds = 60, LastRun = new JsonObject { ["at"] = "now" } };
            s.Save();
            var back = AgentState.Load();
            Assert.Equal("https://fs.test", back.DashboardUrl);
            Assert.Equal(60, back.CheckinSeconds);
            Assert.True(back.IsEnrolled);
            Assert.Equal("now", back.LastRun!["at"]!.GetValue<string>());
        }
        finally
        {
            AgentPaths.DataDir = previous;
            Directory.Delete(dir, recursive: true);
        }
    }
}

public class DashboardClientTests
{
    [Fact]
    public void ExtractsFastApiDetail()
    {
        Assert.Equal("Invalid or expired token", DashboardClient.ExtractDetail("""{"detail":"Invalid or expired token"}"""));
        Assert.Equal("plain", DashboardClient.ExtractDetail("plain"));
        Assert.Equal("request failed", DashboardClient.ExtractDetail(""));
    }
}
