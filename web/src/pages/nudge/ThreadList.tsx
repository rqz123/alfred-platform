import { useState, useMemo } from "react";
import type { Thread, AckStatus } from "../../lib/types/nudge";
import { deleteThread } from "../../lib/api/nudge";

const TZ = "America/Los_Angeles";

function formatThreadDate(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "numeric",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: TZ,
      timeZoneName: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function formatFireAt(iso: string): string {
  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
      timeZone: TZ,
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

const ACK_BADGE: Record<AckStatus, { label: string; bg: string; color: string }> = {
  pending:      { label: "Pending",      bg: "#eff6ff", color: "#3b82f6" },
  firing:       { label: "Firing…",      bg: "#fef3c7", color: "#d97706" },
  awaiting:     { label: "Awaiting ack", bg: "#fefce8", color: "#ca8a04" },
  acknowledged: { label: "Done",         bg: "#f0fdf4", color: "#16a34a" },
  snoozed:      { label: "Snoozed",      bg: "#faf5ff", color: "#9333ea" },
  dismissed:    { label: "Dismissed",    bg: "#f9fafb", color: "#6b7280" },
  expired:      { label: "Expired",      bg: "#fef2f2", color: "#dc2626" },
};

const TRIGGER_ICON: Record<string, string> = {
  once:      "🕐",
  recurring: "🔁",
  geofence:  "📍",
};

function ThreadRow({ thread, onRefresh }: { thread: Thread; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);

  async function handleDelete() {
    if (!confirm("Delete this thread?")) return;
    setBusy(true);
    try {
      await deleteThread(thread.id);
      onRefresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setBusy(false);
    }
  }

  const allEntities = [
    ...(thread.entities?.people ?? []),
    ...(thread.entities?.places ?? []),
    ...(thread.entities?.orgs ?? []),
  ];

  const trigger = thread.trigger;
  const hasTrigger = trigger && trigger.type !== "none";
  const triggerIcon = hasTrigger ? (TRIGGER_ICON[trigger.type] ?? "🔔") : null;
  const ackBadge = hasTrigger ? (ACK_BADGE[trigger.ack_status] ?? ACK_BADGE.pending) : null;

  return (
    <li style={styles.item}>
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          {triggerIcon && (
            <span style={{ fontSize: 14 }}>{triggerIcon}</span>
          )}
          {thread.shortId != null && (
            <span style={styles.shortId}>#{thread.shortId}</span>
          )}
          {thread.title && (
            <span style={styles.title}>{thread.title}</span>
          )}
        </div>
        <div style={styles.headerRight}>
          {ackBadge && (
            <span style={{
              fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 99,
              background: ackBadge.bg, color: ackBadge.color, whiteSpace: "nowrap",
            }}>
              {ackBadge.label}
            </span>
          )}
          <span style={styles.date}>{formatThreadDate(thread.createdAt)}</span>
          <button
            onClick={handleDelete}
            disabled={busy}
            title="Delete"
            style={styles.deleteBtn}
          >
            ✕
          </button>
        </div>
      </div>

      <p style={styles.content}>{thread.content}</p>

      {hasTrigger && trigger?.fire_at && (
        <div style={{ fontSize: 12, color: "#6b7280" }}>
          {triggerIcon} {formatFireAt(trigger.fire_at)}
          {trigger.type === "recurring" && trigger.cron && (
            <span style={{ marginLeft: 6, color: "#9ca3af" }}>· recurring</span>
          )}
        </div>
      )}

      {allEntities.length > 0 && (
        <div style={styles.pills}>
          {allEntities.map((e, i) => (
            <span key={i} style={styles.entityPill}>{e}</span>
          ))}
        </div>
      )}

      {thread.relatedIds && thread.relatedIds.length > 0 && (
        <div style={styles.related}>
          <span style={styles.relatedLabel}>Related:</span>
          {thread.relatedIds.map((id) => (
            <span key={id} style={styles.relatedBadge}>#{id}</span>
          ))}
        </div>
      )}

      {thread.tags && thread.tags.length > 0 && (
        <div style={styles.tags}>
          {thread.tags.map((t) => (
            <span key={t} style={styles.tag}>{t}</span>
          ))}
        </div>
      )}
    </li>
  );
}

interface Props {
  threads: Thread[];
  onRefresh: () => void;
}

export function ThreadList({ threads, onRefresh }: Props) {
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return threads;
    return threads.filter(
      (n) =>
        n.content.toLowerCase().includes(q) ||
        (n.title ?? "").toLowerCase().includes(q) ||
        (n.entities?.people ?? []).some((e) => e.toLowerCase().includes(q)) ||
        (n.entities?.places ?? []).some((e) => e.toLowerCase().includes(q)) ||
        (n.entities?.orgs ?? []).some((e) => e.toLowerCase().includes(q))
    );
  }, [threads, search]);

  if (threads.length === 0) {
    return (
      <div style={styles.empty}>
        <p style={{ margin: 0 }}>No threads yet.</p>
        <p style={{ margin: "6px 0 0", fontSize: 12, color: "#9ca3af" }}>
          Send Alfred a WhatsApp message like "thread: bought blood pressure pills"
          to save a thread.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div style={styles.searchBar}>
        <input
          type="text"
          placeholder="Search threads…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={styles.searchInput}
        />
        {search && (
          <button onClick={() => setSearch("")} style={styles.clearBtn}>
            ✕
          </button>
        )}
      </div>

      {filtered.length === 0 ? (
        <div style={styles.empty}>
          <p style={{ margin: 0, color: "#6b7280" }}>
            No threads match &ldquo;{search}&rdquo;
          </p>
        </div>
      ) : (
        <ul style={styles.list}>
          {filtered.map((n) => (
            <ThreadRow key={n.id} thread={n} onRefresh={onRefresh} />
          ))}
        </ul>
      )}
    </div>
  );
}

const styles: Record<string, React.CSSProperties> = {
  searchBar: {
    display: "flex",
    alignItems: "center",
    marginBottom: 12,
    gap: 6,
  },
  searchInput: {
    flex: 1,
    border: "1px solid #e5e7eb",
    borderRadius: 6,
    padding: "6px 10px",
    fontSize: 13,
    outline: "none",
    fontFamily: "inherit",
  },
  clearBtn: {
    background: "none",
    border: "none",
    cursor: "pointer",
    color: "#9ca3af",
    fontSize: 14,
    padding: "0 4px",
  },
  list: {
    listStyle: "none",
    margin: 0,
    padding: 0,
    display: "flex",
    flexDirection: "column",
    gap: 10,
  },
  item: {
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: "10px 14px",
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 6,
  },
  header: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "flex-start",
    gap: 8,
  },
  headerLeft: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flex: 1,
    minWidth: 0,
    flexWrap: "wrap",
  },
  headerRight: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexShrink: 0,
  },
  shortId: {
    fontSize: 12,
    fontWeight: 600,
    color: "#6366f1",
    background: "#eef2ff",
    padding: "1px 7px",
    borderRadius: 99,
    whiteSpace: "nowrap",
  },
  title: {
    fontSize: 13,
    fontWeight: 600,
    color: "#111827",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  date: {
    fontSize: 11,
    color: "#9ca3af",
    whiteSpace: "nowrap",
  },
  deleteBtn: {
    background: "none",
    border: "1px solid #e5e7eb",
    borderRadius: 4,
    cursor: "pointer",
    fontSize: 11,
    padding: "1px 6px",
    color: "#ef4444",
    lineHeight: 1.4,
  },
  content: {
    margin: 0,
    fontSize: 14,
    color: "#111827",
    lineHeight: 1.6,
    whiteSpace: "pre-wrap",
  },
  pills: {
    display: "flex",
    gap: 5,
    flexWrap: "wrap",
  },
  entityPill: {
    fontSize: 11,
    background: "#fef9c3",
    color: "#854d0e",
    padding: "1px 8px",
    borderRadius: 99,
    border: "1px solid #fde68a",
  },
  related: {
    display: "flex",
    alignItems: "center",
    gap: 5,
    flexWrap: "wrap",
  },
  relatedLabel: {
    fontSize: 11,
    color: "#9ca3af",
  },
  relatedBadge: {
    fontSize: 11,
    background: "#f0fdf4",
    color: "#166534",
    padding: "1px 7px",
    borderRadius: 99,
    border: "1px solid #bbf7d0",
  },
  tags: {
    display: "flex",
    gap: 6,
    flexWrap: "wrap",
  },
  tag: {
    fontSize: 11,
    background: "#eff6ff",
    color: "#3b82f6",
    padding: "1px 8px",
    borderRadius: 99,
  },
  empty: {
    color: "#6b7280",
    fontSize: 14,
    padding: "24px 0",
  },
};
