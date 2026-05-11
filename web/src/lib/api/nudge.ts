import type { ParseResponse, Reminder, ReminderCreate, Thread } from "../types/nudge";

const THREAD_BASE = `${window.location.protocol}//${window.location.hostname}:8002`;

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
  const res = await fetch(`${THREAD_BASE}${path}`, {
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
  return request<ParseResponse>("/api/thread/parse", {
    method: "POST",
    body: JSON.stringify({ input, timezone }),
  });
}

export function saveReminder(data: ReminderCreate): Promise<Reminder> {
  return request<Reminder>("/api/thread/reminders", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function listReminders(): Promise<Reminder[]> {
  return request<Reminder[]>("/api/thread/reminders");
}

export function patchReminder(id: string, status: "active" | "paused" | "done"): Promise<Reminder> {
  return request<Reminder>(`/api/thread/reminders/${id}`, {
    method: "PATCH",
    body: JSON.stringify({ status }),
  });
}

export function deleteReminder(id: string): Promise<void> {
  return request<void>(`/api/thread/reminders/${id}`, { method: "DELETE" });
}

export function listThreads(): Promise<Thread[]> {
  return request<Thread[]>("/api/thread/threads");
}

export function createThread(content: string, tags?: string[]): Promise<Thread> {
  return request<Thread>("/api/thread/threads", {
    method: "POST",
    body: JSON.stringify({ content, tags }),
  });
}

export function deleteThread(id: string): Promise<void> {
  return request<void>(`/api/thread/threads/${id}`, { method: "DELETE" });
}

export function snoozeThread(id: string, minutes = 30): Promise<{ ok: boolean; fire_at: string }> {
  return request(`/api/thread/threads/${id}/snooze`, {
    method: "POST",
    body: JSON.stringify({ minutes }),
  });
}

export function dismissThread(id: string): Promise<{ ok: boolean }> {
  return request(`/api/thread/threads/${id}/dismiss`, { method: "POST" });
}

/** Fetch threads whose trigger fires within the next 24 hours. */
export function listTodayTriggers(): Promise<Thread[]> {
  return listThreads().then((threads) => {
    const now = Date.now();
    const cutoff = now + 24 * 60 * 60 * 1000;
    return threads.filter((t) => {
      const fireAt = t.trigger?.fire_at;
      if (!fireAt) return false;
      const ts = new Date(fireAt).getTime();
      return ts >= now - 60 * 60 * 1000 && ts <= cutoff; // include up to 1h past
    });
  });
}
