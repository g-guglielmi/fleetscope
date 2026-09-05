import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { changePassword, getMe, setMe, clearToken } from "../api";

export default function ChangePassword() {
  const me = getMe();
  const forced = !!me?.mustChangePassword;
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [confirm, setConfirm] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    if (next.length < 12) return setError("New password must be at least 12 characters.");
    if (next !== confirm) return setError("Passwords do not match.");
    setBusy(true);
    try {
      await changePassword(current, next);
      if (me) setMe({ ...me, mustChangePassword: false });
      navigate("/");
    } catch (err: any) {
      setError(err.message || "Failed to change password");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100">
      <form onSubmit={submit} className="bg-white rounded-lg shadow p-8 w-96 space-y-4">
        <h1 className="text-lg font-semibold text-slate-800">Change password</h1>
        {forced ? (
          <p className="text-sm text-amber-700 bg-amber-50 border border-amber-200 rounded p-2">
            Your password was set by an administrator. Choose a new one to continue.
          </p>
        ) : (
          <p className="text-sm text-slate-500">Signed in as {me?.email}</p>
        )}
        <input className="w-full border rounded px-3 py-2 text-sm" type="password" autoComplete="current-password"
          placeholder="Current password" value={current} onChange={(e) => setCurrent(e.target.value)} />
        <input className="w-full border rounded px-3 py-2 text-sm" type="password" autoComplete="new-password"
          placeholder="New password (min. 12 characters)" value={next} onChange={(e) => setNext(e.target.value)} />
        <input className="w-full border rounded px-3 py-2 text-sm" type="password" autoComplete="new-password"
          placeholder="Confirm new password" value={confirm} onChange={(e) => setConfirm(e.target.value)} />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button disabled={busy} className="w-full bg-slate-900 text-white rounded py-2 text-sm hover:bg-slate-700 disabled:opacity-50">
          {busy ? "Saving…" : "Change password"}
        </button>
        <div className="flex justify-between text-xs text-slate-500">
          {!forced && <Link to="/" className="hover:text-slate-800">← Back</Link>}
          <button type="button" onClick={() => { clearToken(); location.href = "/login"; }} className="hover:text-slate-800">Sign out</button>
        </div>
      </form>
    </div>
  );
}
