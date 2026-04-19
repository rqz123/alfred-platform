import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { listReminders } from "../../lib/api/nudge";
import { listPhoneBindings } from "../../lib/api/ourcents";
import { ReminderList } from "./ReminderList";
import type { Reminder } from "../../lib/types/nudge";

export default function NudgeDashboard() {
  const [reminders, setReminders] = useState<Reminder[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasPhone, setHasPhone] = useState<boolean | null>(null);
  const navigate = useNavigate();

  useEffect(() => {
    listReminders()
      .then(setReminders)
      .catch(() => {})
      .finally(() => setLoading(false));
    listPhoneBindings()
      .then((b) => setHasPhone(b.length > 0))
      .catch(() => setHasPhone(null));
  }, []);

  const active = reminders.filter((r) => r.status === "active").length;
  const fired = reminders.filter((r) => r.status === "done").length;
  const paused = reminders.filter((r) => r.status === "paused").length;

  const now = new Date();
  const todayEnd = new Date(now.getFullYear(), now.getMonth(), now.getDate(), 23, 59, 59);
  const upcomingToday = reminders.filter((r) => {
    if (r.status !== "active") return false;
    const fire = r.nextFireAt ?? r.fireAt;
    if (!fire) return false;
    const d = new Date(fire);
    return d >= now && d <= todayEnd;
  }).length;

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ maxWidth: 700 }}>
        <div style={{ marginBottom: "1.5rem" }}>
          <h2 style={{ margin: 0 }}>Nudge</h2>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>Your reminders at a glance</p>
        </div>

        {hasPhone === false && (
          <div style={{ background: "#fffbeb", border: "1px solid #fcd34d", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#92400e", marginBottom: "1rem", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>⚠ No phone number linked — reminders will fire but alerts won't be sent.</span>
            <button
              onClick={() => navigate("/settings")}
              style={{ marginLeft: 12, padding: "3px 10px", fontSize: 12, borderRadius: 4, border: "1px solid #f59e0b", background: "#fef3c7", cursor: "pointer", color: "#92400e" }}
            >
              Go to Settings
            </button>
          </div>
        )}

        <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem", flexWrap: "wrap" }}>
          <StatCard label="Active" value={String(active)} color="#16a34a" />
          <StatCard label="Firing Today" value={String(upcomingToday)} color="#6366f1" />
          <StatCard label="Fired" value={String(fired)} color="#6b7280" />
          <StatCard label="Paused" value={String(paused)} color="#d97706" />
        </div>

        {loading ? (
          <p style={{ color: "#9ca3af", fontSize: 14 }}>Loading…</p>
        ) : (
          <ReminderList reminders={reminders} />
        )}
      </div>
    </div>
  );
}

function StatCard({ label, value, color }: { label: string; value: string; color: string }) {
  return (
    <div style={{ padding: "1rem 1.5rem", background: "#f8f9fa", borderRadius: 8, border: "1px solid #e2e8f0", minWidth: 120 }}>
      <div style={{ fontSize: "0.85rem", color: "#64748b" }}>{label}</div>
      <div style={{ fontSize: "1.5rem", fontWeight: 700, color }}>{value}</div>
    </div>
  );
}
