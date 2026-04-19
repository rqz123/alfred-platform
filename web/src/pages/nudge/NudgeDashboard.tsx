import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listReminders, listNotes } from "../../lib/api/nudge";
import { listPhoneBindings } from "../../lib/api/ourcents";
import { ReminderSection } from "./ReminderList";
import { NoteList } from "./NoteList";
import type { Reminder, Note } from "../../lib/types/nudge";

const TZ = "America/Los_Angeles";

function todayStrPDT(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: TZ });
}

function firedTodayPDT(r: Reminder): boolean {
  if (!r.lastFiredAt) return false;
  return new Date(r.lastFiredAt).toLocaleDateString("en-CA", { timeZone: TZ }) === todayStrPDT();
}

type Tab = "reminders" | "notes";

export default function NudgeDashboard() {
  const [tab, setTab] = useState<Tab>("reminders");
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [notes, setNotes] = useState<Note[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasPhone, setHasPhone] = useState<boolean | null>(null);
  const navigate = useNavigate();

  function loadReminders() {
    listReminders().then(setReminders).catch(() => {});
  }

  function loadNotes() {
    listNotes().then(setNotes).catch(() => {});
  }

  useEffect(() => {
    Promise.all([listReminders(), listNotes()])
      .then(([r, n]) => { setReminders(r); setNotes(n); })
      .catch(() => {})
      .finally(() => setLoading(false));
    listPhoneBindings()
      .then((b) => setHasPhone(b.length > 0))
      .catch(() => setHasPhone(null));
  }, []);

  // Reminder sections
  const activeReminders = reminders.filter(
    (r) => r.status === "active" || r.status === "paused"
  );
  const firedToday = reminders
    .filter((r) => (r.status === "done" || r.status === "expired") && firedTodayPDT(r))
    .sort((a, b) => new Date(b.lastFiredAt!).getTime() - new Date(a.lastFiredAt!).getTime());
  const past = reminders
    .filter((r) => (r.status === "done" || r.status === "expired") && !firedTodayPDT(r))
    .sort((a, b) => {
      const at = a.lastFiredAt ? new Date(a.lastFiredAt).getTime() : 0;
      const bt = b.lastFiredAt ? new Date(b.lastFiredAt).getTime() : 0;
      return bt - at;
    });

  const activeNotes = notes.filter((n) => n.status === "active");

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ maxWidth: 700 }}>
        <div style={{ marginBottom: "1.25rem" }}>
          <h2 style={{ margin: 0 }}>Nudge</h2>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>Reminders & notes</p>
        </div>

        {/* Tabs */}
        <div style={{ display: "flex", gap: 4, marginBottom: "1.5rem", borderBottom: "1px solid #e5e7eb", paddingBottom: 0 }}>
          {(["reminders", "notes"] as Tab[]).map((t) => (
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
              {t === "reminders"
                ? `Reminders${activeReminders.length ? ` (${activeReminders.length})` : ""}`
                : `Notes${activeNotes.length ? ` (${activeNotes.length})` : ""}`}
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
        ) : tab === "reminders" ? (
          <>
            <ReminderSection
              title="Active"
              reminders={activeReminders}
              onRefresh={loadReminders}
              variant="active"
              emptyText="No active reminders."
            />
            <ReminderSection
              title="Fired Today"
              reminders={firedToday}
              variant="fired"
              emptyText="Nothing fired today yet."
            />
            <ReminderSection
              title="Past"
              reminders={past}
              variant="fired"
              emptyText="No past reminders."
            />
          </>
        ) : (
          <NoteList notes={activeNotes} onRefresh={loadNotes} />
        )}
      </div>
    </div>
  );
}
