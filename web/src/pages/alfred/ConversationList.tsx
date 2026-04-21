import { Conversation } from "../../lib/api/gateway";

type ConversationListProps = {
  conversations: Conversation[];
  activeConversationId: number | null;
  onSelect: (conversationId: number) => void;
  onCreateConversation: () => void;
  onDeleteConversation: (conversationId: number) => void;
  onDeleteAll: () => void;
};

function messagePreview(conv: Conversation): string {
  if (!conv.latest_message && !conv.latest_message_type) return "No messages yet";
  if (conv.latest_message_type === "image") return conv.latest_message ?? "📷 Image";
  if (conv.latest_message_type === "audio" || conv.latest_message_type === "ptt") return "🎵 Voice message";
  return conv.latest_message ?? "";
}

function formatTime(iso: string): string {
  const d = new Date(iso);
  const now = new Date();
  if (d.toDateString() === now.toDateString()) {
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }
  return d.toLocaleDateString([], { month: "short", day: "numeric" });
}

export function ConversationList({
  conversations,
  activeConversationId,
  onSelect,
  onCreateConversation,
  onDeleteConversation,
  onDeleteAll,
}: ConversationListProps) {
  return (
    <div style={{ display: "flex", flexDirection: "column", flex: 1, minHeight: 0 }}>
      <div style={{ padding: "10px 12px", borderBottom: "1px solid #e5e7eb", flexShrink: 0, display: "flex", justifyContent: "flex-end" }}>
        <button type="button" className="new-chat-button" onClick={onCreateConversation}>
          New Chat
        </button>
      </div>
      <div className="conversation-list" style={{ flex: 1, overflowY: "auto" }}>
        {conversations.map((conversation) => (
          <div
            key={conversation.id}
            style={{ position: "relative" }}
            className={conversation.id === activeConversationId ? "conversation-item active" : "conversation-item"}
          >
            <button
              type="button"
              style={{ width: "100%", background: "none", border: "none", padding: 0, textAlign: "left", cursor: "pointer" }}
              onClick={() => onSelect(conversation.id)}
            >
              <div className="conversation-topline">
                <strong className="conv-name">{conversation.contact_name}</strong>
                <span className="conv-time">{formatTime(conversation.updated_at)}</span>
              </div>
              <div className="conv-bottom">
                <p className="conv-preview" style={{ fontSize: 11, color: "#9ca3af", margin: "1px 0 0" }}>
                  {conversation.phone_number}
                </p>
              </div>
              <div className="conv-bottom">
                <p className="conv-preview">{messagePreview(conversation)}</p>
                {conversation.unread_count > 0 ? (
                  <span className="unread-badge">{conversation.unread_count > 99 ? "99+" : conversation.unread_count}</span>
                ) : null}
              </div>
            </button>
            {/* Per-conversation delete button */}
            <button
              type="button"
              onClick={(e) => { e.stopPropagation(); onDeleteConversation(conversation.id); }}
              title="Delete conversation"
              style={{
                position: "absolute",
                top: 8,
                right: 8,
                background: "none",
                border: "none",
                color: "#d1d5db",
                cursor: "pointer",
                fontSize: 13,
                lineHeight: 1,
                padding: "2px 4px",
                borderRadius: 4,
              }}
              onMouseEnter={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "#ef4444"; }}
              onMouseLeave={(e) => { (e.currentTarget as HTMLButtonElement).style.color = "#d1d5db"; }}
            >
              ✕
            </button>
          </div>
        ))}
      </div>
      {conversations.length > 0 && (
        <div style={{ padding: "10px 12px", borderTop: "1px solid #e5e7eb" }}>
          <button
            type="button"
            onClick={onDeleteAll}
            style={{
              width: "100%",
              background: "none",
              border: "1px solid #fca5a5",
              color: "#ef4444",
              borderRadius: 6,
              padding: "6px 0",
              fontSize: 12,
              cursor: "pointer",
            }}
          >
            Clear all conversations
          </button>
        </div>
      )}
    </div>
  );
}
