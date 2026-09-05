const TOKEN_KEY = "fs_token";
const ME_KEY = "fs_me";

export type Role = "admin" | "viewer";
export type Me = { email: string; role: Role; mustChangePassword: boolean };

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
  localStorage.removeItem(ME_KEY);
}
export function getMe(): Me | null {
  try {
    const s = localStorage.getItem(ME_KEY);
    return s ? (JSON.parse(s) as Me) : null;
  } catch {
    return null;
  }
}
export function setMe(m: Me | null) {
  if (m) localStorage.setItem(ME_KEY, JSON.stringify(m));
  else localStorage.removeItem(ME_KEY);
}
export function isAdmin(): boolean {
  return getMe()?.role === "admin";
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const res = await fetch(path, {
    ...options,
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  });
  if (res.status === 401) {
    clearToken();
    if (!location.pathname.startsWith("/login")) location.href = "/login";
    throw new ApiError(401, "Unauthorized");
  }
  if (!res.ok) {
    const text = await res.text();
    let detail = text;
    try {
      const j = JSON.parse(text);
      detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch { /* plain text */ }
    if (res.status === 403 && detail === "Password change required") {
      const me = getMe();
      if (me) setMe({ ...me, mustChangePassword: true });
      location.href = "/change-password";
    }
    throw new ApiError(res.status, detail || `${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

// ---- auth ----
export async function login(email: string, password: string): Promise<Me> {
  const data = await request<{ access_token: string; role: Role; mustChangePassword: boolean }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
  const me = { email, role: data.role, mustChangePassword: data.mustChangePassword };
  setMe(me);
  return me;
}
export const changePassword = (currentPassword: string, newPassword: string) =>
  request<{ ok: boolean }>("/api/auth/change-password", { method: "POST", body: JSON.stringify({ currentPassword, newPassword }) });

// ---- overview / clients ----
export type OverviewClient = {
  slug: string;
  name: string;
  sites: number;
  collectors: number;
  status: "ok" | "stale" | "offline" | "unknown";
  lastSeen: string | null;
  openFindings: number;
  criticalFindings: number;
  nearestCertExpiry: string | null;
  nearestLicenseExpiry: string | null;
};
export const getOverview = () => request<OverviewClient[]>("/api/overview");
export const getClient = (slug: string) => request<any>(`/api/clients/${slug}`);
export const createSite = (clientSlug: string, name: string) =>
  request<{ slug: string; name: string }>(`/api/clients/${clientSlug}/sites`, { method: "POST", body: JSON.stringify({ name }) });

export type EnrollmentToken = {
  id: number; token?: string; label: string | null; expiresAt: string;
  revoked: boolean; lastUsedAt: string | null; valid: boolean; note?: string;
};
export type CreateClientResult = { client: { slug: string; name: string }; enrollment: EnrollmentToken };

export const createClient = (name: string, ttlHours?: number) =>
  request<CreateClientResult>("/api/admin/clients", {
    method: "POST",
    body: JSON.stringify({ name, ...(ttlHours ? { ttl_hours: ttlHours } : {}) }),
  });
export const deleteClient = (slug: string) => request<void>(`/api/admin/clients/${slug}`, { method: "DELETE" });
export const getEnrollmentTokens = (clientSlug: string) =>
  request<EnrollmentToken[]>(`/api/admin/clients/${clientSlug}/enrollment-tokens`);
export const createEnrollmentToken = (clientSlug: string, label?: string, ttlHours?: number) =>
  request<EnrollmentToken>(`/api/admin/clients/${clientSlug}/enrollment-tokens`, {
    method: "POST",
    body: JSON.stringify({ label, ...(ttlHours ? { ttl_hours: ttlHours } : {}) }),
  });
export const revokeEnrollmentToken = (tokenId: number) =>
  request<{ ok: boolean }>(`/api/admin/enrollment-tokens/${tokenId}/revoke`, { method: "POST" });

export type InstallCommand = { command: string; enrollment: EnrollmentToken; warnings: string[] };
export const installCommand = (clientSlug: string, site?: string) =>
  request<InstallCommand>(`/api/admin/clients/${clientSlug}/install-command`, { method: "POST", body: JSON.stringify({ site }) });

// ---- credentials ----
export type CredentialKind = "device" | "windows";
export type Credential = {
  id: number; client: string; name: string; kind: CredentialKind; username: string; version: number; gmsa: boolean;
  updatedAt: string; updatedBy: string | null;
  referencedBy: { site: string; siteName: string }[];
  heldBy: { site: string; agent: string; version: number; current: boolean }[];
};
export const listCredentials = (clientSlug: string) => request<Credential[]>(`/api/admin/credentials?client=${encodeURIComponent(clientSlug)}`);
export const createCredential = (body: { client: string; name: string; kind: CredentialKind; username: string; password: string }) =>
  request<Credential>("/api/admin/credentials", { method: "POST", body: JSON.stringify(body) });
export const updateCredential = (id: number, body: { username?: string; password?: string }) =>
  request<Credential>(`/api/admin/credentials/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteCredential = (id: number) => request<void>(`/api/admin/credentials/${id}`, { method: "DELETE" });

// ---- site config ----
export type SchemaNode = string | { type: string; required?: boolean; label?: string; help?: string; item?: any; kind?: string };
export type CheckDef = { name: string; version: string; description: string; requires: string[]; timeoutSeconds: number; settingsSchema: Record<string, SchemaNode> };
export type SiteConfig = {
  intervalMinutes: number; autoUpdate: boolean;
  agent: { serviceAccount?: string | null };
  prerequisites: { unattended?: boolean; citrixSdkSource?: string | null };
  checks: Record<string, { enabled: boolean; settings: Record<string, any> }>;
  updatedAt?: string | null; updatedBy?: string | null;
};
export type SiteConfigResponse = {
  client: { slug: string; name: string }; site: { slug: string; name: string };
  config: SiteConfig; checks: CheckDef[]; manifestSigned: boolean;
  credentials: { name: string; kind: CredentialKind; username: string; version: number }[];
  missingCredentials: string[];
};
export const getSiteConfig = (client: string, site: string) => request<SiteConfigResponse>(`/api/sites/${client}/${site}/config`);
export const putSiteConfig = (client: string, site: string, config: SiteConfig) =>
  request<{ ok: boolean; config: SiteConfig }>(`/api/sites/${client}/${site}/config`, { method: "PUT", body: JSON.stringify(config) });
export const siteAction = (client: string, site: string, action: "run-now" | "restart") =>
  request<{ ok: boolean; queued: number }>(`/api/sites/${client}/${site}/actions/${action}`, { method: "POST" });

// ---- users / audit ----
export type User = { id: number; email: string; role: Role; disabled: boolean; mustChangePassword: boolean; lastLogin: string | null; createdAt: string };
export const listUsers = () => request<User[]>("/api/admin/users");
export const createUser = (email: string, password: string, role: Role) =>
  request<User>("/api/admin/users", { method: "POST", body: JSON.stringify({ email, password, role }) });
export const updateUser = (id: number, body: { role?: Role; disabled?: boolean; password?: string }) =>
  request<User>(`/api/admin/users/${id}`, { method: "PATCH", body: JSON.stringify(body) });
export const deleteUser = (id: number) => request<void>(`/api/admin/users/${id}`, { method: "DELETE" });

export type AuditEntry = { id: number; at: string; actor: string; action: string; targetType: string; targetId: string | null; detail: any; ip: string | null };
export const getAudit = (limit = 200) => request<AuditEntry[]>(`/api/admin/audit?limit=${limit}`);
