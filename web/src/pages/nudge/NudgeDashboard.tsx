import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listReminders } from "../../lib/api/nudge";
import { listPhoneBindings } from "../../lib/api/ourcents";
import { ReminderSection } from "./ReminderList";
import type { Reminder } from "../../lib/types/nudge";

const TZ = "America/Los_Angeles";

function todayStrPDT(): string {
  return new Date().toLocaleDateString("en-CA", { timeZone: TZ }); // "YYYY-MM-DD"
}

function firedTodayPDT(r: Reminder): boolean {
  if (!r.lastFiredAt) return false;
  return new Date(r.lastFiredAt).toLocaleDateString("en-CA", { timeZone: TZ }) === todayStrPDT();
}

export default function NudgeDashboard() {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasPhone, setHasPhone] = useState<boolean | null>(null);
  const navigate = useNavigate();

  function loadReminders() {
    listReminders()
      .then(setReminders)
      .catch(() => {})
      .finally(() => setLoading(false));
  }

  useEffect(() => {
    loadReminders();
    listPhoneBindings()
      .then((b) => setHasPhone(b.length > 0))
      .catch(() => setHasPhone(null));
  }, []);

  // Section 1: active + paused
  const activeReminders = reminders.filter(
    (r) => r.status === "active" || r.status === "paused"
  );

  // Section 2: fired today (done, lastFiredAt is today in PDT)
  const firedToday = reminders
    .filter((r) => (r.status === "done" || r.status === "expired") && firedTodayPDT(r))
    .sort((a, b) => new Date(b.lastFiredAt!).getTime() - new Date(a.lastFiredAt!).getTime());

  // Section 3: past (done/expired but not today)
  const past = reminders
    .filter((r) => (r.status === "done" || r.status === "expired") && !firedTodayPDT(r))
    .sort((a, b) => {
      const at = a.lastFiredAt ? new Date(a.lastFiredAt).getTime() : 0;
      const bt = b.lastFiredAt ? new Date(b.lastFiredAt).getTime() : 0;
      return bt - at;
    });

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ maxWidth: 700 }}>
        <div style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ margin: 0 }}>Nudge</h2>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>Your reminders at a glance</p>
        </div>

        {hasPhone === false && (
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
        ) : (
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
        )}
      </div>
    </div>
  );
}
