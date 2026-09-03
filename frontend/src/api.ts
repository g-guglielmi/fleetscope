const TOKEN_KEY = "fs_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}
export function setToken(t: string) {
  localStorage.setItem(TOKEN_KEY, t);
}
export function clearToken() {
  localStorage.removeItem(TOKEN_KEY);
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
    throw new Error("Unauthorized");
  }
  if (!res.ok) throw new Error(`${res.status} ${await res.text()}`);
  return res.json() as Promise<T>;
}

export async function login(email: string, password: string): Promise<void> {
  const data = await request<{ access_token: string }>("/api/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  setToken(data.access_token);
}

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

export type EnrollmentToken = {
  id: number;
  token?: string;
  label: string | null;
  expiresAt: string;
  revoked: boolean;
  lastUsedAt: string | null;
  valid: boolean;
  note?: string;
};

export type CreateClientResult = {
  client: { slug: string; name: string };
  enrollment: EnrollmentToken;
};

export const createClient = (name: string, ttlHours?: number) =>
  request<CreateClientResult>("/api/admin/clients", {
    method: "POST",
    body: JSON.stringify({ name, ...(ttlHours ? { ttl_hours: ttlHours } : {}) }),
  });

export const getEnrollmentTokens = (clientSlug: string) =>
  request<EnrollmentToken[]>(`/api/admin/clients/${clientSlug}/enrollment-tokens`);

export const createEnrollmentToken = (clientSlug: string, label?: string, ttlHours?: number) =>
  request<EnrollmentToken>(`/api/admin/clients/${clientSlug}/enrollment-tokens`, {
    method: "POST",
    body: JSON.stringify({ label, ...(ttlHours ? { ttl_hours: ttlHours } : {}) }),
  });

export const revokeEnrollmentToken = (tokenId: number) =>
  request<{ ok: boolean }>(`/api/admin/enrollment-tokens/${tokenId}/revoke`, {
    method: "POST",
  });

export const deleteClient = (slug: string) =>
  request<{ ok: boolean }>(`/api/admin/clients/${slug}`, { method: "DELETE" });
