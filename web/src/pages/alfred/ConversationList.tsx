import { Conversation } from "../../lib/api/gateway";

type ConversationListProps = {
  conversations: Conversation[];
  activeConversationId: number | null;
  onSelect: (conversationId: number) => void;
  onCreateConversation: () => void;
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
}: ConversationListProps) {
  return (
    <aside className="sidebar">
      <div className="sidebar-header">
        <div>
          <p className="eyebrow">Inbox</p>
          <h2>Conversations</h2>
        </div>
        <button type="button" className="new-chat-button" onClick={onCreateConversation}>
          New Chat
        </button>
      </div>
      <div className="conversation-list">
        {conversations.map((conversation) => (
          <button
            key={conversation.id}
            className={conversation.id === activeConversationId ? "conversation-item active" : "conversation-item"}
            onClick={() => onSelect(conversation.id)}
            type="button"
          >
            <div className="conversation-topline">
              <strong className="conv-name">{conversation.contact_name}</strong>
              <span className="conv-time">{formatTime(conversation.updated_at)}</span>
            </div>
            <div className="conv-bottom">
              <p className="conv-preview">{messagePreview(conversation)}</p>
              {conversation.unread_count > 0 ? (
                <span className="unread-badge">{conversation.unread_count > 99 ? "99+" : conversation.unread_count}</span>
              ) : null}
            </div>
          </button>
        ))}
      </div>
    </aside>
  );
}
