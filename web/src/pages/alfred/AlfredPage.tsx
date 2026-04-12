/**
 * Alfred WhatsApp page — contains all state logic originally in App.tsx.
 * Assumes the user is already authenticated (handled by AuthGuard + router).
 */

import { useEffect, useState } from "react";

import { Composer } from "./Composer";
import { ConnectionPanel } from "./ConnectionPanel";
import { ConversationList } from "./ConversationList";
import { MessageList } from "./MessageList";
import {
  WaConnection,
  Conversation,
  Message,
  clearConversation,
  createConnection,
  createConversation,
  deleteConnection,
  fetchConnections,
  fetchConversations,
  fetchMessages,
  sendImage,
  sendMessage,
} from "../../lib/api/gateway";

export default function AlfredPage() {
  const token = localStorage.getItem("alfred_token") ?? "";
  const username = (() => {
    try {
      const raw = localStorage.getItem("alfred_user");
      return raw ? (JSON.parse(raw) as { username: string }).username : "";
    } catch { return ""; }
  })();

  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [activeConversationId, setActiveConversationId] = useState<number | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [connections, setConnections] = useState<WaConnection[]>([]);
  const [chatError, setChatError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) return;
    void loadConversations(token);
    void loadConnections(token);

    const intervalId = window.setInterval(() => {
      void loadConnections(token);
      if (activeConversationId !== null) void loadMessages(token, activeConversationId);
      void loadConversations(token);
    }, 5000);

    return () => window.clearInterval(intervalId);
  }, [token, activeConversationId]);

  useEffect(() => {
    if (!token || activeConversationId === null) return;
    void loadMessages(token, activeConversationId);
  }, [token, activeConversationId]);

  async function loadConversations(t: string) {
    try {
      const items = await fetchConversations(t);
      setConversations(items);
      setActiveConversationId((cur) => cur ?? items[0]?.id ?? null);
      setChatError(null);
    } catch (e) { setChatError(e instanceof Error ? e.message : "Failed to load"); }
  }

  async function loadMessages(t: string, id: number) {
    try {
      const items = await fetchMessages(t, id);
      setMessages(items);
      setChatError(null);
    } catch (e) { setChatError(e instanceof Error ? e.message : "Failed to load messages"); }
  }

  async function loadConnections(t: string) {
    try { setConnections(await fetchConnections(t)); } catch { /* swallow */ }
  }

  async function handleSend(body: string, options: { sendAsVoice: boolean }) {
    if (!token || activeConversationId === null) return;
    const msg = await sendMessage(token, activeConversationId, body, options);
    setMessages((cur) => [...cur, msg]);
    await loadConversations(token);
  }

  async function handleSendImage(file: File) {
    if (!token || activeConversationId === null) return;
    const msg = await sendImage(token, activeConversationId, file);
    setMessages((cur) => [...cur, msg]);
    await loadConversations(token);
  }

  async function handleClear() {
    if (!token || activeConversationId === null) return;
    await clearConversation(token, activeConversationId);
    setMessages([]);
    await loadConversations(token);
  }

  async function handleCreateConnection() {
    if (!token) return;
    const label = window.prompt("Optional label (e.g. \"My iPhone\")") ?? undefined;
    try { await createConnection(token, label); await loadConnections(token); }
    catch (e) { setChatError(e instanceof Error ? e.message : "Failed"); }
  }

  async function handleDeleteConnection(id: number) {
    if (!token) return;
    try { await deleteConnection(token, id); await loadConnections(token); }
    catch (e) { setChatError(e instanceof Error ? e.message : "Failed"); }
  }

  async function handleCreateConversation() {
    if (!token) return;
    const phone = window.prompt("Phone number (with country code):");
    if (!phone) return;
    const name = window.prompt("Contact name (optional)") || undefined;
    const msg = window.prompt("Initial message (optional)") || undefined;
    try {
      const convo = await createConversation(token, { phone_number: phone, contact_name: name });
      setActiveConversationId(convo.id);
      setChatError(null);
      if (msg) { const m = await sendMessage(token, convo.id, msg); setMessages([m]); }
      await loadConversations(token);
    } catch (e) { setChatError(e instanceof Error ? e.message : "Failed"); }
  }

  return (
    <main className="app-shell">
      <ConversationList
        conversations={conversations}
        activeConversationId={activeConversationId}
        onSelect={setActiveConversationId}
        onCreateConversation={handleCreateConversation}
      />
      <section className="chat-panel">
        <header className="chat-header">
          <div>
            <p className="eyebrow">Signed in as</p>
            <h1>{username}</h1>
          </div>
        </header>
        <ConnectionPanel
          connections={connections}
          onCreateConnection={handleCreateConnection}
          onDeleteConnection={handleDeleteConnection}
        />
        {chatError ? <p className="error-banner">{chatError}</p> : null}
        <MessageList messages={messages} />
        <Composer
          disabled={activeConversationId === null}
          onSend={handleSend}
          onSendImage={handleSendImage}
          onClear={handleClear}
        />
      </section>
    </main>
  );
}
