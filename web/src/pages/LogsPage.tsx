import { useEffect, useRef, useState } from "react";

const SERVICES = ["gateway", "ourcents", "nudge", "bridge", "frontend"] as const;
type Service = typeof SERVICES[number];

export default function LogsPage() {
  const alfredToken = localStorage.getItem("alfred_token");
  const [active, setActive] = useState<Service>("gateway");
  const [lines, setLines] = useState<string[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);
  const bottomRef = useRef<HTMLDivElement>(null);

  async function fetchLogs(service: Service, silent = false) {
    if (!alfredToken) return;
    if (!silent) setLoading(true);
    setError("");
    try {
      const res = await fetch(`/api/logs/${service}?lines=300`, {
        headers: { Authorization: `Bearer ${alfredToken}` },
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      setLines(data.lines as string[]);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load logs");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchLogs(active);
    const id = setInterval(() => fetchLogs(active, true), 5000);
    return () => clearInterval(id);
  }, [active]);

  useEffect(() => {
    if (autoScroll) bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, autoScroll]);

  if (!alfredToken) {
    return <p style={{ padding: "1.5rem", color: "#94a3b8" }}>Admin access required.</p>;
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100vh", overflow: "hidden" }}>
      {/* Toolbar */}
      <div style={{ padding: "0.75rem 1rem", borderBottom: "1px solid #e2e8f0", display: "flex", gap: "0.5rem", alignItems: "center", flexShrink: 0 }}>
        <span style={{ fontWeight: 600, fontSize: "0.95rem", marginRight: "0.5rem" }}>Logs</span>
        {SERVICES.map((s) => (
          <button key={s} onClick={() => setActive(s)}
            style={{ padding: "0.3rem 0.75rem", borderRadius: 4, border: "1px solid #e2e8f0", cursor: "pointer",
              background: active === s ? "#4f46e5" : "white", color: active === s ? "white" : "#1e293b",
              fontSize: "0.82rem", fontWeight: active === s ? 600 : 400 }}>
            {s}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <label style={{ fontSize: "0.82rem", color: "#64748b", display: "flex", alignItems: "center", gap: 4, cursor: "pointer" }}>
          <input type="checkbox" checked={autoScroll} onChange={(e) => setAutoScroll(e.target.checked)} />
          Auto-scroll
        </label>
        <button onClick={() => fetchLogs(active)}
          style={{ padding: "0.3rem 0.6rem", borderRadius: 4, border: "1px solid #e2e8f0", background: "white", cursor: "pointer", fontSize: "0.82rem" }}>
          ↺
        </button>
      </div>

      {/* Log output */}
      <div style={{ flex: 1, overflowY: "auto", background: "#0f172a", padding: "0.75rem 1rem", fontFamily: "monospace", fontSize: "0.78rem", lineHeight: 1.6 }}>
        {loading && <p style={{ color: "#94a3b8" }}>Loading…</p>}
        {error && <p style={{ color: "#f87171" }}>{error}</p>}
        {!loading && lines.length === 0 && <p style={{ color: "#475569" }}>No logs found.</p>}
        {lines.map((line, i) => (
          <div key={i} style={{ color: lineColor(line), whiteSpace: "pre-wrap", wordBreak: "break-all" }}>
            {line}
          </div>
        ))}
        <div ref={bottomRef} />
      </div>
    </div>
  );
}

function lineColor(line: string): string {
  const l = line.toLowerCase();
  if (l.includes("error") || l.includes("exception") || l.includes("traceback")) return "#f87171";
  if (l.includes("warning") || l.includes("warn")) return "#fbbf24";
  if (l.includes("info")) return "#94a3b8";
  if (l.includes("debug")) return "#475569";
  return "#cbd5e1";
}
