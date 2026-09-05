import { useEffect, useState } from "react";
import { listUsers, createUser, updateUser, deleteUser, getMe, Role, User } from "../api";
import { Badge, ErrorText, btn, card, fmtTime, input } from "../components";

export default function Users() {
  const me = getMe();
  const [users, setUsers] = useState<User[]>([]);
  const [error, setError] = useState("");
  const [form, setForm] = useState({ email: "", password: "", role: "viewer" as Role });
  const [created, setCreated] = useState<{ email: string; password: string } | null>(null);

  const load = () => listUsers().then(setUsers).catch((e) => setError(e.message));
  useEffect(() => { load(); }, []);

  async function add(e: React.FormEvent) {
    e.preventDefault(); setError(""); setCreated(null);
    try {
      await createUser(form.email.trim(), form.password, form.role);
      setCreated({ email: form.email.trim(), password: form.password });
      setForm({ email: "", password: "", role: "viewer" });
      load();
    } catch (err: any) { setError(err.message); }
  }
  async function patch(u: User, body: { role?: Role; disabled?: boolean; password?: string }) {
    setError("");
    try { await updateUser(u.id, body); load(); } catch (err: any) { setError(err.message); }
  }
  async function resetPassword(u: User) {
    const pw = prompt(`Temporary password for ${u.email} (min. 12 characters). They must change it at next login.`);
    if (!pw) return;
    await patch(u, { password: pw });
  }
  async function remove(u: User) {
    if (!confirm(`Delete user ${u.email}?`)) return;
    setError("");
    try { await deleteUser(u.id); load(); } catch (err: any) { setError(err.message); }
  }

  function genPassword() {
    const chars = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789!@#$%&*";
    const arr = new Uint32Array(20); crypto.getRandomValues(arr);
    setForm({ ...form, password: Array.from(arr, (n) => chars[n % chars.length]).join("") });
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-semibold">Users</h2>
      <section className={card}>
        <p className="text-sm text-slate-500">
          <strong>admin</strong> manages clients, sites, credentials, users. <strong>viewer</strong> is read-only. New users must change their password at first login.
        </p>
        <ErrorText error={error} />
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead><tr className="text-left text-slate-400">
              <th className="py-1 pr-4 font-normal">Email</th><th className="py-1 pr-4 font-normal">Role</th><th className="py-1 pr-4 font-normal">Status</th>
              <th className="py-1 pr-4 font-normal">Last login</th><th className="py-1 pr-4 font-normal">Created</th><th className="py-1 font-normal"></th>
            </tr></thead>
            <tbody>
              {users.map((u) => {
                const self = u.email === me?.email;
                return (
                  <tr key={u.id} className="border-t">
                    <td className="py-1 pr-4">{u.email}{self && <span className="text-xs text-slate-400"> (you)</span>}</td>
                    <td className="py-1 pr-4">
                      <select className="border rounded px-1 py-0.5 text-xs" value={u.role} disabled={self} onChange={(e) => patch(u, { role: e.target.value as Role })}>
                        <option value="admin">admin</option><option value="viewer">viewer</option>
                      </select>
                    </td>
                    <td className="py-1 pr-4 space-x-1">
                      {u.disabled ? <Badge kind="error">disabled</Badge> : <Badge kind="ok">active</Badge>}
                      {u.mustChangePassword && <Badge kind="warn">password change pending</Badge>}
                    </td>
                    <td className="py-1 pr-4 text-xs text-slate-500">{fmtTime(u.lastLogin)}</td>
                    <td className="py-1 pr-4 text-xs text-slate-500">{fmtTime(u.createdAt)}</td>
                    <td className="py-1 text-right whitespace-nowrap text-xs">
                      <button className="text-slate-700 hover:text-slate-900 mr-3" onClick={() => resetPassword(u)}>Reset password</button>
                      {!self && <button className="text-slate-700 hover:text-slate-900 mr-3" onClick={() => patch(u, { disabled: !u.disabled })}>{u.disabled ? "Enable" : "Disable"}</button>}
                      {!self && <button className="text-red-600 hover:text-red-800" onClick={() => remove(u)}>Delete</button>}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </section>

      <section className={card}>
        <h3 className="font-semibold text-slate-800">Add user</h3>
        {created && (
          <div className="bg-green-50 border border-green-200 rounded p-3 text-sm">
            Created <strong>{created.email}</strong>. Temporary password (shown once): <code className="font-mono select-all">{created.password}</code>
          </div>
        )}
        <form onSubmit={add} className="grid gap-2 sm:grid-cols-4 items-end">
          <div><label className="text-xs text-slate-500">Email</label><input className={input} type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></div>
          <div><label className="text-xs text-slate-500">Temporary password <button type="button" className="ml-1 underline" onClick={genPassword}>generate</button></label>
            <input className={input} type="text" autoComplete="off" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /></div>
          <div><label className="text-xs text-slate-500">Role</label>
            <select className={input} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value as Role })}><option value="viewer">viewer</option><option value="admin">admin</option></select></div>
          <button className={btn} disabled={!form.email || form.password.length < 12}>+ Add user</button>
        </form>
      </section>
    </div>
  );
}
