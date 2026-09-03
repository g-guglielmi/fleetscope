import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getOverview, OverviewClient } from "../api";

const STATUS_STYLES: Record<string, string> = {
  ok: "bg-green-100 text-green-700",
  stale: "bg-amber-100 text-amber-700",
  offline: "bg-red-100 text-red-700",
  unknown: "bg-slate-200 text-slate-600",
};

function fmt(d: string | null) {
  return d ? new Date(d).toLocaleDateString() : "—";
}

export default function Overview() {
  const [clients, setClients] = useState<OverviewClient[]>([]);
  const [error, setError] = useState("");

  useEffect(() => {
    getOverview().then(setClients).catch((e) => setError(String(e)));
  }, []);

  if (error) return <p className="text-red-600">{error}</p>;

  return (
    <div>
      <h2 className="text-xl font-semibold mb-4">Overview</h2>
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
        <p className="text-slate-500">No clients yet. Enroll one via the admin API.</p>
      )}
    </div>
  );
}
