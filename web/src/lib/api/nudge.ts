import type { ParseResponse, Reminder, ReminderCreate, Note } from "../types/nudge";

const NUDGE_BASE = `${window.location.protocol}//${window.location.hostname}:8002`;

function getAuthHeaders(): Record<string, string> {
  const token = localStorage.getItem("alfred_token");
  return token ? { Authorization: `Bearer ${token}` } : {};
}

function clearSessionAndRedirect() {
  localStorage.removeItem("alfred_token");
  localStorage.removeItem("alfred_user");
  localStorage.removeItem("ourcents_token");
  window.location.href = "/login";
}

async function request<T>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${NUDGE_BASE}${path}`, {
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

export function patchReminder(id: string, status: "active" | "paused" | "done"): Promise<Reminder> {
  return request<Reminder>(`/api/nudge/reminders/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function deleteReminder(id: string): Promise<void> {
  return request<void>(`/api/nudge/reminders/${id}`, { method: "DELETE" });
}

export function listNotes(): Promise<Note[]> {
  return request<Note[]>("/api/nudge/notes");
}

export function createNote(content: string, tags?: string[]): Promise<Note> {
  return request<Note>("/api/nudge/notes", {
    method: "POST",
    body: JSON.stringify({ content, tags }),
  });
}

export function deleteNote(id: string): Promise<void> {
  return request<void>(`/api/nudge/notes/${id}`, { method: "DELETE" });
}
