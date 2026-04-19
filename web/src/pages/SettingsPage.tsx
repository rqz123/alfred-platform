import { useEffect, useRef, useState } from "react";
import {
  PhoneBinding,
  listPhoneBindings,
  bindPhone,
  unbindPhone,
} from "../lib/api/ourcents";
import {
  WaConnection,
  fetchConnections,
  createConnection,
  deleteConnection,
} from "../lib/api/gateway";

export default function SettingsPage() {
  const alfredToken = localStorage.getItem("alfred_token");
  const isAdmin = !!alfredToken;

  // ── Bot state ──────────────────────────────────────────────
  const [conn, setConn] = useState<WaConnection | null | undefined>(undefined); // undefined = loading
  const [connError, setConnError] = useState("");
  const [connWorking, setConnWorking] = useState(false);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  function stopPoll() {
    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
  }

  async function loadConn() {
    if (!alfredToken) return;
    try {
      const list = await fetchConnections(alfredToken);
      setConn(list.length > 0 ? list[0] : null);
      if (list[0]?.status === "connected") stopPoll();
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Failed to load bot status.";
      const isAuth = msg.toLowerCase().includes("401") || msg.toLowerCase().includes("unauthorized") || msg.toLowerCase().includes("invalid token");
      setConnError(isAuth ? "Session expired — please sign out and sign in again." : msg);
      setConn(null);
    }
  }

  useEffect(() => {
    if (!isAdmin) return;
    loadConn();
    return stopPoll;
  }, []);

  async function handleSetupBot() {
    if (!alfredToken) return;
    setConnWorking(true);
    setConnError("");
    try {
      await createConnection(alfredToken, "Alfred Bot");
      await loadConn();
      // Start polling until connected
      stopPoll();
      pollRef.current = setInterval(loadConn, 3000);
    } catch (e: unknown) {
      setConnError(e instanceof Error ? e.message : "Failed to create connection.");
    } finally {
      setConnWorking(false);
    }
  }

  async function handleDisconnect() {
    if (!alfredToken || !conn) return;
    if (!confirm("Disconnect Alfred's WhatsApp bot? Reminders and incoming messages will stop working.")) return;
    setConnWorking(true);
    setConnError("");
    try {
      await deleteConnection(alfredToken, conn.id);
      setConn(null);
      stopPoll();
    } catch (e: unknown) {
      setConnError(e instanceof Error ? e.message : "Failed to disconnect.");
    } finally {
      setConnWorking(false);
    }
  }

  // ── Phone binding state ────────────────────────────────────
  const [bindings, setBindings] = useState<PhoneBinding[]>([]);
  const [bindLoading, setBindLoading] = useState(true);
  const [bindError, setBindError] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  function loadBindings() {
    setBindLoading(true);
    setBindError("");
    listPhoneBindings()
      .then(setBindings)
      .catch((e: Error) => setBindError(e.message))
      .finally(() => setBindLoading(false));
  }

  useEffect(loadBindings, []);

  async function handleBind(e: React.FormEvent) {
    e.preventDefault();
    if (!phone.trim()) return;
    setSaving(true);
    setSaveMsg("");
    setBindError("");
    try {
      await bindPhone(phone.trim());
      setPhone("");
      setSaveMsg("Phone number bound successfully.");
      loadBindings();
    } catch (e: unknown) {
      setBindError(e instanceof Error ? e.message : "Failed to bind phone.");
    } finally {
      setSaving(false);
    }
  }

  async function handleUnbind(p: string) {
    if (!confirm(`Remove binding for +${p}?`)) return;
    setBindError("");
    try {
      await unbindPhone(p);
      loadBindings();
    } catch (e: unknown) {
      setBindError(e instanceof Error ? e.message : "Failed to remove binding.");
    }
  }

  const botPhone = conn?.connected_phone ?? null;

  return (
    <div style={{ padding: "1.5rem", maxWidth: 620 }}>
      <h2 style={{ marginTop: 0 }}>Settings</h2>

      {/* ── Section 1: Alfred Bot (admin only) ──────────────── */}
      {isAdmin && (
        <section style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Alfred Bot</h3>
          <p style={{ color: "#64748b", fontSize: "0.9rem", marginTop: 0 }}>
            Alfred communicates with users via a dedicated WhatsApp number.
            Set it up here by scanning the QR code with that phone.
          </p>

          {connError && <p style={{ color: "#dc2626", fontSize: "0.9rem" }}>{connError}</p>}

          {conn === undefined && (
            <p style={{ color: "#64748b", fontSize: "0.9rem" }}>Loading…</p>
          )}

          {conn === null && (
            <div style={{ display: "flex", alignItems: "center", gap: "1rem" }}>
              <span style={{ color: "#92400e", fontSize: "0.9rem" }}>
                ⚠ Alfred's WhatsApp bot is not set up.
              </span>
              <button onClick={handleSetupBot} disabled={connWorking} style={btnStyle}>
                {connWorking ? "Setting up…" : "Set Up Bot"}
              </button>
            </div>
          )}

          {conn && conn.status === "qr_ready" && (
            <div>
              <p style={{ fontSize: "0.9rem", color: "#1e293b", marginBottom: "0.5rem" }}>
                Scan this QR code with Alfred's WhatsApp phone:
              </p>
              <p style={{ fontSize: "0.85rem", color: "#64748b", margin: "0 0 0.75rem" }}>
                On that phone: WhatsApp → Linked Devices → Link a Device
              </p>
              {conn.qr_code_data_url && (
                <img
                  src={conn.qr_code_data_url}
                  alt="WhatsApp QR code"
                  style={{ width: 200, height: 200, border: "1px solid #e2e8f0", borderRadius: 8 }}
                />
              )}
              <p style={{ fontSize: "0.8rem", color: "#94a3b8", marginTop: "0.5rem" }}>
                Waiting for scan… (refreshing automatically)
              </p>
            </div>
          )}

          {conn && conn.status === "connected" && (
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
              <span style={{ color: "#16a34a", fontSize: "0.9rem", fontWeight: 500 }}>
                ✓ Connected
              </span>
              {conn.connected_phone && (
                <code style={codeStyle}>+{conn.connected_phone}</code>
              )}
              {conn.connected_name && (
                <span style={{ color: "#64748b", fontSize: "0.9rem" }}>{conn.connected_name}</span>
              )}
              <button onClick={handleDisconnect} disabled={connWorking} style={dangerBtnStyle}>
                {connWorking ? "Disconnecting…" : "Disconnect"}
              </button>
            </div>
          )}
        </section>
      )}

      {/* ── Section 2: My WhatsApp Number ───────────────────── */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>My WhatsApp Number</h3>
        <p style={{ color: "#64748b", fontSize: "0.9rem", marginTop: 0 }}>
          Add your personal WhatsApp number. Alfred will send you reminders here,
          and recognize your messages when you chat with the bot.
          Use the international format, e.g. <code>+14081234567</code>.
        </p>

        <form onSubmit={handleBind} style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+14081234567"
            disabled={saving}
            style={inputStyle}
          />
          <button type="submit" disabled={saving || !phone.trim()} style={btnStyle}>
            {saving ? "Saving…" : "Save"}
          </button>
        </form>

        {saveMsg && <p style={{ color: "#16a34a", fontSize: "0.9rem" }}>{saveMsg}</p>}
        {bindError && <p style={{ color: "#dc2626", fontSize: "0.9rem" }}>{bindError}</p>}

        {bindLoading ? (
          <p style={{ color: "#64748b", fontSize: "0.9rem" }}>Loading…</p>
        ) : bindings.filter((b) => {
          try {
            const me = JSON.parse(localStorage.getItem("ourcents_user") ?? "{}");
            return b.username === me.username;
          } catch { return false; }
        }).map((b) => (
          <div key={b.id} style={{ display: "flex", alignItems: "center", gap: "0.75rem", marginTop: "0.5rem" }}>
            <code style={codeStyle}>+{b.phone}</code>
            <button onClick={() => handleUnbind(b.phone)} style={deleteBtnStyle}>Remove</button>
          </div>
        ))}
      </section>

      {/* ── Section 3: Family Members ────────────────────────── */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Family Members</h3>
        <p style={{ color: "#64748b", fontSize: "0.9rem", marginTop: 0 }}>
          Everyone in your family who has connected their WhatsApp to Alfred.
        </p>

        {/* Invite instructions */}
        <div style={{ background: "#f8fafc", border: "1px solid #e2e8f0", borderRadius: 6, padding: "0.75rem 1rem", marginBottom: "1rem", fontSize: "0.875rem", color: "#475569" }}>
          <strong>To invite someone:</strong>
          <ol style={{ margin: "0.4rem 0 0", paddingLeft: "1.25rem", lineHeight: 1.8 }}>
            <li>
              Share Alfred's WhatsApp number:{" "}
              {botPhone
                ? <code style={codeStyle}>+{botPhone}</code>
                : <span style={{ color: "#94a3b8" }}>— (bot not connected)</span>}
            </li>
            <li>Ask them to add it to WhatsApp contacts and send a message.</li>
            <li>Have them register on this app and add their number in <em>My WhatsApp Number</em> above.</li>
          </ol>
        </div>

        {bindLoading ? (
          <p style={{ color: "#64748b", fontSize: "0.9rem" }}>Loading…</p>
        ) : bindings.length === 0 ? (
          <p style={{ color: "#94a3b8", fontSize: "0.9rem" }}>No members connected yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e2e8f0", textAlign: "left" }}>
                <th style={thStyle}>Phone</th>
                <th style={thStyle}>User</th>
                <th style={thStyle}>Bound at</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {bindings.map((b) => (
                <tr key={b.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={tdStyle}><code style={codeStyle}>+{b.phone}</code></td>
                  <td style={tdStyle}>{b.username}</td>
                  <td style={tdStyle}>{new Date(b.created_at).toLocaleDateString()}</td>
                  <td style={tdStyle}>
                    <button onClick={() => handleUnbind(b.phone)} style={deleteBtnStyle}>Remove</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  );
}

const sectionStyle: React.CSSProperties = {
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 8,
  padding: "1.25rem 1.5rem",
  marginBottom: "1.5rem",
};
const inputStyle: React.CSSProperties = {
  flex: 1,
  padding: "0.45rem 0.75rem",
  border: "1px solid #e2e8f0",
  borderRadius: 4,
  fontSize: "0.95rem",
  outline: "none",
};
const btnStyle: React.CSSProperties = {
  padding: "0.45rem 1.1rem",
  background: "#4f46e5",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: "0.9rem",
  whiteSpace: "nowrap",
};
const dangerBtnStyle: React.CSSProperties = {
  ...btnStyle,
  background: "none",
  border: "1px solid #fca5a5",
  color: "#dc2626",
};
const deleteBtnStyle: React.CSSProperties = {
  padding: "0.25rem 0.6rem",
  background: "none",
  border: "1px solid #fca5a5",
  color: "#dc2626",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: "0.8rem",
};
const codeStyle: React.CSSProperties = {
  background: "#f8fafc",
  padding: "0.1rem 0.4rem",
  borderRadius: 3,
  fontFamily: "monospace",
  fontSize: "0.9em",
};
const thStyle: React.CSSProperties = { padding: "0.4rem 0.6rem", color: "#64748b", fontWeight: 600 };
const tdStyle: React.CSSProperties = { padding: "0.5rem 0.6rem", verticalAlign: "middle" };
