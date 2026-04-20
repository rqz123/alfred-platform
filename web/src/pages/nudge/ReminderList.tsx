import { useState } from "react";
import type { Reminder } from "../../lib/types/nudge";
import { deleteReminder, patchReminder } from "../../lib/api/nudge";

// ── Shared helpers ──────────────────────────────────────────────────────────

const TZ = "America/Los_Angeles";

function formatTime(iso?: string | null): string {
  if (!iso) return "—";
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

const TYPE_LABEL: Record<string, string> = {
  once: "One-time",
  recurring: "Recurring",
  event: "Event",
};

const STATUS_COLOR: Record<string, string> = {
  active: "#16a34a",
  paused: "#d97706",
  awaiting: "#dc2626",
  done: "#6b7280",
  expired: "#9ca3af",
};

// ── Active / Paused row (with manage buttons) ───────────────────────────────

function ReminderRow({ reminder, onRefresh }: { reminder: Reminder; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);

  async function handleDelete() {
    if (!confirm(`Delete "${reminder.title}"?`)) return;
    setBusy(true);
    try {
      await deleteReminder(reminder.id);
      onRefresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setBusy(false);
    }
  }

  async function handleTogglePause() {
    const newStatus = reminder.status === "paused" ? "active" : "paused";
    setBusy(true);
    try {
      await patchReminder(reminder.id, newStatus);
      onRefresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to update");
    } finally {
      setBusy(false);
    }
  }

  const isPaused = reminder.status === "paused";

  return (
    <li style={styles.item}>
      <div style={styles.top}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          {reminder.shortName && (
            <span style={styles.petBadge} title={`Pet name: ${reminder.shortName}`}>
              🐾 {reminder.shortName}
            </span>
          )}
          <span style={styles.title}>{reminder.title}</span>
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6, flexShrink: 0 }}>
          <span style={{ ...styles.statusLabel, color: STATUS_COLOR[reminder.status] ?? "#6b7280" }}>
            {reminder.status}
          </span>
          <button
            onClick={handleTogglePause}
            disabled={busy}
            title={isPaused ? "Resume" : "Pause"}
            style={styles.actionBtn}
          >
            {isPaused ? "▶" : "⏸"}
          </button>
          <button
            onClick={handleDelete}
            disabled={busy}
            title="Delete"
            style={{ ...styles.actionBtn, color: "#ef4444" }}
          >
            ✕
          </button>
        </div>
      </div>

      <div style={styles.meta}>
        <span style={styles.typeBadge}>{TYPE_LABEL[reminder.type] ?? reminder.type}</span>
        <span style={styles.metaText}>
          {reminder.nextFireAt
            ? `Next: ${formatTime(reminder.nextFireAt)}`
            : reminder.fireAt
            ? formatTime(reminder.fireAt)
            : null}
        </span>
        {reminder.cronExpression && (
          <code style={styles.cron}>{reminder.cronExpression}</code>
        )}
      </div>

      {reminder.body && reminder.body !== reminder.title && (
        <p style={styles.body}>{reminder.body}</p>
      )}
    </li>
  );
}

// ── Fired row (read-only, shows what was sent) ──────────────────────────────

function FiredRow({ reminder }: { reminder: Reminder }) {
  const label = reminder.shortName ? `🐾 ${reminder.shortName} — ` : "";
  const msgText = `${label}${reminder.body || reminder.title}`;

  return (
    <li style={{ ...styles.item, background: "#f9fafb" }}>
      <div style={styles.top}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          {reminder.shortName && (
            <span style={styles.petBadge}>🐾 {reminder.shortName}</span>
          )}
          <span style={{ ...styles.title, color: "#374151" }}>{reminder.title}</span>
        </div>
        <span style={{ fontSize: 11, color: "#9ca3af", flexShrink: 0 }}>
          {formatTime(reminder.lastFiredAt)}
        </span>
      </div>
      <div style={{ fontSize: 12, color: "#9ca3af", marginTop: 2 }}>
        <span style={{ marginRight: 4 }}>📲</span>
        <code style={{ background: "#e5e7eb", padding: "1px 6px", borderRadius: 4, fontFamily: "monospace", fontSize: 11, color: "#374151" }}>
          {msgText}
        </code>
      </div>
    </li>
  );
}

// ── Awaiting-ack row (fired, needs user confirmation) ──────────────────────

function AwaitingRow({ reminder }: { reminder: Reminder }) {
  const MAX_RETRIES = 3;
  const ackCount = parseInt(reminder.ackRetries ?? "0", 10);
  const totalFires = MAX_RETRIES + 2;
  const fireNum = ackCount + 1; // 1 = initial fire, 2 = first re-fire, …
  const label = reminder.shortName ? `🐾 ${reminder.shortName}` : reminder.title;
  const nextRefire = reminder.nextFireAt;

  return (
    <li style={{ ...styles.item, border: "1.5px solid #fca5a5", background: "#fff5f5" }}>
      <div style={styles.top}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, minWidth: 0 }}>
          {reminder.shortName && (
            <span style={{ ...styles.petBadge, background: "#fee2e2", color: "#b91c1c" }}>
              🐾 {reminder.shortName}
            </span>
          )}
          <span style={{ ...styles.title }}>{reminder.title}</span>
        </div>
        <span style={{ fontSize: 11, fontWeight: 600, color: "#dc2626", flexShrink: 0 }}>
          ● awaiting ({fireNum}/{totalFires})
        </span>
      </div>
      <div style={styles.meta}>
        <span style={styles.typeBadge}>{TYPE_LABEL[reminder.type] ?? reminder.type}</span>
        <span style={{ fontSize: 12, color: "#6b7280" }}>
          First fired: {formatTime(reminder.firstFiredAt)}
        </span>
        {nextRefire && (
          <span style={{ fontSize: 12, color: "#ef4444" }}>
            Re-fire at: {formatTime(nextRefire)}
          </span>
        )}
      </div>
      <p style={{ fontSize: 12, color: "#b91c1c", margin: 0 }}>
        Reply "OK" on WhatsApp to confirm {label}.
      </p>
    </li>
  );
}

// ── Section wrapper ─────────────────────────────────────────────────────────

interface SectionProps {
  title: string;
  reminders: Reminder[];
  onRefresh?: () => void;
  variant: "active" | "awaiting" | "fired";
  emptyText?: string;
}

export function ReminderSection({ title, reminders, onRefresh, variant, emptyText }: SectionProps) {
  return (
    <div style={{ marginBottom: "1.75rem" }}>
      <h3 style={{ margin: "0 0 0.6rem", fontSize: 14, fontWeight: 600, color: "#374151", textTransform: "uppercase", letterSpacing: "0.05em" }}>
        {title}
        <span style={{ marginLeft: 8, fontWeight: 400, color: "#9ca3af", fontSize: 12, textTransform: "none", letterSpacing: 0 }}>
          ({reminders.length})
        </span>
      </h3>
      {reminders.length === 0 ? (
        <p style={{ color: "#9ca3af", fontSize: 13, margin: 0 }}>{emptyText ?? "None"}</p>
      ) : (
        <ul style={styles.list}>
          {reminders.map((r) =>
            variant === "active" ? (
              <ReminderRow key={r.id} reminder={r} onRefresh={onRefresh!} />
            ) : variant === "awaiting" ? (
              <AwaitingRow key={r.id} reminder={r} />
            ) : (
              <FiredRow key={r.id} reminder={r} />
            )
          )}
        </ul>
      )}
    </div>
  );
}

// ── Styles ──────────────────────────────────────────────────────────────────

const styles: Record<string, React.CSSProperties> = {
  list: {
    listStyle: "none",
    margin: 0,
    padding: 0,
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  item: {
    border: "1px solid #e5e7eb",
    borderRadius: 8,
    padding: "10px 14px",
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  top: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    gap: 8,
  },
  petBadge: {
    fontSize: 11,
    fontWeight: 600,
    color: "#92400e",
    background: "#fef3c7",
    padding: "2px 8px",
    borderRadius: 99,
    flexShrink: 0,
    whiteSpace: "nowrap" as const,
  },
  title: {
    fontWeight: 600,
    fontSize: 14,
    color: "#111827",
    overflow: "hidden",
    textOverflow: "ellipsis",
    whiteSpace: "nowrap",
  },
  statusLabel: {
    fontSize: 11,
    fontWeight: 500,
  },
  actionBtn: {
    background: "none",
    border: "1px solid #e5e7eb",
    borderRadius: 4,
    cursor: "pointer",
    fontSize: 12,
    padding: "2px 7px",
    color: "#374151",
    lineHeight: 1.4,
  },
  meta: {
    display: "flex",
    alignItems: "center",
    gap: 8,
    flexWrap: "wrap",
  },
  typeBadge: {
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 7px",
    borderRadius: 99,
    color: "#374151",
  },
  metaText: {
    fontSize: 12,
    color: "#6b7280",
  },
  cron: {
    fontSize: 11,
    background: "#f3f4f6",
    padding: "1px 5px",
    borderRadius: 4,
    fontFamily: "monospace",
    color: "#374151",
  },
  body: {
    fontSize: 13,
    color: "#6b7280",
    margin: 0,
  },
};
