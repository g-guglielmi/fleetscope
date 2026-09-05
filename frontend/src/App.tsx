import { Navigate, NavLink, Route, Routes, Link, useLocation } from "react-router-dom";
import { getToken, getMe, clearToken, isAdmin } from "./api";
import Login from "./pages/Login";
import ChangePassword from "./pages/ChangePassword";
import Overview from "./pages/Overview";
import ClientDetail from "./pages/ClientDetail";
import SiteDetail from "./pages/SiteDetail";
import Users from "./pages/Users";
import AuditLog from "./pages/AuditLog";

function RequireAuth({ children }: { children: JSX.Element }) {
  const loc = useLocation();
  if (!getToken()) return <Navigate to="/login" replace />;
  const me = getMe();
  if (me?.mustChangePassword && loc.pathname !== "/change-password") return <Navigate to="/change-password" replace />;
  return children;
}

function RequireAdmin({ children }: { children: JSX.Element }) {
  return isAdmin() ? children : <Navigate to="/" replace />;
}

function Shell({ children }: { children: JSX.Element }) {
  const me = getMe();
  const link = ({ isActive }: { isActive: boolean }) =>
    `text-sm px-2 py-1 rounded ${isActive ? "bg-slate-700 text-white" : "text-slate-300 hover:text-white"}`;
  return (
    <div className="min-h-screen bg-slate-100 text-slate-800">
      <header className="bg-slate-900 text-white px-6 py-3 flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link to="/" className="font-semibold tracking-tight">FleetScope</Link>
          <nav className="flex items-center gap-1">
            <NavLink to="/" end className={link}>Overview</NavLink>
            {me?.role === "admin" && <NavLink to="/admin/users" className={link}>Users</NavLink>}
            {me?.role === "admin" && <NavLink to="/admin/audit" className={link}>Audit</NavLink>}
          </nav>
        </div>
        <div className="flex items-center gap-3 text-sm">
          {me && (
            <Link to="/change-password" className="text-slate-300 hover:text-white" title="Change password">
              {me.email} <span className="text-slate-500">({me.role})</span>
            </Link>
          )}
          <button onClick={() => { clearToken(); location.href = "/login"; }} className="text-slate-300 hover:text-white">
            Sign out
          </button>
        </div>
      </header>
      <main className="p-6 max-w-6xl mx-auto">{children}</main>
    </div>
  );
}

const page = (el: JSX.Element) => <RequireAuth><Shell>{el}</Shell></RequireAuth>;
const adminPage = (el: JSX.Element) => <RequireAuth><RequireAdmin><Shell>{el}</Shell></RequireAdmin></RequireAuth>;

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/change-password" element={<RequireAuth><ChangePassword /></RequireAuth>} />
      <Route path="/" element={page(<Overview />)} />
      <Route path="/clients/:slug" element={page(<ClientDetail />)} />
      <Route path="/clients/:slug/sites/:site" element={page(<SiteDetail />)} />
      <Route path="/admin/users" element={adminPage(<Users />)} />
      <Route path="/admin/audit" element={adminPage(<AuditLog />)} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
