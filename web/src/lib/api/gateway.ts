export type LoginPayload = {
  username: string;
  password: string;
};

export type Conversation = {
  id: number;
  contact_name: string;
  phone_number: string;
  updated_at: string;
  latest_message: string | null;
  latest_message_type: string | null;
  connection_id: number | null;
  unread_count: number;
};

export type WaConnection = {
  id: number;
  bridge_session_id: string;
  label: string | null;
  created_at: string;
  status: string;
  qr_code_data_url: string | null;
  connected_phone: string | null;
  connected_name: string | null;
  last_error: string | null;
};

export type Message = {
  id: number;
  conversation_id: number;
  direction: "inbound" | "outbound";
  message_type: string;
  body: string | null;
  media_url: string | null;
  transcript: string | null;
  delivery_status: string;
  created_at: string;
};


// Use relative path so requests go through the Vite proxy in dev and directly
// to the same-origin gateway in production.
const API_BASE = "/api";

function clearSessionAndRedirect() {
  localStorage.removeItem("alfred_token");
  localStorage.removeItem("alfred_user");
  localStorage.removeItem("ourcents_token");
  window.location.href = "/login";
}

async function apiRequest<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  if (!(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (token) {
    headers.set("Authorization", `Bearer ${token}`);
  }

  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (response.status === 401) {
    clearSessionAndRedirect();
    throw new Error("Session expired");
  }

  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(data.detail ?? "Request failed");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return response.json() as Promise<T>;
}

export async function login(payload: LoginPayload) {
  const body = new URLSearchParams();
  body.set("username", payload.username);
  body.set("password", payload.password);

  const response = await fetch(`${API_BASE}/auth/login`, {
    method: "POST",
    body,
    credentials: "include",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "Login failed" }));
    throw new Error(data.detail ?? "Login failed");
  }

  return response.json() as Promise<{ access_token: string; username: string }>;
}

export function fetchConversations(token: string) {
  return apiRequest<Conversation[]>("/conversations", undefined, token);
}

export function createConversation(
  token: string,
  payload: { phone_number: string; contact_name?: string | null }
) {
  return apiRequest<Conversation>(
    "/conversations",
    {
      method: "POST",
      body: JSON.stringify(payload),
    },
    token
  );
}

export function fetchMessages(token: string, conversationId: number) {
  return apiRequest<Message[]>(`/conversations/${conversationId}/messages`, undefined, token);
}

export function fetchConnections(token: string) {
  return apiRequest<WaConnection[]>("/connections", undefined, token);
}

export function createConnection(token: string, label?: string) {
  return apiRequest<WaConnection>(
    "/connections",
    { method: "POST", body: JSON.stringify({ label: label ?? null }) },
    token
  );
}

export function deleteConnection(token: string, connectionId: number) {
  return apiRequest<void>(`/connections/${connectionId}`, { method: "DELETE" }, token);
}

export function sendMessage(
  token: string,
  conversationId: number,
  body: string,
  options?: { sendAsVoice?: boolean }
) {
  return apiRequest<Message>(
    `/conversations/${conversationId}/messages`,
    {
      method: "POST",
      body: JSON.stringify({ message_type: "text", body, send_as_voice: options?.sendAsVoice ?? false }),
    },
    token
  );
}

export function sendImage(token: string, conversationId: number, file: File, caption?: string) {
  const formData = new FormData();
  formData.append("file", file);
  if (caption) formData.append("caption", caption);
  return apiRequest<Message>(
    `/conversations/${conversationId}/messages/media`,
    { method: "POST", body: formData },
    token
  );
}

export function clearConversation(token: string, conversationId: number) {
  return apiRequest<void>(
    `/conversations/${conversationId}/messages`,
    { method: "DELETE" },
    token
  );
}

export function deleteConversation(token: string, conversationId: number) {
  return apiRequest<void>(
    `/conversations/${conversationId}`,
    { method: "DELETE" },
    token
  );
}

export function deleteAllConversations(token: string) {
  return apiRequest<void>("/conversations", { method: "DELETE" }, token);
}

// ── Alfred Account API ─────────────────────────────────────────────────────────

export type AlfredUser = {
  id: string;
  phone: string;
  display_name: string | null;
  role: "admin" | "user";
  family_id: string | null;
  created_at: string;
  updated_at: string;
};

export type AlfredFamily = {
  id: string;
  name: string;
  created_by: string | null;
  created_at: string;
  updated_at: string;
};

export type AlfredFamilyDetail = AlfredFamily & { members: AlfredUser[] };

async function alfredRequest<T>(
  path: string,
  adminPhone: string,
  init?: RequestInit,
): Promise<T> {
  const headers = new Headers(init?.headers ?? {});
  headers.set("Content-Type", "application/json");
  headers.set("X-Alfred-Phone", adminPhone);

  const response = await fetch(`/api/alfred${path}`, {
    ...init,
    headers,
    credentials: "include",
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: { message: "Request failed" } }));
    const msg = data?.detail?.message ?? data?.detail ?? "Request failed";
    throw new Error(typeof msg === "string" ? msg : JSON.stringify(msg));
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export function alfredBootstrap(payload: {
  family_name: string;
  admin_phone: string;
  admin_display_name: string;
}) {
  return fetch("/api/alfred/bootstrap", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    credentials: "include",
  }).then(async (r) => {
    const data = await r.json();
    if (!r.ok) throw new Error(data?.detail?.message ?? data?.detail ?? "Bootstrap failed");
    return data as { success: boolean; user_id: string; family_id: string; message: string };
  });
}

export function alfredResolve(phone: string) {
  return fetch(`/api/alfred/resolve?phone=${encodeURIComponent(phone)}`, {
    credentials: "include",
  }).then(async (r) => {
    if (r.status === 404) return null;
    if (!r.ok) throw new Error("Resolve failed");
    return r.json() as Promise<AlfredUser & { user_id: string }>;
  });
}

export const alfredUsers = {
  list: (adminPhone: string) =>
    alfredRequest<AlfredUser[]>("/users", adminPhone),
  create: (adminPhone: string, payload: { phone: string; display_name?: string; family_id?: string }) =>
    alfredRequest<AlfredUser>("/users", adminPhone, { method: "POST", body: JSON.stringify(payload) }),
  update: (adminPhone: string, phone: string, payload: Partial<{ display_name: string; role: string; family_id: string | null }>) =>
    alfredRequest<AlfredUser>(`/users/${encodeURIComponent(phone)}`, adminPhone, { method: "PATCH", body: JSON.stringify(payload) }),
  delete: (adminPhone: string, phone: string) =>
    alfredRequest<void>(`/users/${encodeURIComponent(phone)}`, adminPhone, { method: "DELETE" }),
};

export const alfredFamilies = {
  list: (adminPhone: string) =>
    alfredRequest<AlfredFamily[]>("/families", adminPhone),
  create: (adminPhone: string, name: string) =>
    alfredRequest<AlfredFamily>("/families", adminPhone, { method: "POST", body: JSON.stringify({ name }) }),
  get: (adminPhone: string, id: string) =>
    alfredRequest<AlfredFamilyDetail>(`/families/${id}`, adminPhone),
  delete: (adminPhone: string, id: string) =>
    alfredRequest<void>(`/families/${id}`, adminPhone, { method: "DELETE" }),
};

export function clearAllData(adminPhone: string) {
  return alfredRequest<void>("/admin/clear-all-data", adminPhone, { method: "DELETE" });
}