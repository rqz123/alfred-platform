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