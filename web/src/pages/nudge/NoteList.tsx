import { useState, useMemo } from "react";
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

  const allEntities = [
    ...(note.entities?.people ?? []),
    ...(note.entities?.places ?? []),
    ...(note.entities?.orgs ?? []),
  ];

  return (
    <li style={styles.item}>
      <div style={styles.header}>
        <div style={styles.headerLeft}>
          {note.shortId != null && (
            <span style={styles.shortId}>#{note.shortId}</span>
          )}
          {note.title && (
            <span style={styles.title}>{note.title}</span>
          )}
        </div>
        <div style={styles.headerRight}>
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
      </div>

      <p style={styles.content}>{note.content}</p>

      {allEntities.length > 0 && (
        <div style={styles.pills}>
          {allEntities.map((e, i) => (
            <span key={i} style={styles.entityPill}>{e}</span>
          ))}
        </div>
      )}

      {note.relatedIds && note.relatedIds.length > 0 && (
        <div style={styles.related}>
          <span style={styles.relatedLabel}>Related:</span>
          {note.relatedIds.map((id) => (
            <span key={id} style={styles.relatedBadge}>#{id}</span>
          ))}
        </div>
      )}

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
  const [search, setSearch] = useState("");

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase();
    if (!q) return notes;
    return notes.filter(
      (n) =>
        n.content.toLowerCase().includes(q) ||
        (n.title ?? "").toLowerCase().includes(q) ||
        (n.entities?.people ?? []).some((e) => e.toLowerCase().includes(q)) ||
        (n.entities?.places ?? []).some((e) => e.toLowerCase().includes(q)) ||
        (n.entities?.orgs ?? []).some((e) => e.toLowerCase().includes(q))
    );
  }, [notes, search]);

  if (notes.length === 0) {
    return (
      <div style={styles.empty}>
        <p style={{ margin: 0 }}>No notes yet.</p>
        <p style={{ margin: "6px 0 0", fontSize: 12, color: "#9ca3af" }}>
          Send Alfred a WhatsApp message like "note bought blood pressure pills"
          to save a note.
        </p>
      </div>
    );
  }

  return (
    <div>
      <div style={styles.searchBar}>
        <input
          type="text"
          placeholder="Search notes…"
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
            No notes match &ldquo;{search}&rdquo;
          </p>
        </div>
      ) : (
        <ul style={styles.list}>
          {filtered.map((n) => (
            <NoteRow key={n.id} note={n} onRefresh={onRefresh} />
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
