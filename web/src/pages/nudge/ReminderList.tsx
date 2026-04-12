import type { Reminder } from "../../lib/types/nudge";

interface Props {
  reminders: Reminder[];
}

function formatTime(iso?: string | null, tz?: string): string {
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
      timeZone: tz,
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
  done: "#6b7280",
  expired: "#dc2626",
};

export function ReminderList({ reminders }: Props) {
  if (reminders.length === 0) {
    return <p style={styles.empty}>No reminders yet. Type one above.</p>;
  }

  return (
    <ul style={styles.list}>
      {reminders.map((r) => (
        <li key={r.id} style={styles.item}>
          <div style={styles.top}>
            <span style={styles.title}>{r.title}</span>
            <span style={{ ...styles.status, color: STATUS_COLOR[r.status] ?? "#6b7280" }}>
              {r.status}
            </span>
          </div>

          <div style={styles.meta}>
            <span style={styles.typeBadge}>{TYPE_LABEL[r.type] ?? r.type}</span>
            <span style={styles.metaText}>
              {r.nextFireAt
                ? `Next: ${formatTime(r.nextFireAt, r.timezone)}`
                : r.fireAt
                ? formatTime(r.fireAt, r.timezone)
                : null}
            </span>
            {r.cronExpression && (
              <code style={styles.cron}>{r.cronExpression}</code>
            )}
          </div>

          {r.body && <p style={styles.body}>{r.body}</p>}
        </li>
      ))}
    </ul>
  );
}

const styles: Record<string, React.CSSProperties> = {
  empty: {
    color: "#9ca3af",
    fontSize: 14,
    textAlign: "center",
    padding: "24px 0",
  },
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
    padding: "12px 14px",
    background: "#fff",
    display: "flex",
    flexDirection: "column",
    gap: 4,
  },
  top: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  title: {
    fontWeight: 600,
    fontSize: 14,
    color: "#111827",
  },
  status: {
    fontSize: 12,
    fontWeight: 500,
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
