using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using System.Text.Json.Nodes;
using FleetScope.Agent.Security;

namespace FleetScope.Agent.Api;

public sealed class DashboardException : Exception
{
    public int Status { get; }
    public DashboardException(int status, string message) : base(message) => Status = status;
}

/// <summary>HTTPS client for the dashboard's agent API. Outbound only.</summary>
public sealed class DashboardClient : IDisposable
{
    private readonly HttpClient _http;
    private string? _token;

    public string BaseUrl { get; }

    public DashboardClient(string baseUrl, bool insecure, string userAgent)
    {
        BaseUrl = baseUrl.TrimEnd('/');
        var handler = new HttpClientHandler { AutomaticDecompression = DecompressionMethods.All };
        if (insecure)
            handler.ServerCertificateCustomValidationCallback = HttpClientHandler.DangerousAcceptAnyServerCertificateValidator;
        _http = new HttpClient(handler)
        {
            BaseAddress = new Uri(BaseUrl + "/"),
            Timeout = TimeSpan.FromSeconds(90),
        };
        _http.DefaultRequestHeaders.UserAgent.ParseAdd(userAgent);
        _http.DefaultRequestHeaders.Accept.Add(new MediaTypeWithQualityHeaderValue("application/json"));
    }

    public void SetToken(string? token) => _token = token;

    public Task<EnrollResponse> EnrollAsync(string enrollmentToken, string site, string hostname, string agentVersion, string osVersion, CancellationToken ct)
        => SendAsync<EnrollResponse>(Request(HttpMethod.Post, "api/agent/enroll",
            new { site, hostname, agentVersion, osVersion }, enrollmentToken), ct);

    public Task<CheckinResponse> CheckinAsync(CheckinRequest body, CancellationToken ct)
        => SendAsync<CheckinResponse>(Request(HttpMethod.Post, "api/agent/checkin", body), ct);

    public async Task<(byte[] Body, string Sha256)> GetCheckAsync(string name, CancellationToken ct)
    {
        using var resp = await _http.SendAsync(Request(HttpMethod.Get, $"api/agent/checks/{Uri.EscapeDataString(name)}", null), ct);
        if (!resp.IsSuccessStatusCode)
            throw new DashboardException((int)resp.StatusCode, ExtractDetail(await resp.Content.ReadAsStringAsync(ct)));
        var bytes = await resp.Content.ReadAsByteArrayAsync(ct);
        var sha = resp.Headers.TryGetValues("X-Checksum-Sha256", out var v) ? v.First() : Signing.Sha256Hex(bytes);
        return (bytes, sha);
    }

    public Task<CredentialResponse> GetCredentialAsync(string name, CancellationToken ct)
        => SendAsync<CredentialResponse>(Request(HttpMethod.Get, $"api/agent/credentials/{Uri.EscapeDataString(name)}", null), ct);

    public Task<IngestResult> IngestAsync(JsonObject payload, CancellationToken ct)
        => SendAsync<IngestResult>(Request(HttpMethod.Post, "api/ingest", payload), ct);

    public async Task<JsonObject?> GetReleaseAsync(CancellationToken ct)
    {
        using var resp = await _http.SendAsync(Request(HttpMethod.Get, "api/agent/release", null), ct);
        if (resp.StatusCode == HttpStatusCode.NotFound) return null;
        var text = await resp.Content.ReadAsStringAsync(ct);
        if (!resp.IsSuccessStatusCode) throw new DashboardException((int)resp.StatusCode, ExtractDetail(text));
        return JsonNode.Parse(text) as JsonObject;
    }

    public async Task DownloadReleaseAsync(string destination, CancellationToken ct)
    {
        using var resp = await _http.GetAsync("api/agent/release/download", HttpCompletionOption.ResponseHeadersRead, ct);
        if (!resp.IsSuccessStatusCode)
            throw new DashboardException((int)resp.StatusCode, ExtractDetail(await resp.Content.ReadAsStringAsync(ct)));
        await using var fs = File.Create(destination);
        await resp.Content.CopyToAsync(fs, ct);
    }

    private HttpRequestMessage Request(HttpMethod method, string path, object? body, string? tokenOverride = null)
    {
        var req = new HttpRequestMessage(method, path);
        var token = tokenOverride ?? _token;
        if (!string.IsNullOrEmpty(token)) req.Headers.Authorization = new AuthenticationHeaderValue("Bearer", token);
        if (body is not null)
        {
            var json = body is JsonNode node ? node.ToJsonString(Json.Options) : JsonSerializer.Serialize(body, Json.Options);
            req.Content = new StringContent(json, Encoding.UTF8, "application/json");
        }
        return req;
    }

    private async Task<T> SendAsync<T>(HttpRequestMessage req, CancellationToken ct)
    {
        using var resp = await _http.SendAsync(req, ct);
        var text = await resp.Content.ReadAsStringAsync(ct);
        if (!resp.IsSuccessStatusCode) throw new DashboardException((int)resp.StatusCode, ExtractDetail(text));
        return JsonSerializer.Deserialize<T>(text, Json.Options)
               ?? throw new DashboardException((int)resp.StatusCode, "empty response");
    }

    internal static string ExtractDetail(string text)
    {
        try
        {
            var node = JsonNode.Parse(text);
            var detail = node?["detail"];
            if (detail is JsonValue v && v.TryGetValue<string>(out var s)) return s;
            if (detail is not null) return detail.ToJsonString();
        }
        catch (JsonException) { }
        return string.IsNullOrWhiteSpace(text) ? "request failed" : text.Length > 300 ? text[..300] : text;
    }

    public void Dispose() => _http.Dispose();
}
