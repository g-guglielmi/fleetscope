using System.Globalization;
using System.Text;
using System.Text.Encodings.Web;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;

namespace FleetScope.Agent;

public static class Json
{
    /// <summary>camelCase, null-skipping, no HTML escaping — matches the dashboard API.</summary>
    public static readonly JsonSerializerOptions Options = new(JsonSerializerDefaults.Web)
    {
        DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull,
        Encoder = JavaScriptEncoder.UnsafeRelaxedJsonEscaping,
    };

    public static readonly JsonSerializerOptions Pretty = new(Options) { WriteIndented = true };

    /// <summary>
    /// Deterministic serialization identical to the server's signer
    /// (Python <c>json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)</c>):
    /// object keys sorted by ordinal code point, no whitespace, non-ASCII left raw, and
    /// Python's exact escape table for strings. Signatures cover this form (docs/AGENT.md §7.2).
    /// Hand-rolled on purpose: Utf8JsonWriter's escaping differs in details (e.g.  vs ).
    /// </summary>
    public static byte[] Canonical(JsonNode? node)
    {
        var sb = new StringBuilder();
        WriteCanonical(sb, node);
        return Encoding.UTF8.GetBytes(sb.ToString());
    }

    private static void WriteCanonical(StringBuilder sb, JsonNode? node)
    {
        switch (node)
        {
            case null:
                sb.Append("null");
                break;
            case JsonObject o:
                sb.Append('{');
                var first = true;
                foreach (var kv in o.OrderBy(k => k.Key, StringComparer.Ordinal))
                {
                    if (!first) sb.Append(',');
                    first = false;
                    PyQuote(sb, kv.Key);
                    sb.Append(':');
                    WriteCanonical(sb, kv.Value);
                }
                sb.Append('}');
                break;
            case JsonArray a:
                sb.Append('[');
                for (var i = 0; i < a.Count; i++)
                {
                    if (i > 0) sb.Append(',');
                    WriteCanonical(sb, a[i]);
                }
                sb.Append(']');
                break;
            case JsonValue v:
                WriteValue(sb, v);
                break;
        }
    }

    private static void WriteValue(StringBuilder sb, JsonValue v)
    {
        if (v.TryGetValue<JsonElement>(out var el))
        {
            switch (el.ValueKind)
            {
                case JsonValueKind.String: PyQuote(sb, el.GetString()!); return;
                case JsonValueKind.Number: sb.Append(el.GetRawText()); return;   // keep the exact numeric text
                case JsonValueKind.True: sb.Append("true"); return;
                case JsonValueKind.False: sb.Append("false"); return;
                case JsonValueKind.Null: sb.Append("null"); return;
                default: sb.Append(el.GetRawText()); return;
            }
        }
        if (v.TryGetValue<string>(out var s)) { PyQuote(sb, s); return; }
        if (v.TryGetValue<bool>(out var b)) { sb.Append(b ? "true" : "false"); return; }
        if (v.TryGetValue<long>(out var l)) { sb.Append(l.ToString(CultureInfo.InvariantCulture)); return; }
        if (v.TryGetValue<int>(out var i)) { sb.Append(i.ToString(CultureInfo.InvariantCulture)); return; }
        if (v.TryGetValue<double>(out var d)) { sb.Append(d.ToString("R", CultureInfo.InvariantCulture)); return; }
        sb.Append(v.ToJsonString());
    }

    /// <summary>Python json's string escaping with ensure_ascii=False.</summary>
    private static void PyQuote(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (var c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                case '\b': sb.Append("\\b"); break;
                case '\f': sb.Append("\\f"); break;
                default:
                    if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4"));
                    else sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }
}
