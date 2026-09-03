import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { login } from "../api";

export default function Login() {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const navigate = useNavigate();

  async function submit(e: React.FormEvent) {
    e.preventDefault();
    setError("");
    try {
      await login(email, password);
      navigate("/");
    } catch {
      setError("Invalid credentials");
    }
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-slate-100">
      <form onSubmit={submit} className="bg-white rounded-lg shadow p-8 w-80 space-y-4">
        <h1 className="text-lg font-semibold text-slate-800">FleetScope</h1>
        <input
          className="w-full border rounded px-3 py-2 text-sm"
          placeholder="Email" value={email} onChange={(e) => setEmail(e.target.value)}
        />
        <input
          className="w-full border rounded px-3 py-2 text-sm" type="password"
          placeholder="Password" value={password} onChange={(e) => setPassword(e.target.value)}
        />
        {error && <p className="text-sm text-red-600">{error}</p>}
        <button className="w-full bg-slate-900 text-white rounded py-2 text-sm hover:bg-slate-700">
          Sign in
        </button>
      </form>
    </div>
  );
}
