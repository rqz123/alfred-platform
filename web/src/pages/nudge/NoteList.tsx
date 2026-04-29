import { useState } from "react";
import type { Note } from "../../lib/types/nudge";
import { deleteNote } from "../../lib/api/nudge";

const TZ = "America/Los_Angeles";

function formatNoteDate(iso: string): string {
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

function NoteRow({ note, onRefresh }: { note: Note; onRefresh: () => void }) {
  const [busy, setBusy] = useState(false);

  async function handleDelete() {
    if (!confirm("Delete this note?")) return;
    setBusy(true);
    try {
      await deleteNote(note.id);
      onRefresh();
    } catch (e) {
      alert(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setBusy(false);
    }
  }

  return (
    <li style={styles.item}>
      <div style={styles.header}>
        <span style={styles.date}>{formatNoteDate(note.createdAt)}</span>
        <button
          onClick={handleDelete}
          disabled={busy}
          title="Delete"
          style={styles.deleteBtn}
        >
          ✕
        </button>
      </div>
      <p style={styles.content}>{note.content}</p>
      {note.tags && note.tags.length > 0 && (
        <div style={styles.tags}>
          {note.tags.map((t) => (
            <span key={t} style={styles.tag}>{t}</span>
          ))}
        </div>
      )}
    </li>
  );
}

interface Props {
  notes: Note[];
  onRefresh: () => void;
}

export function NoteList({ notes, onRefresh }: Props) {
  if (notes.length === 0) {
    return (
      <div style={styles.empty}>
        <p style={{ margin: 0 }}>No notes yet.</p>
        <p style={{ margin: "6px 0 0", fontSize: 12, color: "#9ca3af" }}>
          Send Alfred a WhatsApp message like "note bought blood pressure pills" to save a note.
        </p>
      </div>
    );
  }

  return (
    <ul style={styles.list}>
      {notes.map((n) => (
        <NoteRow key={n.id} note={n} onRefresh={onRefresh} />
      ))}
    </ul>
  );
}

const styles: Record<string, React.CSSProperties> = {
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
    alignItems: "center",
  },
  date: {
    fontSize: 11,
    color: "#9ca3af",
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
