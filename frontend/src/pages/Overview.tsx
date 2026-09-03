import { useEffect, useState, useRef } from "react";
import { Link } from "react-router-dom";
import { getOverview, createClient, OverviewClient, CreateClientResult } from "../api";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-green-100 text-green-700",
  stale: "bg-amber-100 text-amber-700",
  offline: "bg-red-100 text-red-700",
  unknown: "bg-slate-200 text-slate-600",
};

function fmt(d: string | null) {
  return d ? new Date(d).toLocaleDateString() : "—";
}

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

function AddClientDialog({ onClose, onCreated }: { onClose: () => void; onCreated: () => void }) {
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [result, setResult] = useState<CreateClientResult | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => { inputRef.current?.focus(); }, []);

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    if (!name.trim()) return;
    setLoading(true);
    setError("");
    try {
      const res = await createClient(name.trim());
      setResult(res);
      onCreated();
    } catch (err: any) {
      setError(err.message || "Failed to create client");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50" onClick={onClose}>
      <div className="bg-white rounded-lg shadow-xl w-full max-w-md mx-4 p-6" onClick={(e) => e.stopPropagation()}>
        {!result ? (
          <>
            <h3 className="text-lg font-semibold mb-4">Add Client</h3>
            <form onSubmit={submit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-700 mb-1">Client name</label>
                <input
                  ref={inputRef}
                  className="w-full border rounded px-3 py-2 text-sm"
                  placeholder="e.g. ACME Corp"
                  value={name}
                  onChange={(e) => setName(e.target.value)}
                />
              </div>
              {error && <p className="text-sm text-red-600">{error}</p>}
              <div className="flex justify-end gap-2">
                <button type="button" onClick={onClose} className="px-4 py-2 text-sm text-slate-600 hover:text-slate-800">
                  Cancel
                </button>
                <button
                  type="submit"
                  disabled={loading || !name.trim()}
                  className="px-4 py-2 text-sm bg-slate-900 text-white rounded hover:bg-slate-700 disabled:opacity-50"
                >
                  {loading ? "Creating…" : "Create"}
                </button>
              </div>
            </form>
          </>
        ) : (
          <>
            <h3 className="text-lg font-semibold mb-1">Client created</h3>
            <p className="text-sm text-slate-600 mb-4">
              <span className="font-medium">{result.client.name}</span> is ready.
              Use the enrollment token below in the collector's <code className="text-xs bg-slate-100 px-1 py-0.5 rounded">config.json</code>.
            </p>
            <div className="bg-slate-50 border rounded p-3 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs text-slate-500">Enrollment token</span>
                {result.enrollment.token && <CopyButton text={result.enrollment.token} />}
              </div>
              <code className="block text-sm break-all font-mono text-slate-800 select-all">
                {result.enrollment.token}
              </code>
              <p className="text-xs text-slate-500">
                Expires {new Date(result.enrollment.expiresAt).toLocaleString()}.
                The probe swaps it for a permanent token on first push.
              </p>
            </div>
            <div className="mt-4 flex justify-end">
              <button onClick={onClose} className="px-4 py-2 text-sm bg-slate-900 text-white rounded hover:bg-slate-700">
                Done
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

export default function Overview() {
  const [clients, setClients] = useState<OverviewClient[]>([]);
  const [error, setError] = useState("");
  const [showAdd, setShowAdd] = useState(false);

  const load = () => getOverview().then(setClients).catch((e) => setError(String(e)));
  useEffect(() => { load(); }, []);

  if (error) return <p className="text-red-600">{error}</p>;

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-xl font-semibold">Overview</h2>
        <button
          onClick={() => setShowAdd(true)}
          className="px-4 py-2 text-sm bg-slate-900 text-white rounded hover:bg-slate-700"
        >
          + Add Client
        </button>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {clients.map((c) => (
          <Link
            key={c.slug} to={`/clients/${c.slug}`}
            className="block bg-white rounded-lg shadow p-4 hover:shadow-md transition"
          >
            <div className="flex items-center justify-between">
              <span className="font-medium">{c.name}</span>
              <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[c.status]}`}>
                {c.status}
              </span>
            </div>
            <div className="mt-3 text-sm text-slate-500 grid grid-cols-2 gap-y-1">
              <span>Sites</span><span className="text-right text-slate-800">{c.sites}</span>
              <span>Collectors</span><span className="text-right text-slate-800">{c.collectors}</span>
              <span>Open findings</span>
              <span className={`text-right ${c.criticalFindings ? "text-red-600 font-semibold" : "text-slate-800"}`}>
                {c.openFindings}{c.criticalFindings ? ` (${c.criticalFindings} crit)` : ""}
              </span>
              <span>Next cert expiry</span><span className="text-right text-slate-800">{fmt(c.nearestCertExpiry)}</span>
              <span>Next license expiry</span><span className="text-right text-slate-800">{fmt(c.nearestLicenseExpiry)}</span>
              <span>Last seen</span>
              <span className="text-right text-slate-800">
                {c.lastSeen ? new Date(c.lastSeen).toLocaleString() : "never"}
              </span>
            </div>
          </Link>
        ))}
      </div>

      {clients.length === 0 && (
        <p className="text-slate-500 mt-4">
          No clients yet. Click <strong>+ Add Client</strong> above to get started.
        </p>
      )}

      {showAdd && <AddClientDialog onClose={() => setShowAdd(false)} onCreated={load} />}
    </div>
  );
}
