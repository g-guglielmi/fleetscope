import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { getClient } from "../api";

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

      {data.sites.map((site: any) => (
        <section key={site.slug} className="bg-white rounded-lg shadow p-5 space-y-5">
          <h3 className="font-semibold text-slate-800">{site.name}</h3>

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
      )}
    </div>
  );
}
