import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getClient,
  getEnrollmentTokens,
  createEnrollmentToken,
  revokeEnrollmentToken,
  EnrollmentToken,
} from "../api";

function fmt(d: string | null) {
  return d ? new Date(d).toLocaleDateString() : "—";
}

const SEV: Record<string, string> = {
  critical: "text-red-700 font-semibold",
  high: "text-red-600",
  medium: "text-amber-600",
  low: "text-slate-600",
  unknown: "text-slate-500",
};

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
      className="ml-2 px-2 py-0.5 text-xs rounded bg-slate-200 hover:bg-slate-300 text-slate-700"
    >
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

function EnrollmentSection({ slug }: { slug: string }) {
  const [tokens, setTokens] = useState<EnrollmentToken[]>([]);
  const [newToken, setNewToken] = useState<EnrollmentToken | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => getEnrollmentTokens(slug).then(setTokens).catch(() => {});
  useEffect(() => { load(); }, [slug]);

  async function mint() {
    setLoading(true);
    try {
      const t = await createEnrollmentToken(slug);
      setNewToken(t);
      load();
    } catch { /* ignore */ }
    setLoading(false);
  }

  async function revoke(id: number) {
    await revokeEnrollmentToken(id);
    load();
  }

  return (
    <section className="bg-white rounded-lg shadow p-5 space-y-4">
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-800">Enrollment Tokens</h3>
        <button
          onClick={mint}
          disabled={loading}
          className="px-3 py-1 text-xs bg-slate-900 text-white rounded hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? "Minting…" : "+ New Token"}
        </button>
      </div>

      {newToken?.token && (
        <div className="bg-green-50 border border-green-200 rounded p-3">
          <div className="flex items-center justify-between mb-1">
            <span className="text-xs font-medium text-green-800">New enrollment token (shown once)</span>
            <CopyButton text={newToken.token} />
          </div>
          <code className="block text-sm break-all font-mono text-green-900 select-all">{newToken.token}</code>
          <p className="text-xs text-green-700 mt-1">
            Expires {new Date(newToken.expiresAt).toLocaleString()}.
            Put this in the probe's config.json as "token".
          </p>
        </div>
      )}

      {tokens.length === 0 ? (
        <p className="text-sm text-slate-400">No enrollment tokens.</p>
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-slate-400">
              <th className="py-1 pr-4 font-normal">ID</th>
              <th className="py-1 pr-4 font-normal">Label</th>
              <th className="py-1 pr-4 font-normal">Expires</th>
              <th className="py-1 pr-4 font-normal">Last used</th>
              <th className="py-1 pr-4 font-normal">Status</th>
              <th className="py-1 font-normal"></th>
            </tr>
          </thead>
          <tbody>
            {tokens.map((t) => (
              <tr key={t.id} className="border-t">
                <td className="py-1 pr-4">{t.id}</td>
                <td className="py-1 pr-4">{t.label || "—"}</td>
                <td className="py-1 pr-4">{new Date(t.expiresAt).toLocaleString()}</td>
                <td className="py-1 pr-4">{t.lastUsedAt ? new Date(t.lastUsedAt).toLocaleString() : "never"}</td>
                <td className="py-1 pr-4">
                  {t.revoked ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-red-100 text-red-700">revoked</span>
                  ) : t.valid ? (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-green-100 text-green-700">valid</span>
                  ) : (
                    <span className="text-xs px-2 py-0.5 rounded-full bg-slate-200 text-slate-600">expired</span>
                  )}
                </td>
                <td className="py-1 text-right">
                  {!t.revoked && t.valid && (
                    <button
                      onClick={() => revoke(t.id)}
                      className="text-xs text-red-600 hover:text-red-800"
                    >
                      Revoke
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}

export default function ClientDetail() {
  const { slug } = useParams();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (slug) getClient(slug).then(setData).catch((e) => setError(String(e)));
  }, [slug]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="space-y-8">
      <div>
        <Link to="/" className="text-sm text-slate-500 hover:text-slate-800">← Overview</Link>
        <h2 className="text-xl font-semibold mt-1">{data.name}</h2>
      </div>

      <EnrollmentSection slug={data.slug} />

      {data.sites.map((site: any) => (
        <section key={site.slug} className="bg-white rounded-lg shadow p-5 space-y-5">
          <h3 className="font-semibold text-slate-800">{site.name}</h3>

          {site.collectors?.length > 0 && (
            <div>
              <h4 className="text-sm font-medium text-slate-500 mb-2">Collectors ({site.collectors.length})</h4>
              <div className="flex flex-wrap gap-3">
                {site.collectors.map((col: any) => (
                  <div key={col.name} className="text-sm bg-slate-50 rounded px-3 py-2 border">
                    <span className="font-medium">{col.name}</span>
                    <span className="text-slate-400 ml-2 text-xs">v{col.version || "?"}</span>
                    <div className="text-xs text-slate-500">
                      {col.lastSeen ? `Last seen ${new Date(col.lastSeen).toLocaleString()}` : "Never seen"}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <Table title="Components" rows={site.components} cols={[
            ["type", "Type"], ["hostname", "Host"], ["product", "Product"],
            ["version", "Version"], ["build", "Build"], ["osVersion", "OS"],
          ]} />

          <Table title="Findings" rows={site.findings} render={(f: any) => (
            <tr key={f.hostname + f.cve} className="border-t">
              <td className="py-1 pr-4">{f.hostname}</td>
              <td className="py-1 pr-4">{f.build}</td>
              <td className={`py-1 pr-4 ${SEV[f.severity] || ""}`}>{f.severity}</td>
              <td className="py-1 pr-4">{f.cve || "—"}</td>
              <td className="py-1 pr-4">{f.title}</td>
              <td className="py-1">{f.fixedBuild || "—"}</td>
            </tr>
          )} headers={["Host", "Build", "Severity", "CVE", "Title", "Fixed in"]} />

          <Table title="Certificates" rows={site.certificates} render={(c: any) => (
            <tr key={c.thumbprint} className="border-t">
              <td className="py-1 pr-4">{c.source}</td>
              <td className="py-1 pr-4">{c.subject}</td>
              <td className="py-1 pr-4">{c.issuer}</td>
              <td className="py-1">{fmt(c.notAfter)}</td>
            </tr>
          )} headers={["Source", "Subject", "Issuer", "Expires"]} />

          <Table title="Licenses" rows={site.licenses} render={(l: any) => (
            <tr key={l.product} className="border-t">
              <td className="py-1 pr-4">{l.product}</td>
              <td className="py-1 pr-4">{l.edition || "—"}</td>
              <td className="py-1 pr-4">{l.count ?? "—"}</td>
              <td className="py-1 pr-4">{fmt(l.subscriptionAdvantageDate)}</td>
              <td className="py-1">{fmt(l.expires)}</td>
            </tr>
          )} headers={["Product", "Edition", "Count", "SA date", "Expires"]} />
        </section>
      ))}

      {data.sites.length === 0 && (
        <p className="text-slate-500">
          No sites yet. Configure a collector with this client's enrollment token and push data to create the first site.
        </p>
      )}
    </div>
  );
}

function Table({ title, rows, cols, headers, render }: any) {
  const finalHeaders = headers || (cols ? cols.map((c: any) => c[1]) : []);
  return (
    <div>
      <h4 className="text-sm font-medium text-slate-500 mb-2">{title} ({rows.length})</h4>
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400">None.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-slate-400">
                {finalHeaders.map((h: string) => <th key={h} className="py-1 pr-4 font-normal">{h}</th>)}
              </tr>
            </thead>
            <tbody>
              {render
                ? rows.map(render)
                : rows.map((r: any, i: number) => (
                    <tr key={i} className="border-t">
                      {cols.map(([key]: any) => <td key={key} className="py-1 pr-4">{r[key] ?? "—"}</td>)}
                    </tr>
                  ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
