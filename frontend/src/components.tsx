import { useState } from "react";

export const STATUS_STYLES: Record<string, string> = {
  ok: "bg-green-100 text-green-700",
  stale: "bg-amber-100 text-amber-700",
  offline: "bg-red-100 text-red-700",
  unknown: "bg-slate-200 text-slate-600",
  error: "bg-red-100 text-red-700",
  warn: "bg-amber-100 text-amber-700",
  skipped: "bg-slate-200 text-slate-600",
};

export function Badge({ kind, children }: { kind: string; children: React.ReactNode }) {
  return <span className={`text-xs px-2 py-0.5 rounded-full ${STATUS_STYLES[kind] || "bg-slate-200 text-slate-600"}`}>{children}</span>;
}

export function fmtDate(d: string | null | undefined) {
  return d ? new Date(d).toLocaleDateString() : "—";
}
export function fmtTime(d: string | null | undefined) {
  return d ? new Date(d).toLocaleString() : "never";
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      type="button"
      onClick={() => { navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 2000); }}
      className="ml-2 px-2 py-0.5 text-xs rounded bg-slate-200 hover:bg-slate-300 text-slate-700"
    >
      {copied ? "Copied!" : label}
    </button>
  );
}

export const btn = "px-3 py-1.5 text-sm bg-slate-900 text-white rounded hover:bg-slate-700 disabled:opacity-50";
export const btnSm = "px-2 py-1 text-xs bg-slate-900 text-white rounded hover:bg-slate-700 disabled:opacity-50";
export const btnGhost = "px-3 py-1.5 text-sm text-slate-600 hover:text-slate-900";
export const input = "border rounded px-2 py-1.5 text-sm w-full disabled:bg-slate-50 disabled:text-slate-500";
export const card = "bg-white rounded-lg shadow p-5 space-y-4";

export function ErrorText({ error }: { error: string }) {
  return error ? <p className="text-sm text-red-600 whitespace-pre-wrap">{error}</p> : null;
}

export function Table({ title, rows, cols, headers, render, empty = "None." }: any) {
  const finalHeaders = headers || (cols ? cols.map((c: any) => c[1]) : []);
  return (
    <div>
      {title && <h4 className="text-sm font-medium text-slate-500 mb-2">{title} ({rows.length})</h4>}
      {rows.length === 0 ? (
        <p className="text-sm text-slate-400">{empty}</p>
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
