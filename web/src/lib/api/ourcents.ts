const OURCENTS_BASE = `${window.location.protocol}//${window.location.hostname}:8001`;

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("ourcents_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function clearSessionAndRedirect() {
  localStorage.removeItem("alfred_token");
  localStorage.removeItem("alfred_user");
  localStorage.removeItem("ourcents_token");
  window.location.href = "/login";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${OURCENTS_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    ...options,
  });
  if (res.status === 401) {
    clearSessionAndRedirect();
    throw new Error("Session expired");
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface LoginResponse {
  access_token: string;
  user_id: number;
  family_id: number;
  username: string;
  family_name: string;
  is_admin: boolean;
}

export async function register(familyName: string, username: string, password: string): Promise<void> {
  await fetch(`${OURCENTS_BASE}/api/ourcents/auth/register`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      family_name: familyName,
      admin_username: username,
      admin_email: `${username}@alfred.local`,
      admin_password: password,
    }),
  });
  // ignore errors (e.g. already registered)
}

export async function login(username: string, password: string): Promise<LoginResponse> {
  const data = await request<LoginResponse>("/api/ourcents/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
  localStorage.setItem("ourcents_token", data.access_token);
  localStorage.setItem("ourcents_user", JSON.stringify(data));
  return data;
}

export function logout() {
  localStorage.removeItem("ourcents_token");
  localStorage.removeItem("ourcents_user");
}

export function getDashboard(period = "month") {
  return request<Record<string, unknown>>(`/api/ourcents/dashboard?period=${period}`);
}

export function getDashboardSummary() {
  return request<Record<string, unknown>>("/api/ourcents/dashboard/summary");
}

export function listReceipts(params?: { status_filter?: string; days_back?: number }) {
  const qs = new URLSearchParams();
  if (params?.status_filter) qs.set("status_filter", params.status_filter);
  if (params?.days_back) qs.set("days_back", String(params.days_back));
  return request<Record<string, unknown>[]>(`/api/ourcents/receipts?${qs}`);
}

export function getReceipt(id: number) {
  return request<Record<string, unknown>>(`/api/ourcents/receipts/${id}`);
}

export async function uploadReceipt(file: File) {
  const form = new FormData();
  form.append("file", file);
  const res = await fetch(`${OURCENTS_BASE}/api/ourcents/receipts/upload`, {
    method: "POST",
    headers: getAuthHeaders(),
    body: form,
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export function confirmReceipt(id: number, body: Record<string, unknown>) {
  return request<void>(`/api/ourcents/receipts/${id}/confirm`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function getRules() {
  return request<Record<string, unknown>>("/api/ourcents/settings/rules");
}

// ── Phone bindings ──────────────────────────────────────────────

export interface PhoneBinding {
  id: number;
  phone: string;
  username: string;
  created_at: string;
}

export function listPhoneBindings() {
  return request<PhoneBinding[]>("/api/ourcents/phone/bindings");
}

export function bindPhone(phone: string) {
  return request<void>("/api/ourcents/phone/bind", {
    method: "POST",
    body: JSON.stringify({ phone }),
  });
}

export function unbindPhone(phone: string) {
  return request<void>(`/api/ourcents/phone/bindings/${encodeURIComponent(phone)}`, {
    method: "DELETE",
  });
}
