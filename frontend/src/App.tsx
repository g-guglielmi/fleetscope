import { Navigate, Route, Routes, Link } from "react-router-dom";
import { getToken, clearToken } from "./api";
import Login from "./pages/Login";
import Overview from "./pages/Overview";
import ClientDetail from "./pages/ClientDetail";

function RequireAuth({ children }: { children: JSX.Element }) {
  return getToken() ? children : <Navigate to="/login" replace />;
}

function Shell({ children }: { children: JSX.Element }) {
  return (
    <div className="min-h-screen bg-slate-100 text-slate-800">
      <header className="bg-slate-900 text-white px-6 py-3 flex items-center justify-between">
        <Link to="/" className="font-semibold tracking-tight">FleetScope</Link>
        <button
          onClick={() => { clearToken(); location.href = "/login"; }}
          className="text-sm text-slate-300 hover:text-white"
        >
          Sign out
        </button>
      </header>
      <main className="p-6 max-w-6xl mx-auto">{children}</main>
    </div>
  );
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<RequireAuth><Shell><Overview /></Shell></RequireAuth>} />
      <Route path="/clients/:slug" element={<RequireAuth><Shell><ClientDetail /></Shell></RequireAuth>} />
    </Routes>
  );
}
