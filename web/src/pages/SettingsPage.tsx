import { useEffect, useState } from "react";
import {
  PhoneBinding,
  listPhoneBindings,
  bindPhone,
  unbindPhone,
} from "../lib/api/ourcents";

export default function SettingsPage() {
  const [bindings, setBindings] = useState<PhoneBinding[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [phone, setPhone] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState("");

  function load() {
    setLoading(true);
    setError("");
    listPhoneBindings()
      .then(setBindings)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function handleBind(e: React.FormEvent) {
    e.preventDefault();
    if (!phone.trim()) return;
    setSaving(true);
    setSaveMsg("");
    setError("");
    try {
      await bindPhone(phone.trim());
      setPhone("");
      setSaveMsg("Phone number bound successfully.");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to bind phone.");
    } finally {
      setSaving(false);
    }
  }

  async function handleUnbind(p: string) {
    if (!confirm(`Remove binding for ${p}?`)) return;
    setError("");
    try {
      await unbindPhone(p);
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to remove binding.");
    }
  }

  return (
    <div style={{ padding: "1.5rem", maxWidth: 600 }}>
      <h2 style={{ marginTop: 0 }}>Settings</h2>

      {/* ── WhatsApp Phone Binding ─────────────────────────── */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>WhatsApp Phone Binding</h3>
        <p style={{ color: "#64748b", fontSize: "0.9rem", marginTop: 0 }}>
          Link your WhatsApp phone number so Alfred can identify you when you
          send messages. Use the international format, e.g.{" "}
          <code>+8613800000000</code>.
        </p>

        {/* Add new binding */}
        <form onSubmit={handleBind} style={{ display: "flex", gap: "0.5rem", marginBottom: "1rem" }}>
          <input
            type="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="+8613800000000"
            disabled={saving}
            style={inputStyle}
          />
          <button type="submit" disabled={saving || !phone.trim()} style={btnStyle}>
            {saving ? "Binding…" : "Bind"}
          </button>
        </form>

        {saveMsg && <p style={{ color: "#16a34a", fontSize: "0.9rem" }}>{saveMsg}</p>}
        {error && <p style={{ color: "#dc2626", fontSize: "0.9rem" }}>{error}</p>}

        {/* Binding list */}
        {loading ? (
          <p style={{ color: "#64748b" }}>Loading…</p>
        ) : bindings.length === 0 ? (
          <p style={{ color: "#94a3b8", fontSize: "0.9rem" }}>No phone numbers bound yet.</p>
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
                  <td style={tdStyle}>
                    <code style={{ background: "#f8fafc", padding: "0.1rem 0.4rem", borderRadius: 3 }}>
                      +{b.phone}
                    </code>
                  </td>
                  <td style={tdStyle}>{b.username}</td>
                  <td style={tdStyle}>{new Date(b.created_at).toLocaleDateString()}</td>
                  <td style={tdStyle}>
                    <button
                      onClick={() => handleUnbind(b.phone)}
                      style={deleteBtnStyle}
                    >
                      Remove
                    </button>
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

const deleteBtnStyle: React.CSSProperties = {
  padding: "0.25rem 0.6rem",
  background: "none",
  border: "1px solid #fca5a5",
  color: "#dc2626",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: "0.8rem",
};

const thStyle: React.CSSProperties = {
  padding: "0.4rem 0.6rem",
  color: "#64748b",
  fontWeight: 600,
};

const tdStyle: React.CSSProperties = {
  padding: "0.5rem 0.6rem",
  verticalAlign: "middle",
};
