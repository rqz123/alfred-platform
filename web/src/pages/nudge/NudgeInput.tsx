import { useState } from "react";

interface Props {
  onParse: (input: string, timezone: string) => void;
  loading: boolean;
}

export function NudgeInput({ onParse, loading }: Props) {
  const [input, setInput] = useState("");
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone;

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = input.trim();
    if (!trimmed) return;
    onParse(trimmed, timezone);
  }

  return (
    <form onSubmit={handleSubmit} style={styles.form}>
      <textarea
        value={input}
        onChange={(e) => setInput(e.target.value)}
        placeholder="What do you want to be reminded of? e.g. Remind me to write the weekly report every Monday at 9am"
        rows={3}
        style={styles.textarea}
        disabled={loading}
      />
      <button type="submit" disabled={loading || !input.trim()} style={styles.button}>
        {loading ? "Parsing…" : "Parse Reminder"}
      </button>
    </form>
  );
}

const styles: Record<string, React.CSSProperties> = {
  form: {
    display: "flex",
    flexDirection: "column",
    gap: 8,
  },
  textarea: {
    padding: "10px 12px",
    fontSize: 15,
    borderRadius: 8,
    border: "1px solid #d1d5db",
    resize: "vertical",
    fontFamily: "inherit",
    outline: "none",
  },
  button: {
    alignSelf: "flex-end",
    padding: "8px 20px",
    fontSize: 14,
    borderRadius: 8,
    border: "none",
    background: "#2563eb",
    color: "#fff",
    cursor: "pointer",
  },
};
