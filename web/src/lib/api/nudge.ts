import type { ParseResponse, Reminder, ReminderCreate } from "../types/nudge";

const NUDGE_BASE = `${window.location.protocol}//${window.location.hostname}:8002`;

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("alfred_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${NUDGE_BASE}${path}`, {
    headers: { "Content-Type": "application/json", ...getAuthHeaders() },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || `HTTP ${res.status}`);
  }
  return res.json() as Promise<T>;
}

export function parseReminder(
  input: string,
  timezone: string
): Promise<ParseResponse> {
  return request<ParseResponse>("/api/nudge/parse", {
    method: "POST",
    body: JSON.stringify({ input, timezone }),
  });
}

export function saveReminder(data: ReminderCreate): Promise<Reminder> {
  return request<Reminder>("/api/nudge/reminders", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function listReminders(): Promise<Reminder[]> {
  return request<Reminder[]>("/api/nudge/reminders");
}
