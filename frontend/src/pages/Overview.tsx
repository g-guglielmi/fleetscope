import { useEffect, useState, useRef } from "react";
import { Link, useNavigate } from "react-router-dom";
import { getOverview, createClient, isAdmin, OverviewClient } from "../api";
import { Badge, btn, btnGhost, fmtDate, fmtTime, input } from "../components";

function AddClientDialog({ onClose }: { onClose: () => void }) {
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await createClient(name.trim());
      navigate(`/clients/${res.client.slug}`);
    } catch (err: any) {
      setError(err.message || "Failed to create client");
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6" onClick={(e) => e.stopPropagation()}>
        <h3 className="text-lg font-semibold mb-4">Add Client</h3>
        <form onSubmit={submit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-700 mb-1">Client name</label>
            <input ref={inputRef} className={input} placeholder="e.g. ACME Corp" value={name} onChange={(e) => setName(e.target.value)} />
          </div>
          <p className="text-xs text-slate-500">
            Next you'll add the client's sites and credentials, then generate the agent install command.
          </p>
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex justify-end gap-2">
            <button type="button" onClick={onClose} className={btnGhost}>Cancel</button>
            <button type="submit" disabled={loading || !name.trim()} className={btn}>{loading ? "Creating…" : "Create"}</button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function Overview() {
  const [clients, setClients] = useState<OverviewClient[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);
  const admin = isAdmin();

  const load = () => getOverview().then(setClients).catch((e) => setError(String(e.message || e)));
  useEffect(() => {
    load();
    const t = setInterval(load, 60_000);
    return () => clearInterval(t);
  }, []);

  if (error) return <p className="text-red-600">{error}</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Overview</h2>
        {admin && <button onClick={() => setShowAdd(true)} className={btn}>+ Add Client</button>}
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {clients.map((c) => (
          <Link key={c.slug} to={`/clients/${c.slug}`} className="block bg-white rounded-lg shadow p-4 hover:shadow-md transition">
            <div className="flex items-center justify-between">
              <span className="font-medium">{c.name}</span>
              <Badge kind={c.status}>{c.status}</Badge>
            </div>
            <div className="mt-3 text-sm text-slate-500 grid grid-cols-2 gap-y-1">
              <span>Sites</span><span className="text-right text-slate-800">{c.sites}</span>
              <span>Agents</span><span className="text-right text-slate-800">{c.collectors}</span>
              <span>Open findings</span>
              <span className={`text-right ${c.criticalFindings ? "text-red-600 font-semibold" : "text-slate-800"}`}>
                {c.openFindings}{c.criticalFindings ? ` (${c.criticalFindings} crit)` : ""}
              </span>
              <span>Next cert expiry</span><span className="text-right text-slate-800">{fmtDate(c.nearestCertExpiry)}</span>
              <span>Next license expiry</span><span className="text-right text-slate-800">{fmtDate(c.nearestLicenseExpiry)}</span>
              <span>Last seen</span><span className="text-right text-slate-800">{fmtTime(c.lastSeen)}</span>
            </div>
          </Link>
        ))}
      </div>

      {clients.length === 0 && (
        <p className="text-slate-500 mt-4">
          No clients yet.{admin ? <> Click <strong>+ Add Client</strong> above to get started.</> : ""}
        </p>
      )}

      {showAdd && <AddClientDialog onClose={() => setShowAdd(false)} />}
    </div>
  );
}
