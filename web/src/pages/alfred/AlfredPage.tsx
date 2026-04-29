/**
 * Alfred WhatsApp page — contains all state logic originally in App.tsx.
 * Assumes the user is already authenticated (handled by AuthGuard + router).
 */

import { useEffect, useState } from "react";

import { Composer } from "./Composer";
import { ConversationList } from "./ConversationList";
import { MessageList } from "./MessageList";
import {
  WaConnection,
  Conversation,
  Message,
  clearConversation,
  createConversation,
  deleteConversation,
  deleteAllConversations,
  fetchConnections,
  fetchConversations,
  fetchMessages,
  sendImage,
  sendMessage,
} from "../../lib/api/gateway";

export default function AlfredPage() {
  const token = localStorage.getItem("alfred_token") ?? "";

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

  async function handleDeleteConversation(id: number) {
    if (!token) return;
    if (!confirm("Delete this conversation and all its messages?")) return;
    await deleteConversation(token, id);
    if (activeConversationId === id) {
      setActiveConversationId(null);
      setMessages([]);
    }
    await loadConversations(token);
  }

  async function handleDeleteAll() {
    if (!token) return;
    if (!confirm("Delete ALL conversations? This cannot be undone.")) return;
    await deleteAllConversations(token);
    setActiveConversationId(null);
    setMessages([]);
    setConversations([]);
  }

  async function handleCreateConversation() {
    if (!token) return;
    const phone = window.prompt("Phone number (with country code):");
    if (!phone) return;
    const name = window.prompt("Contact name (optional)") || undefined;
    try {
      const convo = await createConversation(token, { phone_number: phone, contact_name: name });
      setActiveConversationId(convo.id);
      setChatError(null);
      await loadConversations(token);
    } catch (e) { setChatError(e instanceof Error ? e.message : "Failed"); }
  }

  const activeConv = conversations.find((c) => c.id === activeConversationId) ?? null;
  const connectedConn = connections.find((c) => c.status === "connected") ?? null;

  return (
    <main className="app-shell">
      {/* ── Left sidebar: conversation list ── */}
      <aside className="sidebar">
        <ConversationList
          conversations={conversations}
          activeConversationId={activeConversationId}
          onSelect={(id) => { setActiveConversationId(id); }}
          onCreateConversation={handleCreateConversation}
          onDeleteConversation={handleDeleteConversation}
          onDeleteAll={handleDeleteAll}
        />
      </aside>

      {/* ── Right panel: chat ── */}
      <section className="chat-panel">
        <header className="chat-header">
          <div>
            {activeConv ? (
              <>
                <p className="eyebrow">{activeConv.phone_number}</p>
                <h1>{activeConv.contact_name}</h1>
              </>
            ) : connectedConn ? (
              <>
                <p className="eyebrow">Connected</p>
                <h1>{connectedConn.connected_name ?? "Alfred"}</h1>
              </>
            ) : (
              <>
                <p className="eyebrow">WhatsApp</p>
                <h1>No conversation selected</h1>
              </>
            )}
          </div>
        </header>
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
