using Xunit;

// AgentPaths.DataDir / InstallDir are process-global statics that several test
// classes redirect to temp directories; running classes in parallel races them.
[assembly: CollectionBehavior(DisableTestParallelization = true)]
