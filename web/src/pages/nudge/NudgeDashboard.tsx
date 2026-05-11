import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listReminders, listThreads, deleteReminder } from "../../lib/api/nudge";
import { listPhoneBindings } from "../../lib/api/ourcents";
import { ReminderSection } from "./ReminderList";
import { ThreadList } from "./ThreadList";
import { TodayTriggers } from "./TodayTriggers";
import type { Reminder, Thread } from "../../lib/types/nudge";

type Period = "7d" | "30d" | "all";

function withinPeriod(iso: string | null | undefined, period: Period): boolean {
  if (period === "all") return true;
  if (!iso) return false;
  const days = period === "7d" ? 7 : 30;
  return Date.now() - new Date(iso).getTime() < days * 86400_000;
}



type Tab = "today" | "reminders" | "threads";

export default function NudgeDashboard() {
  const [tab, setTab] = useState<Tab>("today");
  const [period, setPeriod] = useState<Period>("7d");
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [threads, setThreads] = useState<Thread[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasPhone, setHasPhone] = useState<boolean | null>(null);
  const navigate = useNavigate();

  function loadReminders() {
    listReminders().then(setReminders).catch(() => {});
  }

  function loadThreads() {
    listThreads().then(setThreads).catch(() => {});
  }

  useEffect(() => {
    Promise.all([listReminders(), listThreads()])
      .then(([r, n]) => { setReminders(r); setThreads(n); })
      .catch(() => {})
      .finally(() => setLoading(false));
    listPhoneBindings()
      .then((b) => setHasPhone(b.length > 0))
      .catch(() => setHasPhone(null));
  }, []);

  // Reminder sections
  const awaitingReminders = reminders
    .filter((r) => r.status === "awaiting")
    .sort((a, b) => {
      const at = a.firstFiredAt ? new Date(a.firstFiredAt).getTime() : 0;
      const bt = b.firstFiredAt ? new Date(b.firstFiredAt).getTime() : 0;
      return at - bt; // oldest first (most urgent)
    });
  const activeReminders = reminders.filter(
    (r) => r.status === "active" || r.status === "paused"
  );
  const confirmedReminders = reminders
    .filter((r) => r.status === "done" && withinPeriod(r.lastFiredAt ?? r.updatedAt, period))
    .sort((a, b) => new Date(b.lastFiredAt ?? b.updatedAt).getTime() - new Date(a.lastFiredAt ?? a.updatedAt).getTime());
  const expiredReminders = reminders
    .filter((r) => r.status === "expired" && withinPeriod(r.updatedAt, period))
    .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());

  async function clearAll(ids: string[]) {
    await Promise.all(ids.map((id) => deleteReminder(id).catch(() => {})));
    loadReminders();
  }

  const activeThreads = threads.filter((n) => n.status === "active");

  // Today's triggers: threads with fire_at in the next 24h (or up to 1h past)
  const now = Date.now();
  const cutoff = now + 24 * 60 * 60 * 1000;
  const todayTriggers = threads.filter((t) => {
    const fireAt = t.trigger?.fire_at;
    if (!fireAt || t.trigger?.type === "none") return false;
    const ts = new Date(fireAt).getTime();
    return ts >= now - 60 * 60 * 1000 && ts <= cutoff;
  }).sort((a, b) => {
    const at = a.trigger?.fire_at ? new Date(a.trigger.fire_at).getTime() : 0;
    const bt = b.trigger?.fire_at ? new Date(b.trigger.fire_at).getTime() : 0;
    return at - bt;
  });

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ maxWidth: 700 }}>
        <div style={{ marginBottom: "1.25rem" }}>
          <h2 style={{ margin: 0 }}>Nudge</h2>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>Reminders & threads</p>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 4, marginBottom: "1.5rem", borderBottom: "1px solid #e5e7eb", paddingBottom: 0 }}>
          {(["today", "reminders", "threads"] as Tab[]).map((t) => (
            <button
              key={t}
              onClick={() => setTab(t)}
              style={{
                background: "none",
                border: "none",
                borderBottom: tab === t ? "2px solid #6366f1" : "2px solid transparent",
                padding: "6px 16px",
                fontSize: 14,
                fontWeight: tab === t ? 600 : 400,
                color: tab === t ? "#6366f1" : "#6b7280",
                cursor: "pointer",
                marginBottom: -1,
                borderRadius: 0,
                textTransform: "capitalize",
              }}
            >
              {t === "today"
                ? `Today${todayTriggers.length ? ` (${todayTriggers.length})` : ""}`
                : t === "reminders"
                ? `Reminders${activeReminders.length ? ` (${activeReminders.length})` : ""}`
                : `Threads${activeThreads.length ? ` (${activeThreads.length})` : ""}`}
            </button>
          ))}
        </div>

        {hasPhone === false && tab === "reminders" && (
          <div style={{
            background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 8,
            padding: "10px 14px", fontSize: 13, color: "#92400e", marginBottom: "1.5rem",
            display: "flex", justifyContent: "space-between", alignItems: "center",
          }}>
            <span>⚠ No phone number linked — reminders will fire but alerts won't be sent.</span>
            <button
              onClick={() => navigate("/settings")}
              style={{ marginLeft: 12, padding: "3px 10px", fontSize: 12, borderRadius: 4, border: "1px solid #f59e0b", background: "#fef3c7", cursor: "pointer", color: "#92400e" }}
            >
              Go to Settings
            </button>
          </div>
        )}

        {loading ? (
          <p style={{ color: "#9ca3af", fontSize: 14 }}>Loading…</p>
        ) : tab === "today" ? (
          <TodayTriggers threads={todayTriggers} onRefresh={loadThreads} />
        ) : tab === "reminders" ? (
          <>
            <ReminderSection
              title="Awaiting Confirmation"
              reminders={awaitingReminders}
              variant="awaiting"
              emptyText="No reminders awaiting confirmation."
            />
            <ReminderSection
              title="Active"
              reminders={activeReminders}
              onRefresh={loadReminders}
              variant="active"
              emptyText="No active reminders."
            />
            {/* Period filter — shared for Confirmed + Expired */}
            <div style={{ display: "flex", alignItems: "center", gap: 6, marginBottom: "1rem" }}>
              <span style={{ fontSize: 12, color: "#9ca3af" }}>Show:</span>
              {(["7d", "30d", "all"] as Period[]).map((p) => (
                <button
                  key={p}
                  onClick={() => setPeriod(p)}
                  style={{
                    fontSize: 12,
                    padding: "2px 10px",
                    borderRadius: 99,
                    border: "1px solid",
                    borderColor: period === p ? "#6366f1" : "#e5e7eb",
                    background: period === p ? "#6366f1" : "none",
                    color: period === p ? "#fff" : "#6b7280",
                    cursor: "pointer",
                  }}
                >
                  {p === "7d" ? "7 days" : p === "30d" ? "30 days" : "All"}
                </button>
              ))}
            </div>

            <ReminderSection
              title="Confirmed"
              reminders={confirmedReminders}
              variant="fired"
              emptyText="No confirmed reminders in this period."
              onClearAll={() => clearAll(confirmedReminders.map((r) => r.id))}
            />
            <ReminderSection
              title="Expired"
              reminders={expiredReminders}
              variant="fired"
              emptyText="No expired reminders in this period."
              onClearAll={() => clearAll(expiredReminders.map((r) => r.id))}
            />
          </>
        ) : (
          <ThreadList threads={activeThreads} onRefresh={loadThreads} />
        )}
      </div>
    </div>
  );
}
