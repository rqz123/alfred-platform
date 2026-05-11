import type { GraphData, Weaving } from "../types/brain";

const BRAIN_BASE = `${window.location.protocol}//${window.location.hostname}:8003`;

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("alfred_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${BRAIN_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function fetchGraph(familyId: string): Promise<GraphData> {
  return request<GraphData>(`/api/brain/graph/${familyId}`);
}

export function fetchWeavings(familyId: string): Promise<Weaving[]> {
  return request<Weaving[]>(`/api/brain/weavings/${familyId}`);
}

export function confirmWeaving(id: string): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/brain/weavings/${id}/confirm`, {
    method: "POST",
  });
}

export function correctWeaving(
  id: string,
  familyId: string,
  reason?: string
): Promise<{ ok: boolean }> {
  return request<{ ok: boolean }>(`/api/brain/weavings/${id}/correct`, {
    method: "POST",
    body: JSON.stringify({ family_id: familyId, reason }),
  });
}
