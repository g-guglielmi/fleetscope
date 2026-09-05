import { useEffect, useState } from "react";
import { getAudit, AuditEntry } from "../api";
import { ErrorText, card, fmtTime, input } from "../components";

export default function AuditLog() {
  const [rows, setRows] = useState<AuditEntry[]>([]);
  const [error, setError] = useState("");
  const [filter, setFilter] = useState("");

  useEffect(() => { getAudit(500).then(setRows).catch((e) => setError(e.message)); }, []);

  const q = filter.toLowerCase();
  const shown = q ? rows.filter((r) => `${r.actor} ${r.action} ${r.targetType} ${r.targetId} ${JSON.stringify(r.detail)}`.toLowerCase().includes(q)) : rows;

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between">
        <h2 className="text-xl font-semibold">Audit log</h2>
        <input className={input + " max-w-xs"} placeholder="filter…" value={filter} onChange={(e) => setFilter(e.target.value)} />
      </div>
      <section className={card}>
        <ErrorText error={error} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-400">
              <th className="py-1 pr-4 font-normal">When</th><th className="py-1 pr-4 font-normal">Actor</th><th className="py-1 pr-4 font-normal">Action</th>
              <th className="py-1 pr-4 font-normal">Target</th><th className="py-1 pr-4 font-normal">Detail</th><th className="py-1 font-normal">IP</th>
            </tr></thead>
            <tbody>
              {shown.map((r) => (
                <tr key={r.id} className="border-t align-top">
                  <td className="py-1 pr-4 whitespace-nowrap text-xs text-slate-500">{fmtTime(r.at)}</td>
                  <td className="py-1 pr-4 text-xs">{r.actor}</td>
                  <td className="py-1 pr-4 font-mono text-xs">{r.action}</td>
                  <td className="py-1 pr-4 text-xs">{r.targetType}{r.targetId ? ` ${r.targetId}` : ""}</td>
                  <td className="py-1 pr-4 text-xs font-mono text-slate-600 max-w-md break-all">{r.detail ? JSON.stringify(r.detail) : ""}</td>
                  <td className="py-1 text-xs text-slate-400">{r.ip || ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && <p className="text-sm text-slate-400">No entries.</p>}
        </div>
      </section>
    </div>
  );
}
