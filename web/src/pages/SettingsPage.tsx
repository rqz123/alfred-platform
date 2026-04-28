import { useEffect, useRef, useState } from "react";
import {
  AlfredUser,
  WaConnection,
  alfredResolve,
  alfredUsers,
  fetchConnections,
  createConnection,
  deleteConnection,
} from "../lib/api/gateway";

export default function SettingsPage() {
  const alfredToken = localStorage.getItem("alfred_token");
  const isAdmin = !!alfredToken;

  // ── My Account (Alfred) ────────────────────────────────────
  const [alfredPhone, setAlfredPhone] = useState(localStorage.getItem("alfred_admin_phone") ?? "");
  const [phoneInput, setPhoneInput] = useState("");
  const [phoneMsg, setPhoneMsg] = useState("");
  const [phoneErr, setPhoneErr] = useState("");
  const [linkingPhone, setLinkingPhone] = useState(false);
  const [alfredMe, setAlfredMe] = useState<AlfredUser | null>(null);
  const [editName, setEditName] = useState("");
  const [savingName, setSavingName] = useState(false);
  const [nameMsg, setNameMsg] = useState("");

  async function loadAlfredAccount(phone: string) {
    try {
      const resolved = await alfredResolve(phone);
      if (!resolved) { setAlfredMe(null); return; }
      const user: AlfredUser = { ...resolved, id: resolved.user_id };
      setAlfredMe(user);
      setEditName(user.display_name ?? "");
    } catch { /* not yet bootstrapped */ }
  }

  useEffect(() => {
    if (alfredPhone) loadAlfredAccount(alfredPhone);
  }, [alfredPhone]);

  async function handleLinkPhone(e: React.FormEvent) {
    e.preventDefault();
    setLinkingPhone(true);
    setPhoneMsg(""); setPhoneErr("");
    try {
      const resolved = await alfredResolve(phoneInput.trim());
      if (!resolved) {
        setPhoneErr("Phone not found — ask an admin to add it first via the Admin Panel.");
        return;
      }
      const phone = phoneInput.trim();
      localStorage.setItem("alfred_admin_phone", phone);
      setAlfredPhone(phone);
      setPhoneInput("");
      setPhoneMsg("Phone linked!");
    } catch (e: unknown) {
      setPhoneErr(e instanceof Error ? e.message : "Failed to verify phone");
    } finally {
      setLinkingPhone(false);
    }
  }

  async function handleSaveName(e: React.FormEvent) {
    e.preventDefault();
    if (!alfredPhone) return;
    setSavingName(true); setNameMsg("");
    try {
      await alfredUsers.update(alfredPhone, alfredPhone, { display_name: editName });
      setNameMsg("Saved.");
      loadAlfredAccount(alfredPhone);
    } catch (e: unknown) {
      setNameMsg(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSavingName(false);
    }
  }

  // ── Alfred Bot ─────────────────────────────────────────────
  const [conn, setConn] = useState<WaConnection | null | undefined>(undefined);
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
      stopPoll();
      pollRef.current = setInterval(loadConn, 3000);
    } catch (e: unknown) {
      setConnError(e instanceof Error ? e.message : "Failed to create connection.");
    } finally {
      setConnWorking(false);
    }
  }

  async function handleReconnect() {
    if (!alfredToken || !conn) return;
    setConnWorking(true);
    setConnError("");
    try {
      await deleteConnection(alfredToken, conn.id);
      await createConnection(alfredToken, "Alfred Bot");
      await loadConn();
      stopPoll();
      pollRef.current = setInterval(loadConn, 3000);
    } catch (e: unknown) {
      setConnError(e instanceof Error ? e.message : "Failed to reconnect.");
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

  return (
    <div style={{ padding: "1.5rem", maxWidth: 620 }}>
      <h2 style={{ marginTop: 0 }}>Settings</h2>

      {/* ── My Account ──────────────────────────────────────── */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>My Account</h3>
        {!alfredPhone ? (
          <>
            <p style={{ color: "#64748b", fontSize: "0.9rem", marginTop: 0 }}>
              Enter your WhatsApp number to link your account.
            </p>
            <form onSubmit={handleLinkPhone} style={{ display: "flex", gap: "0.5rem" }}>
              <input
                type="tel"
                value={phoneInput}
                onChange={(e) => setPhoneInput(e.target.value)}
                placeholder="+14081234567"
                style={inputStyle}
                required
              />
              <button type="submit" disabled={linkingPhone} style={btnStyle}>
                {linkingPhone ? "Verifying…" : "Link"}
              </button>
            </form>
            {phoneMsg && <p style={{ color: "#16a34a", fontSize: "0.875rem", margin: "0.5rem 0 0" }}>{phoneMsg}</p>}
            {phoneErr && <p style={{ color: "#dc2626", fontSize: "0.875rem", margin: "0.5rem 0 0" }}>{phoneErr}</p>}
          </>
        ) : alfredMe ? (
          <>
            <div style={{ display: "flex", gap: "1.5rem", marginBottom: "1rem", flexWrap: "wrap" }}>
              <div>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: 2 }}>Phone</div>
                <code style={codeStyle}>{alfredMe.phone}</code>
              </div>
              <div>
                <div style={{ fontSize: "0.75rem", color: "#94a3b8", marginBottom: 2 }}>Role</div>
                <span style={{
                  display: "inline-block", padding: "0.1rem 0.5rem", borderRadius: 3, fontSize: "0.8rem",
                  background: alfredMe.role === "admin" ? "#e0e7ff" : "#f1f5f9",
                  color: alfredMe.role === "admin" ? "#4338ca" : "#475569",
                  fontWeight: alfredMe.role === "admin" ? 600 : 400,
                }}>{alfredMe.role}</span>
              </div>
            </div>
            <form onSubmit={handleSaveName} style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
              <label style={{ fontSize: "0.875rem", color: "#475569", whiteSpace: "nowrap" }}>Display name</label>
              <input
                value={editName}
                onChange={(e) => setEditName(e.target.value)}
                style={{ ...inputStyle, flex: 1 }}
                placeholder="Your name"
              />
              <button type="submit" disabled={savingName} style={btnStyle}>
                {savingName ? "Saving…" : "Save"}
              </button>
            </form>
            {nameMsg && <p style={{ color: "#16a34a", fontSize: "0.875rem", margin: "0.5rem 0 0" }}>{nameMsg}</p>}
            <button
              style={{ marginTop: "1rem", background: "none", border: "none", color: "#94a3b8", fontSize: "0.8rem", cursor: "pointer", padding: 0 }}
              onClick={() => { localStorage.removeItem("alfred_admin_phone"); setAlfredPhone(""); setAlfredMe(null); }}
            >
              Unlink phone
            </button>
          </>
        ) : (
          <p style={{ color: "#64748b", fontSize: "0.875rem" }}>
            Linked as <code style={codeStyle}>{alfredPhone}</code> — loading…
          </p>
        )}
      </section>

      {/* ── Alfred Bot (admin only) ──────────────────────────── */}
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

          {conn && conn.status === "offline" && (
            <div style={{ display: "flex", alignItems: "center", gap: "1rem", flexWrap: "wrap" }}>
              <span style={{ color: "#92400e", fontSize: "0.9rem" }}>
                ⚠ Bot is offline — click Reconnect to get a new QR code.
              </span>
              <button onClick={handleReconnect} disabled={connWorking} style={btnStyle}>
                {connWorking ? "Reconnecting…" : "Reconnect"}
              </button>
              <button onClick={handleDisconnect} disabled={connWorking} style={dangerBtnStyle}>
                Remove
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
const codeStyle: React.CSSProperties = {
  background: "#f8fafc",
  padding: "0.1rem 0.4rem",
  borderRadius: 3,
  fontFamily: "monospace",
  fontSize: "0.9em",
};
