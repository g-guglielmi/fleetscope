import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import {
  getClient, getSiteConfig, putSiteConfig, siteAction, isAdmin,
  SiteConfig, SiteConfigResponse, CheckDef, SchemaNode,
} from "../api";
import { Badge, ErrorText, Table, btn, btnSm, card, fmtDate, fmtTime, input } from "../components";

const norm = (n: SchemaNode) => (typeof n === "string" ? { type: n } : n);

const PREREQ_LABELS: Record<string, string> = {
  "cvad-sdk": "CVAD PowerShell SDK",
  "winrm-client": "WinRM client",
  "powershell": "Windows PowerShell",
  "pwsh": "PowerShell 7",
};

// ---------------------------------------------------------------- schema-driven field
function Field({ name, schema, value, onChange, credentials, disabled }: {
  name: string; schema: SchemaNode; value: any; onChange: (v: any) => void;
  credentials: SiteConfigResponse["credentials"]; disabled: boolean;
}) {
  const s = norm(schema);
  const label = s.label || name;
  const help = s.help;
  const wrap = (el: JSX.Element) => (
    <div>
      <label className="block text-xs text-slate-500 mb-1">{label}{s.required && <span className="text-red-500"> *</span>}</label>
      {el}
      {help && <p className="text-xs text-slate-400 mt-0.5">{help}</p>}
    </div>
  );

  switch (s.type) {
    case "hostList":
      return wrap(
        <textarea className={input + " font-mono h-20"} disabled={disabled} placeholder="one host per line"
          value={(value || []).join("\n")}
          onChange={(e) => onChange(e.target.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean))} />
      );
    case "bool":
      return (
        <label className="flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" disabled={disabled} checked={!!value} onChange={(e) => onChange(e.target.checked)} /> {label}
          {help && <span className="text-xs text-slate-400">— {help}</span>}
        </label>
      );
    case "int":
      return wrap(<input type="number" className={input} disabled={disabled} value={value ?? ""} onChange={(e) => onChange(e.target.value === "" ? null : Number(e.target.value))} />);
    case "credentialRef": {
      const kind = s.kind || "device";
      const opts = credentials.filter((c) => c.kind === kind);
      return wrap(
        <select className={input} disabled={disabled} value={value || ""} onChange={(e) => onChange(e.target.value || null)}>
          <option value="">— select a {kind} credential —</option>
          {opts.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.username})</option>)}
        </select>
      );
    }
    case "list": {
      const item = s.item;
      const rows: any[] = Array.isArray(value) ? value : [];
      if (item && typeof item === "object" && !("type" in item)) {
        // list of objects: one bordered row per entry
        return (
          <div>
            <label className="block text-xs text-slate-500 mb-1">{label}{s.required && <span className="text-red-500"> *</span>}</label>
            <div className="space-y-2">
              {rows.map((row, i) => (
                <div key={i} className="border rounded p-3 grid gap-2 sm:grid-cols-3 relative">
                  {Object.entries(item).map(([f, sub]) => (
                    <Field key={f} name={f} schema={sub as SchemaNode} value={row?.[f]} credentials={credentials} disabled={disabled}
                      onChange={(v) => { const next = rows.slice(); next[i] = { ...row, [f]: v }; onChange(next); }} />
                  ))}
                  {!disabled && (
                    <button type="button" className="absolute top-1 right-2 text-xs text-red-600 hover:text-red-800"
                      onClick={() => onChange(rows.filter((_, j) => j !== i))}>remove</button>
                  )}
                </div>
              ))}
              {!disabled && <button type="button" className={btnSm} onClick={() => onChange([...rows, {}])}>+ add</button>}
            </div>
            {help && <p className="text-xs text-slate-400 mt-0.5">{help}</p>}
          </div>
        );
      }
      return wrap(
        <textarea className={input + " font-mono h-20"} disabled={disabled} placeholder="one per line"
          value={rows.join("\n")} onChange={(e) => onChange(e.target.value.split(/\r?\n/).map((x) => x.trim()).filter(Boolean))} />
      );
    }
    default:
      return wrap(<input className={input} disabled={disabled} value={value ?? ""} placeholder={s.type === "url" ? "https://…" : ""} onChange={(e) => onChange(e.target.value || null)} />);
  }
}

// ---------------------------------------------------------------- configuration panel
function ConfigPanel({ client, site, data, reload }: { client: string; site: string; data: SiteConfigResponse; reload: () => void }) {
  const admin = isAdmin();
  const [cfg, setCfg] = useState<SiteConfig>(structuredClone(data.config));
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => { setCfg(structuredClone(data.config)); }, [data]);

  const mut = (fn: (c: SiteConfig) => void) => setCfg((prev) => { const next = structuredClone(prev); fn(next); return next; });
  const checkState = (name: string) => cfg.checks[name] || { enabled: false, settings: {} };
  const windowsCreds = data.credentials.filter((c) => c.kind === "windows");

  async function save() {
    setBusy(true); setError(""); setSaved(false);
    try {
      const { updatedAt, updatedBy, ...body } = cfg;
      await putSiteConfig(client, site, body as SiteConfig);
      setSaved(true); reload();
    } catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <section className={card}>
      <div className="flex items-center justify-between">
        <div>
          <h3 className="font-semibold text-slate-800">Configuration</h3>
          <p className="text-xs text-slate-500">
            {cfg.updatedAt ? `Last saved ${fmtTime(cfg.updatedAt)} by ${cfg.updatedBy}` : "Not configured yet"} · agents pick changes up within a check-in.
            {!data.manifestSigned && <span className="text-amber-700"> · check manifest is UNSIGNED (dev build)</span>}
          </p>
        </div>
        {admin && <button className={btn} onClick={save} disabled={busy}>{busy ? "Saving…" : "Save configuration"}</button>}
      </div>
      <ErrorText error={error} />
      {saved && <p className="text-sm text-green-700">Saved.</p>}
      {data.missingCredentials.length > 0 && (
        <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
          ⚠ Referenced credentials that no longer exist: {data.missingCredentials.join(", ")}
        </p>
      )}

      <div className="grid gap-4 sm:grid-cols-4 border rounded p-3 bg-slate-50">
        <div>
          <label className="block text-xs text-slate-500 mb-1">Run agent as <span className="text-red-500">*</span></label>
          <select className={input} disabled={!admin} value={cfg.agent.serviceAccount || ""} onChange={(e) => mut((c) => { c.agent.serviceAccount = e.target.value || null; })}>
            <option value="">— windows credential —</option>
            {windowsCreds.map((c) => <option key={c.name} value={c.name}>{c.name} ({c.username})</option>)}
          </select>
          {windowsCreds.length === 0 && <p className="text-xs text-amber-700 mt-0.5">Add a <em>windows</em> credential on the client page first.</p>}
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">Collection interval (minutes)</label>
          <input type="number" min={15} max={1440} className={input} disabled={!admin} value={cfg.intervalMinutes} onChange={(e) => mut((c) => { c.intervalMinutes = Number(e.target.value); })} />
        </div>
        <div className="space-y-2 pt-5">
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!admin} checked={cfg.autoUpdate} onChange={(e) => mut((c) => { c.autoUpdate = e.target.checked; })} /> Auto-update agent</label>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" disabled={!admin} checked={!!cfg.prerequisites.unattended} onChange={(e) => mut((c) => { c.prerequisites.unattended = e.target.checked; })} /> Unattended prerequisite installs</label>
        </div>
        <div>
          <label className="block text-xs text-slate-500 mb-1">CVAD SDK media path</label>
          <input className={input} disabled={!admin} placeholder={"\\\\fs01\\sw\\CVAD_2402\\x64\\Citrix Desktop Delivery Controller"} value={cfg.prerequisites.citrixSdkSource || ""} onChange={(e) => mut((c) => { c.prerequisites.citrixSdkSource = e.target.value || null; })} />
        </div>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        {data.checks.map((chk: CheckDef) => {
          const st = checkState(chk.name);
          return (
            <div key={chk.name} className={`border rounded-lg p-4 space-y-3 ${st.enabled ? "" : "opacity-70"}`}>
              <div className="flex items-start justify-between gap-3">
                <div>
                  <div className="font-medium flex items-center gap-2">
                    {chk.name} <span className="text-xs text-slate-400 font-normal">v{chk.version}</span>
                    {chk.requires.map((r) => <span key={r} className="text-xs bg-slate-100 text-slate-600 px-1.5 rounded">needs {PREREQ_LABELS[r] || r}</span>)}
                  </div>
                  <p className="text-xs text-slate-500 mt-0.5">{chk.description}</p>
                </div>
                <label className="flex items-center gap-2 text-sm whitespace-nowrap">
                  <input type="checkbox" disabled={!admin} checked={st.enabled} onChange={(e) => mut((c) => { c.checks[chk.name] = { ...checkState(chk.name), enabled: e.target.checked }; })} /> enabled
                </label>
              </div>
              {st.enabled && (
                <div className="space-y-3">
                  {Object.entries(chk.settingsSchema).map(([field, schema]) => (
                    <Field key={field} name={field} schema={schema} value={st.settings?.[field]} credentials={data.credentials} disabled={!admin}
                      onChange={(v) => mut((c) => { const cur = c.checks[chk.name] || { enabled: true, settings: {} }; c.checks[chk.name] = { ...cur, settings: { ...(cur.settings || {}), [field]: v } }; })} />
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------- agent panel
function AgentPanel({ client, site, siteData, cfgData, reload }: { client: string; site: string; siteData: any; cfgData: SiteConfigResponse | null; reload: () => void }) {
  const admin = isAdmin();
  const [msg, setMsg] = useState("");
  const current: Record<string, number> = Object.fromEntries((cfgData?.credentials || []).map((c) => [c.name, c.version]));

  async function act(action: "run-now" | "restart") {
    setMsg("");
    try { const r = await siteAction(client, site, action); setMsg(`${action} queued for ${r.queued} agent(s); it runs at the next check-in.`); reload(); }
    catch (err: any) { setMsg(err.message); }
  }

  return (
    <section className={card}>
      <div className="flex items-center justify-between">
        <h3 className="font-semibold text-slate-800">Agent</h3>
        {admin && siteData.collectors.length > 0 && (
          <div className="flex gap-2">
            <button className={btnSm} onClick={() => act("run-now")}>Run now</button>
            <button className={btnSm} onClick={() => act("restart")}>Restart agent</button>
          </div>
        )}
      </div>
      {msg && <p className="text-sm text-slate-600">{msg}</p>}
      {siteData.collectors.length === 0 && (
        <p className="text-sm text-slate-400">No agent enrolled for this site yet. Generate the install command on the client page.</p>
      )}
      {siteData.collectors.map((col: any) => {
        const prereqs = col.prerequisites || {};
        const held = col.credentialVersions || {};
        const referenced: string[] = siteData.referencedCredentials || [];
        return (
          <div key={col.name} className="border rounded-lg p-4 grid gap-4 md:grid-cols-3">
            <div className="text-sm space-y-1">
              <div className="flex items-center gap-2"><span className="font-medium">{col.name}</span><Badge kind={col.status}>{col.status}</Badge></div>
              <div className="text-slate-500">Agent {col.agentVersion || col.version || "?"}{col.osVersion ? ` · ${col.osVersion}` : ""}</div>
              <div className="text-slate-500">Last check-in: {fmtTime(col.lastCheckin)}</div>
              <div className="text-slate-500">Last collection: {fmtTime(col.lastSeen)}</div>
              {col.pendingActions?.length > 0 && <div className="text-amber-700">Pending: {col.pendingActions.join(", ")}</div>}
            </div>
            <div className="text-sm">
              <div className="text-xs text-slate-500 mb-1">Prerequisites</div>
              {Object.keys(prereqs).length === 0 ? <span className="text-slate-400 text-xs">not reported yet</span> :
                Object.entries(prereqs).map(([k, v]) => (
                  <div key={k} className="flex items-center gap-2">
                    <span>{v ? "✅" : "❌"}</span><span>{PREREQ_LABELS[k] || k}</span>
                    {typeof v === "string" && <span className="text-xs text-slate-400">{v}</span>}
                  </div>
                ))}
              {!prereqs["cvad-sdk"] && referenced.length >= 0 && siteData.enabledChecks?.includes("citrix-site") && Object.keys(prereqs).length > 0 && (
                <p className="text-xs text-amber-700 mt-1">Install the CVAD SDK from the product ISO, or set the media path in Configuration.</p>
              )}
            </div>
            <div className="text-sm">
              <div className="text-xs text-slate-500 mb-1">Credentials held</div>
              {referenced.length === 0 ? <span className="text-slate-400 text-xs">none referenced</span> :
                referenced.map((n) => {
                  const have = held[n]; const want = current[n];
                  const state = have == null ? "missing" : want != null && have < want ? "stale" : "current";
                  return (
                    <div key={n} className="flex items-center gap-2">
                      <span>{state === "current" ? "✅" : state === "stale" ? "🔄" : "❌"}</span>
                      <span className="font-mono text-xs">{n}</span>
                      <span className="text-xs text-slate-400">{have != null ? `v${have}` : ""}{state === "stale" ? ` → v${want} pending` : ""}{state === "missing" ? "not fetched yet" : ""}</span>
                    </div>
                  );
                })}
            </div>
            {col.lastRun?.checks && (
              <div className="md:col-span-3">
                <div className="text-xs text-slate-500 mb-1">Last collection {col.lastRun.at ? `(${fmtTime(col.lastRun.at)})` : ""}</div>
                <table className="w-full text-sm">
                  <thead><tr className="text-left text-slate-400"><th className="py-1 pr-4 font-normal">Check</th><th className="py-1 pr-4 font-normal">Status</th><th className="py-1 pr-4 font-normal">Duration</th><th className="py-1 font-normal">Details</th></tr></thead>
                  <tbody>
                    {col.lastRun.checks.map((c: any) => (
                      <tr key={c.name} className="border-t align-top">
                        <td className="py-1 pr-4">{c.name} <span className="text-xs text-slate-400">{c.version}</span></td>
                        <td className="py-1 pr-4"><Badge kind={c.status}>{c.status}</Badge></td>
                        <td className="py-1 pr-4">{c.durationMs != null ? `${(c.durationMs / 1000).toFixed(1)}s` : "—"}</td>
                        <td className="py-1 text-xs">
                          {c.error && <div className="text-red-700">{c.error}</div>}
                          {(c.warnings || []).map((w: string, i: number) => <div key={i} className="text-amber-700">{w}</div>)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        );
      })}
    </section>
  );
}

// ---------------------------------------------------------------- inventory
const SEV: Record<string, string> = {
  critical: "text-red-700 font-semibold", high: "text-red-600", medium: "text-amber-600", low: "text-slate-600", unknown: "text-slate-500",
};

function Inventory({ site }: { site: any }) {
  return (
    <section className={card}>
      <h3 className="font-semibold text-slate-800">Inventory</h3>
      <Table title="Components" rows={site.components} cols={[
        ["type", "Type"], ["hostname", "Host"], ["product", "Product"], ["version", "Version"], ["build", "Build"], ["osVersion", "OS"],
      ]} />
      <Table title="Findings" rows={site.findings} headers={["Host", "Build", "Severity", "CVE", "Title", "Fixed in"]} render={(f: any) => (
        <tr key={f.hostname + f.cve + f.title} className="border-t">
          <td className="py-1 pr-4">{f.hostname}</td><td className="py-1 pr-4">{f.build}</td>
          <td className={`py-1 pr-4 ${SEV[f.severity] || ""}`}>{f.severity}</td>
          <td className="py-1 pr-4">{f.url ? <a className="underline" href={f.url} target="_blank" rel="noreferrer">{f.cve || "link"}</a> : (f.cve || "—")}</td>
          <td className="py-1 pr-4">{f.title}</td><td className="py-1">{f.fixedBuild || "—"}</td>
        </tr>
      )} />
      <Table title="Certificates" rows={site.certificates} headers={["Source", "Host", "Subject", "Issuer", "Expires"]} render={(c: any) => {
        const days = Math.floor((new Date(c.notAfter).getTime() - Date.now()) / 86400000);
        return (
          <tr key={(c.thumbprint || "") + c.subject} className="border-t">
            <td className="py-1 pr-4">{c.source}</td><td className="py-1 pr-4">{c.hostname}</td>
            <td className="py-1 pr-4">{c.subject}</td><td className="py-1 pr-4">{c.issuer}</td>
            <td className={`py-1 ${days < 0 ? "text-red-700 font-semibold" : days < 30 ? "text-amber-600" : ""}`}>{fmtDate(c.notAfter)} {days < 0 ? "(expired)" : `(${days}d)`}</td>
          </tr>
        );
      }} />
      <Table title="Licenses" rows={site.licenses} headers={["Product", "Edition", "Model", "Count", "SA date", "Expires"]} render={(l: any, i: number) => (
        <tr key={l.product + i} className="border-t">
          <td className="py-1 pr-4">{l.product}</td><td className="py-1 pr-4">{l.edition || "—"}</td><td className="py-1 pr-4">{l.model || "—"}</td>
          <td className="py-1 pr-4">{l.count ?? "—"}</td><td className="py-1 pr-4">{fmtDate(l.subscriptionAdvantageDate)}</td><td className="py-1">{l.expires ? fmtDate(l.expires) : "permanent"}</td>
        </tr>
      )} />
    </section>
  );
}

// ---------------------------------------------------------------- page
export default function SiteDetail() {
  const { slug, site } = useParams();
  const [clientData, setClientData] = useState<any>(null);
  const [cfg, setCfg] = useState<SiteConfigResponse | null>(null);
  const [error, setError] = useState("");

  const load = () => {
    if (!slug || !site) return;
    getClient(slug).then(setClientData).catch((e) => setError(e.message));
    getSiteConfig(slug, site).then(setCfg).catch((e) => setError(e.message));
  };
  useEffect(() => {
    load();
    const t = setInterval(() => { if (slug) getClient(slug).then(setClientData).catch(() => {}); }, 30_000);
    return () => clearInterval(t);
  }, [slug, site]);

  if (error) return <p className="text-red-600">{error}</p>;
  if (!clientData || !cfg) return <p className="text-slate-500">Loading…</p>;
  const siteData = clientData.sites.find((s: any) => s.slug === site);
  if (!siteData) return <p className="text-red-600">Unknown site.</p>;

  return (
    <div className="space-y-6">
      <div>
        <Link to={`/clients/${slug}`} className="text-sm text-slate-500 hover:text-slate-800">← {clientData.name}</Link>
        <h2 className="text-xl font-semibold mt-1">{siteData.name}</h2>
      </div>
      <AgentPanel client={slug!} site={site!} siteData={siteData} cfgData={cfg} reload={load} />
      <ConfigPanel client={slug!} site={site!} data={cfg} reload={load} />
      <Inventory site={siteData} />
    </div>
  );
}
