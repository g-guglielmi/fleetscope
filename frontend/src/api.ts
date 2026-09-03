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
