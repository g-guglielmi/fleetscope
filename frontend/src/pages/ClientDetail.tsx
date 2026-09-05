import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import {
  getClient, createSite, deleteClient, isAdmin, installCommand, InstallCommand,
  listCredentials, createCredential, updateCredential, deleteCredential, Credential, CredentialKind,
  getEnrollmentTokens, createEnrollmentToken, revokeEnrollmentToken, EnrollmentToken,
} from "../api";
import { Badge, CopyButton, ErrorText, btn, btnSm, btnGhost, card, fmtTime, input } from "../components";

// ---------------------------------------------------------------- sites
function SitesSection({ client, onChanged }: { client: any; onChanged: () => void }) {
  const admin = isAdmin();
  const [name, setName] = useState("");
  const [error, setError] = useState("");

  async function add(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setError("");
    try { await createSite(client.slug, name.trim()); setName(""); onChanged(); }
    catch (err: any) { setError(err.message); }
  }

  return (
    <section className={card}>
      <h3 className="font-semibold text-slate-800">Sites</h3>
      {client.sites.length === 0 && <p className="text-sm text-slate-400">No sites yet. Add one, configure it, then install its agent.</p>}
      <div className="grid gap-3 sm:grid-cols-2">
        {client.sites.map((s: any) => {
          const worst = s.collectors.length
            ? s.collectors.map((c: any) => c.status).sort((a: string, b: string) => ["offline", "unknown", "stale", "ok"].indexOf(a) - ["offline", "unknown", "stale", "ok"].indexOf(b))[0]
            : "unknown";
          return (
            <Link key={s.slug} to={`/clients/${client.slug}/sites/${s.slug}`} className="block border rounded-lg p-3 hover:bg-slate-50">
              <div className="flex items-center justify-between">
                <span className="font-medium">{s.name}</span>
                <Badge kind={worst}>{s.collectors.length ? worst : "no agent"}</Badge>
              </div>
              <div className="text-xs text-slate-500 mt-1 space-y-0.5">
                <div>{s.configured ? `${s.enabledChecks.length} checks enabled` : "not configured"}{s.serviceAccount ? ` · runs as ${s.serviceAccount}` : ""}</div>
                <div>{s.components.length} components · {s.findings.length} findings · {s.certificates.length} certs · {s.licenses.length} licenses</div>
              </div>
            </Link>
          );
        })}
      </div>
      {admin && (
        <form onSubmit={add} className="flex gap-2 items-start">
          <input className={input + " max-w-xs"} placeholder="New site name, e.g. Milan DC1" value={name} onChange={(e) => setName(e.target.value)} />
          <button className={btn} disabled={!name.trim()}>+ Add site</button>
          <ErrorText error={error} />
        </form>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- install command
function InstallSection({ client }: { client: any }) {
  const [site, setSite] = useState<string>(client.sites[0]?.name || "");
  const [result, setResult] = useState<InstallCommand | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  // Sites can be added while this panel is mounted: keep the selection valid.
  useEffect(() => {
    if (!client.sites.some((s: any) => s.name === site)) setSite(client.sites[0]?.name || "");
  }, [client.sites]);

  async function generate() {
    setBusy(true); setError(""); setResult(null);
    try { setResult(await installCommand(client.slug, site || undefined)); }
    catch (err: any) { setError(err.message); }
    finally { setBusy(false); }
  }

  return (
    <section className={card}>
      <h3 className="font-semibold text-slate-800">Install agent</h3>
      <p className="text-sm text-slate-600">
        Run this on the site's management VM (elevated PowerShell). It downloads the agent, enrolls it with a fresh
        temporary token and registers the Windows service using the site's configured service account.
      </p>
      <div className="flex gap-2 items-center">
        <label className="text-sm text-slate-600">Site</label>
        <select className={input + " max-w-xs"} value={site} onChange={(e) => setSite(e.target.value)}>
          {client.sites.map((s: any) => <option key={s.slug} value={s.name}>{s.name}</option>)}
          {client.sites.length === 0 && <option value="">(add a site first)</option>}
        </select>
        <button className={btn} onClick={generate} disabled={busy || !site}>{busy ? "Generating…" : "Generate install command"}</button>
      </div>
      <ErrorText error={error} />
      {result && (
        <div className="space-y-2">
          <div className="bg-slate-900 text-slate-100 rounded p-3 relative">
            <pre className="text-xs whitespace-pre-wrap break-all font-mono">{result.command}</pre>
            <div className="absolute top-2 right-2"><CopyButton text={result.command} /></div>
          </div>
          <p className="text-xs text-slate-500">
            The embedded enrollment token expires {fmtTime(result.enrollment.expiresAt)} and can be revoked below.
            Make sure the site's <em>Run agent as</em> service account is configured before running it.
          </p>
          {result.warnings.map((w) => <p key={w} className="text-xs text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">⚠ {w}</p>)}
        </div>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- credentials
function CredentialsSection({ client }: { client: any }) {
  const admin = isAdmin();
  const [creds, setCreds] = useState<Credential[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ name: "", kind: "device" as CredentialKind, username: "", password: "" });
  const [rotating, setRotating] = useState<{ id: number; password: string } | null>(null);

  const load = () => listCredentials(client.slug).then(setCreds).catch((e) => setError(e.message));
  useEffect(() => { load(); }, [client.slug]);

  async function add(e: React.FormEvent) {
    e.preventDefault(); setError("");
    try {
      await createCredential({ client: client.slug, ...form });
      setForm({ name: "", kind: "device", username: "", password: "" });
      load();
    } catch (err: any) { setError(err.message); }
  }
  async function rotate() {
    if (!rotating) return;
    setError("");
    try { await updateCredential(rotating.id, { password: rotating.password }); setRotating(null); load(); }
    catch (err: any) { setError(err.message); }
  }
  async function remove(c: Credential) {
    if (!confirm(`Delete credential "${c.name}"?`)) return;
    setError("");
    try { await deleteCredential(c.id); load(); } catch (err: any) { setError(err.message); }
  }

  const gmsa = form.kind === "windows" && form.username.trim().endsWith("$");

  return (
    <section className={card}>
      <div>
        <h3 className="font-semibold text-slate-800">Credentials</h3>
        <p className="text-sm text-slate-500">
          Stored encrypted and delivered only to this client's agents that reference them. Passwords are never shown again.
          Use a <strong>read-only</strong> NITRO user for NetScalers; the service account can be the same monitoring account you use elsewhere.
        </p>
      </div>
      <ErrorText error={error} />
      {creds.length === 0 ? <p className="text-sm text-slate-400">No credentials yet.</p> : (
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-400">
              <th className="py-1 pr-4 font-normal">Name</th><th className="py-1 pr-4 font-normal">Kind</th>
              <th className="py-1 pr-4 font-normal">Username</th><th className="py-1 pr-4 font-normal">Version</th>
              <th className="py-1 pr-4 font-normal">Used by</th><th className="py-1 pr-4 font-normal">Held by agents</th>
              <th className="py-1 pr-4 font-normal">Updated</th>{admin && <th className="py-1 font-normal"></th>}
            </tr></thead>
            <tbody>
              {creds.map((c) => (
                <tr key={c.id} className="border-t align-top">
                  <td className="py-1 pr-4 font-mono text-xs">{c.name}</td>
                  <td className="py-1 pr-4">{c.kind}{c.gmsa ? " (gMSA)" : ""}</td>
                  <td className="py-1 pr-4">{c.username}{c.username.toLowerCase() === "nsroot" && <span className="ml-1 text-xs text-amber-700" title="Prefer a read-only NITRO user">⚠ nsroot</span>}</td>
                  <td className="py-1 pr-4">v{c.version}</td>
                  <td className="py-1 pr-4 text-xs">{c.referencedBy.length ? c.referencedBy.map((r) => r.siteName).join(", ") : <span className="text-slate-400">unused</span>}</td>
                  <td className="py-1 pr-4 text-xs">
                    {c.heldBy.length === 0 ? <span className="text-slate-400">—</span> :
                      c.heldBy.map((h) => <div key={h.agent}>{h.agent}: v{h.version} {h.current ? "✓" : <span className="text-amber-700">(stale)</span>}</div>)}
                  </td>
                  <td className="py-1 pr-4 text-xs text-slate-500">{fmtTime(c.updatedAt)}<br />{c.updatedBy}</td>
                  {admin && (
                    <td className="py-1 text-right whitespace-nowrap">
                      {rotating?.id === c.id ? (
                        <span className="inline-flex gap-1">
                          <input type="password" autoFocus className="border rounded px-2 py-0.5 text-xs w-36" placeholder="new password"
                            value={rotating.password} onChange={(e) => setRotating({ id: c.id, password: e.target.value })} />
                          <button className={btnSm} onClick={rotate} disabled={!rotating.password && !c.gmsa}>Save</button>
                          <button className="text-xs text-slate-500" onClick={() => setRotating(null)}>Cancel</button>
                        </span>
                      ) : (
                        <>
                          <button className="text-xs text-slate-700 hover:text-slate-900 mr-3" onClick={() => setRotating({ id: c.id, password: "" })}>Rotate</button>
                          <button className="text-xs text-red-600 hover:text-red-800" onClick={() => remove(c)} disabled={c.referencedBy.length > 0}
                            title={c.referencedBy.length ? "Remove references in site configs first" : ""}>Delete</button>
                        </>
                      )}
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {admin && (
        <form onSubmit={add} className="grid gap-2 sm:grid-cols-5 items-end border-t pt-3">
          <div><label className="text-xs text-slate-500">Name</label>
            <input className={input} placeholder="ns-bolzano" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></div>
          <div><label className="text-xs text-slate-500">Kind</label>
            <select className={input} value={form.kind} onChange={(e) => setForm({ ...form, kind: e.target.value as CredentialKind })}>
              <option value="device">device (NetScaler, …)</option>
              <option value="windows">windows (service account)</option>
            </select></div>
          <div><label className="text-xs text-slate-500">Username</label>
            <input className={input} placeholder={form.kind === "windows" ? "DOMAIN\\svc-account" : "fleetscope-ro"} value={form.username} onChange={(e) => setForm({ ...form, username: e.target.value })} /></div>
          <div><label className="text-xs text-slate-500">Password{gmsa && " (gMSA: none)"}</label>
            <input className={input} type="password" autoComplete="new-password" disabled={gmsa} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          <button className={btn} disabled={!form.name || !form.username || (!form.password && !gmsa)}>+ Add credential</button>
        </form>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- enrollment tokens
function EnrollmentSection({ slug }: { slug: string }) {
  const [tokens, setTokens] = useState<EnrollmentToken[]>([]);
  const [newToken, setNewToken] = useState<EnrollmentToken | null>(null);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);

  const load = () => getEnrollmentTokens(slug).then(setTokens).catch(() => {});
  useEffect(() => { load(); }, [slug]);

  async function mint() {
    setLoading(true);
    try { setNewToken(await createEnrollmentToken(slug, "manual")); load(); } catch { /* ignore */ }
    setLoading(false);
  }
  async function revoke(id: number) { await revokeEnrollmentToken(id); load(); }
  const valid = tokens.filter((t) => t.valid).length;

  return (
    <section className={card}>
      <div className="flex items-center justify-between">
        <button className="font-semibold text-slate-800 flex items-center gap-2" onClick={() => setOpen(!open)}>
          <span className="text-slate-400 text-xs">{open ? "▼" : "▶"}</span> Enrollment tokens <span className="text-xs text-slate-400 font-normal">({valid} valid)</span>
        </button>
        {open && <button onClick={mint} disabled={loading} className={btnSm}>{loading ? "Minting…" : "+ New token"}</button>}
      </div>
      {open && (
        <>
          <p className="text-xs text-slate-500">Temporary tokens agents present once to enroll. The install command above mints one automatically; mint here only for manual use.</p>
          {newToken?.token && (
            <div className="bg-green-50 border border-green-200 rounded p-3">
              <div className="flex items-center justify-between mb-1">
                <span className="text-xs font-medium text-green-800">New enrollment token (shown once)</span>
                <CopyButton text={newToken.token} />
              </div>
              <code className="block text-sm break-all font-mono text-green-900 select-all">{newToken.token}</code>
              <p className="text-xs text-green-700 mt-1">Expires {fmtTime(newToken.expiresAt)}.</p>
            </div>
          )}
          {tokens.length === 0 ? <p className="text-sm text-slate-400">No enrollment tokens.</p> : (
            <table className="w-full text-sm">
              <thead><tr className="text-left text-slate-400">
                <th className="py-1 pr-4 font-normal">Label</th><th className="py-1 pr-4 font-normal">Expires</th>
                <th className="py-1 pr-4 font-normal">Last used</th><th className="py-1 pr-4 font-normal">Status</th><th className="py-1 font-normal"></th>
              </tr></thead>
              <tbody>
                {tokens.map((t) => (
                  <tr key={t.id} className="border-t">
                    <td className="py-1 pr-4">{t.label || "—"}</td>
                    <td className="py-1 pr-4">{fmtTime(t.expiresAt)}</td>
                    <td className="py-1 pr-4">{fmtTime(t.lastUsedAt)}</td>
                    <td className="py-1 pr-4">
                      {t.revoked ? <Badge kind="error">revoked</Badge> : t.valid ? <Badge kind="ok">valid</Badge> : <Badge kind="unknown">expired</Badge>}
                    </td>
                    <td className="py-1 text-right">
                      {!t.revoked && t.valid && <button onClick={() => revoke(t.id)} className="text-xs text-red-600 hover:text-red-800">Revoke</button>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </>
      )}
    </section>
  );
}

// ---------------------------------------------------------------- page
export default function ClientDetail() {
  const { slug } = useParams();
  const [data, setData] = useState<any>(null);
  const [error, setError] = useState("");
  const admin = isAdmin();
  const navigate = useNavigate();

  const load = () => { if (slug) getClient(slug).then(setData).catch((e) => setError(e.message)); };
  useEffect(() => { load(); }, [slug]);

  async function removeClient() {
    if (!confirm(`Delete client "${data.name}" and ALL its sites, agents, credentials and history? This cannot be undone.`)) return;
    if (prompt(`Type the client name to confirm:`) !== data.name) return;
    try { await deleteClient(data.slug); navigate("/"); } catch (err: any) { setError(err.message); }
  }

  if (error) return <p className="text-red-600">{error}</p>;
  if (!data) return <p className="text-slate-500">Loading…</p>;

  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <Link to="/" className="text-sm text-slate-500 hover:text-slate-800">← Overview</Link>
          <h2 className="text-xl font-semibold mt-1">{data.name}</h2>
        </div>
        {admin && <button onClick={removeClient} className={btnGhost + " text-red-600 hover:text-red-800"}>Delete client</button>}
      </div>

      <SitesSection client={data} onChanged={load} />
      {admin && <InstallSection client={data} />}
      <CredentialsSection client={data} />
      {admin && <EnrollmentSection slug={data.slug} />}
    </div>
  );
}
