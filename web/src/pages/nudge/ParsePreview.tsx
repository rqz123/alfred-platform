import type { ParseResponse, ReminderCreate } from "../../lib/types/nudge";

interface Props {
  result: ParseResponse;
  onConfirm: (data: ReminderCreate) => void;
  onCancel: () => void;
  saving: boolean;
}

function formatTime(fireAt?: string | null, nextFireAt?: string | null): string {
  const iso = fireAt || nextFireAt;
  if (!iso) return "—";
  try {
    return new Intl.DateTimeFormat("en-US", {
      dateStyle: "medium",
      timeStyle: "short",
    }).format(new Date(iso));
  } catch {
    return iso;
  }
}

function typeLabel(type: string) {
  return { once: "One-time", recurring: "Recurring", event: "Event-driven" }[type] ?? type;
}

export function ParsePreview({ result, onConfirm, onCancel, saving }: Props) {
  const { reminder, confidence, rawInterpretation, nextFireAt } = result;
  const isLowConfidence = confidence < 0.6;

  function handleConfirm() {
    onConfirm({
      title: reminder.title,
      body: reminder.body,
      type: reminder.type,
      fireAt: reminder.fireAt,
      cronExpression: reminder.cronExpression,
      timezone: reminder.timezone,
    });
  }

  return (
    <div style={styles.card}>
      <div style={styles.header}>AI Parse Result</div>

      {isLowConfidence && (
        <div style={styles.warning}>Low confidence — please review carefully</div>
      )}

      <div style={styles.row}>
        <span style={styles.label}>Title</span>
        <span style={styles.value}>{reminder.title}</span>
      </div>

      {reminder.body && (
        <div style={styles.row}>
          <span style={styles.label}>Body</span>
          <span style={styles.value}>{reminder.body}</span>
        </div>
      )}

      <div style={styles.row}>
        <span style={styles.label}>Type</span>
        <span style={{ ...styles.badge, background: typeColor(reminder.type) }}>
          {typeLabel(reminder.type)}
        </span>
      </div>

      {reminder.cronExpression && (
        <div style={styles.row}>
          <span style={styles.label}>Cron</span>
          <code style={styles.code}>{reminder.cronExpression}</code>
        </div>
      )}

      <div style={styles.row}>
        <span style={styles.label}>Time</span>
        <span style={styles.value}>
          {formatTime(reminder.fireAt, nextFireAt)}
        </span>
      </div>

      <div style={styles.row}>
        <span style={styles.label}>Confidence</span>
        <span style={styles.value}>{Math.round(confidence * 100)}%</span>
      </div>

      <div style={styles.interpretation}>AI understood: {rawInterpretation}</div>

      <div style={styles.actions}>
        <button onClick={onCancel} style={styles.cancelBtn} disabled={saving}>
          Cancel
        </button>
        <button onClick={handleConfirm} style={styles.confirmBtn} disabled={saving}>
          {saving ? "Saving…" : "Confirm & Save"}
        </button>
      </div>
    </div>
  );
}

function typeColor(type: string) {
  return { once: "#dbeafe", recurring: "#dcfce7", event: "#fef9c3" }[type] ?? "#f3f4f6";
}

const styles: Record<string, React.CSSProperties> = {
  card: {
    border: "1px solid #e5e7eb",
    borderRadius: 10,
    padding: "16px 20px",
    display: "flex",
    flexDirection: "column",
    gap: 10,
    background: "#fafafa",
  },
  header: {
    fontWeight: 600,
    fontSize: 15,
    color: "#111827",
  },
  warning: {
    background: "#fef3c7",
    border: "1px solid #fbbf24",
    borderRadius: 6,
    padding: "6px 10px",
    fontSize: 13,
    color: "#92400e",
  },
  row: {
    display: "flex",
    alignItems: "center",
    gap: 10,
  },
  label: {
    width: 60,
    fontSize: 13,
    color: "#6b7280",
    flexShrink: 0,
  },
  value: {
    fontSize: 14,
    color: "#111827",
  },
  badge: {
    fontSize: 12,
    padding: "2px 8px",
    borderRadius: 99,
    color: "#374151",
  },
  code: {
    fontSize: 13,
    background: "#f3f4f6",
    padding: "2px 6px",
    borderRadius: 4,
    fontFamily: "monospace",
  },
  interpretation: {
    fontSize: 12,
    color: "#9ca3af",
    fontStyle: "italic",
  },
  actions: {
    display: "flex",
    justifyContent: "flex-end",
    gap: 8,
    marginTop: 4,
  },
  cancelBtn: {
    padding: "7px 16px",
    borderRadius: 7,
    border: "1px solid #d1d5db",
    background: "#fff",
    cursor: "pointer",
    fontSize: 14,
  },
  confirmBtn: {
    padding: "7px 16px",
    borderRadius: 7,
    border: "none",
    background: "#16a34a",
    color: "#fff",
    cursor: "pointer",
    fontSize: 14,
  },
};
