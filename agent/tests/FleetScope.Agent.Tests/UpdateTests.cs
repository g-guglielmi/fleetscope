using System.Text.Json.Nodes;
using FleetScope.Agent;
using FleetScope.Agent.Service;
using FleetScope.Agent.Windows;
using Xunit;

namespace FleetScope.Agent.Tests;

public class UpdateDecisionTests
{
    private static readonly JsonObject Vector =
        (JsonObject)JsonNode.Parse(File.ReadAllText(Path.Combine(AppContext.BaseDirectory, "vectors", "signing.json")))!;
    private static string Pub => Vector["pub"]!.GetValue<string>();
    private static JsonObject Release() => (JsonObject)Vector["signedRelease"]!.DeepClone();

    [Theory]
    [InlineData("1.2.3", 1, 2, 3)]
    [InlineData("v1.2.3", 1, 2, 3)]
    [InlineData("0.2.0-dev", 0, 2, 0)]
    [InlineData("1.2.3+abc123", 1, 2, 3)]
    [InlineData("0.0.17", 0, 0, 17)]
    public void ParsesVersions(string input, int major, int minor, int build)
        => Assert.Equal(new Version(major, minor, build), UpdateManager.ParseVersion(input));

    [Fact]
    public void RejectsGarbageVersions()
    {
        Assert.Null(UpdateManager.ParseVersion(null));
        Assert.Null(UpdateManager.ParseVersion(""));
        Assert.Null(UpdateManager.ParseVersion("latest"));
    }

    [Fact]
    public void UpdatesWhenNewerSignedAndAllowed()
    {
        var (go, reason) = UpdateManager.Decide(Release(), Pub, "0.2.0", autoUpdate: true, runningFromInstallDir: true);
        Assert.True(go, reason);
        Assert.Contains("9.9.9", reason);
    }

    [Fact]
    public void StaysPutWhenUpToDateOrNewerLocally()
    {
        Assert.False(UpdateManager.Decide(Release(), Pub, "9.9.9", true, true).Go);
        Assert.False(UpdateManager.Decide(Release(), Pub, "10.0.0", true, true).Go);
        Assert.False(UpdateManager.Decide(null, Pub, "0.1.0", true, true).Go);
    }

    [Fact]
    public void RespectsAutoUpdateOff()
    {
        var (go, reason) = UpdateManager.Decide(Release(), Pub, "0.2.0", autoUpdate: false, runningFromInstallDir: true);
        Assert.False(go);
        Assert.Contains("auto-update is off", reason);
    }

    [Fact]
    public void RequiresRunningFromInstallDir()
    {
        var (go, reason) = UpdateManager.Decide(Release(), Pub, "0.2.0", true, runningFromInstallDir: false);
        Assert.False(go);
        Assert.Contains("not running from", reason);
    }

    [Fact]
    public void RefusesUnsignedOrTamperedRelease()
    {
        var unsigned = Release();
        unsigned.Remove("signature");
        var (go, reason) = UpdateManager.Decide(unsigned, Pub, "0.2.0", true, true);
        Assert.False(go);
        Assert.Contains("REFUSED", reason);

        var tampered = Release();
        tampered["sha256"] = new string('c', 64);
        Assert.False(UpdateManager.Decide(tampered, Pub, "0.2.0", true, true).Go);
    }
}

public class UpdateFileTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "fs-upd-" + Guid.NewGuid().ToString("N"));
    private readonly string _prevData;
    private readonly string _prevInstall;

    public UpdateFileTests()
    {
        _prevData = AgentPaths.DataDir;
        _prevInstall = AgentPaths.InstallDir;
        AgentPaths.DataDir = Path.Combine(_dir, "data");
        AgentPaths.InstallDir = Path.Combine(_dir, "install");
        Directory.CreateDirectory(AgentPaths.DataDir);
        Directory.CreateDirectory(AgentPaths.InstallDir);
    }

    public void Dispose()
    {
        AgentPaths.DataDir = _prevData;
        AgentPaths.InstallDir = _prevInstall;
        Directory.Delete(_dir, recursive: true);
    }

    [Fact]
    public void SwapKeepsOldAndInstallsNew()
    {
        var exe = AgentPaths.ExePath;
        File.WriteAllText(exe, "OLD");
        var staged = Path.Combine(_dir, "staged.exe");
        File.WriteAllText(staged, "NEW");

        UpdateManager.SwapNewBinary(exe, staged);

        Assert.Equal("NEW", File.ReadAllText(exe));
        Assert.Equal("OLD", File.ReadAllText(exe + ".old"));
        Assert.False(File.Exists(staged));
    }

    [Fact]
    public void SwapUndoneWhenStagedMoveFails()
    {
        var exe = AgentPaths.ExePath;
        File.WriteAllText(exe, "OLD");
        Assert.ThrowsAny<Exception>(() => UpdateManager.SwapNewBinary(exe, Path.Combine(_dir, "missing.exe")));
        Assert.Equal("OLD", File.ReadAllText(exe));   // rename was undone
        Assert.False(File.Exists(exe + ".old"));
    }

    [Fact]
    public void RollbackRestoresOldBinary()
    {
        var exe = AgentPaths.ExePath;
        File.WriteAllText(exe, "NEW");
        File.WriteAllText(exe + ".old", "OLD");

        Assert.True(UpdateManager.RollbackToOld(exe));
        Assert.Equal("OLD", File.ReadAllText(exe));
        Assert.Equal("NEW", File.ReadAllText(exe + ".failed"));

        File.Delete(exe);
        File.WriteAllText(exe, "X");
        Assert.False(UpdateManager.RollbackToOld(exe));   // nothing to roll back to
    }

    [Fact]
    public void MarkerRoundTripsAndCleanupRemovesEverything()
    {
        UpdateManager.SaveMarker(new UpdateMarker { FromVersion = "1.0.0", ToVersion = "1.1.0", At = DateTimeOffset.UtcNow });
        var back = UpdateManager.LoadMarker();
        Assert.NotNull(back);
        Assert.Equal("1.1.0", back!.ToVersion);

        File.WriteAllText(UpdateManager.OldPath, "x");
        File.WriteAllText(UpdateManager.FailedPath, "x");
        Directory.CreateDirectory(AgentPaths.UpdatesDir);
        File.WriteAllText(Path.Combine(AgentPaths.UpdatesDir, "FleetScopeAgent.2.0.0.exe"), "x");

        UpdateManager.Cleanup();

        Assert.Null(UpdateManager.LoadMarker());
        Assert.False(File.Exists(UpdateManager.OldPath));
        Assert.False(File.Exists(UpdateManager.FailedPath));
        Assert.Empty(Directory.GetFiles(AgentPaths.UpdatesDir));
    }
}

public class PrereqInstallerTests : IDisposable
{
    private readonly string _dir = Path.Combine(Path.GetTempPath(), "fs-sdk-" + Guid.NewGuid().ToString("N"));

    public PrereqInstallerTests() => Directory.CreateDirectory(_dir);
    public void Dispose() => Directory.Delete(_dir, recursive: true);

    [Fact]
    public void FindsMsiInKnownLayoutsAndByFile()
    {
        Assert.Null(PrereqInstaller.ResolveMsi(_dir));   // empty dir

        var iso = Path.Combine(_dir, "x64", "Citrix Desktop Delivery Controller");
        Directory.CreateDirectory(iso);
        var msi = Path.Combine(iso, "Broker_PowerShellSnapIn_x64.msi");
        File.WriteAllText(msi, "msi");

        Assert.Equal(msi, PrereqInstaller.ResolveMsi(_dir));   // ISO root
        Assert.Equal(msi, PrereqInstaller.ResolveMsi(iso));    // the folder itself
        Assert.Equal(msi, PrereqInstaller.ResolveMsi(msi));    // direct file
        Assert.Null(PrereqInstaller.ResolveMsi(Path.Combine(_dir, "nope")));
    }
}
