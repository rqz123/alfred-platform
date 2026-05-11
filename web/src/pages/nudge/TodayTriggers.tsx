import { useState } from "react";
import type { Thread, AckStatus } from "../../lib/types/nudge";
import { snoozeThread, dismissThread } from "../../lib/api/nudge";

const TZ = "America/Los_Angeles";

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

function TriggerCard({ thread, onRefresh }: { thread: Thread; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);
  const trigger = thread.trigger!;
  const badge = ACK_BADGE[trigger.ack_status] ?? ACK_BADGE.pending;
  const icon = TRIGGER_ICON[trigger.type] ?? "🔔";

  const isOverdue =
    trigger.fire_at &&
    new Date(trigger.fire_at).getTime() < Date.now() &&
    trigger.ack_status === "pending";

  const canAct = trigger.ack_status === "pending" || trigger.ack_status === "awaiting";

  async function handleSnooze() {
    setBusy(true);
    try { await snoozeThread(thread.id, 30); onRefresh(); }
    catch (e) { alert(e instanceof Error ? e.message : "Snooze failed"); }
    finally { setBusy(false); }
  }

  async function handleDismiss() {
    setBusy(true);
    try { await dismissThread(thread.id); onRefresh(); }
    catch (e) { alert(e instanceof Error ? e.message : "Dismiss failed"); }
    finally { setBusy(false); }
  }

  return (
    <div style={{
      border: `1px solid ${isOverdue ? "#fca5a5" : "#e5e7eb"}`,
      borderRadius: 10,
      padding: "12px 16px",
      background: isOverdue ? "#fff7f7" : "#fff",
      display: "flex",
      flexDirection: "column",
      gap: 8,
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <span style={{ fontSize: 16 }}>{icon}</span>
          {thread.shortId != null && (
            <span style={{
              fontSize: 11, fontWeight: 600, color: "#6366f1",
              background: "#eef2ff", padding: "1px 7px", borderRadius: 99,
            }}>
              #{thread.shortId}
            </span>
          )}
          {thread.title && (
            <span style={{ fontSize: 13, fontWeight: 600, color: "#111827" }}>
              {thread.title}
            </span>
          )}
        </div>
        <span style={{
          fontSize: 11, fontWeight: 500, padding: "2px 9px", borderRadius: 99,
          background: badge.bg, color: badge.color, whiteSpace: "nowrap",
        }}>
          {badge.label}
        </span>
      </div>

      <p style={{ margin: 0, fontSize: 14, color: "#374151", lineHeight: 1.55 }}>
        {thread.content}
      </p>

      {trigger.fire_at && (
        <div style={{ fontSize: 12, color: isOverdue ? "#dc2626" : "#6b7280" }}>
          {isOverdue ? "⚠ Overdue · " : ""}
          {formatFireAt(trigger.fire_at)}
          {trigger.type === "recurring" && trigger.cron && (
            <span style={{ marginLeft: 6, color: "#9ca3af" }}>· recurring</span>
          )}
        </div>
      )}

      {canAct && (
        <div style={{ display: "flex", gap: 6, marginTop: 2 }}>
          <button
            onClick={handleSnooze}
            disabled={busy}
            style={{
              fontSize: 12, padding: "3px 10px", borderRadius: 6,
              border: "1px solid #e5e7eb", background: "#f9fafb",
              color: "#6b7280", cursor: "pointer",
            }}
          >
            Snooze 30m
          </button>
          <button
            onClick={handleDismiss}
            disabled={busy}
            style={{
              fontSize: 12, padding: "3px 10px", borderRadius: 6,
              border: "1px solid #fca5a5", background: "#fff7f7",
              color: "#dc2626", cursor: "pointer",
            }}
          >
            Dismiss
          </button>
        </div>
      )}
    </div>
  );
}

interface Props {
  threads: Thread[];
  onRefresh: () => void;
}

export function TodayTriggers({ threads, onRefresh }: Props) {
  if (threads.length === 0) {
    return (
      <div style={{ color: "#6b7280", fontSize: 14, padding: "24px 0" }}>
        <p style={{ margin: 0 }}>No upcoming reminders in the next 24 hours.</p>
        <p style={{ margin: "6px 0 0", fontSize: 12, color: "#9ca3af" }}>
          Say "remind me tomorrow at 9am" via WhatsApp to add one.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
      {threads.map((t) => (
        <TriggerCard key={t.id} thread={t} onRefresh={onRefresh} />
      ))}
    </div>
  );
}
