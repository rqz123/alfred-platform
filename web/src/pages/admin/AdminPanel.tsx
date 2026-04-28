import { useEffect, useState } from "react";
import {
  AlfredUser,
  AlfredFamily,
  AlfredFamilyDetail,
  alfredUsers,
  alfredFamilies,
} from "../../lib/api/gateway";

// ── Shared styles ──────────────────────────────────────────────────────────────

const sectionStyle: React.CSSProperties = {
  background: "#fff",
  border: "1px solid #e2e8f0",
  borderRadius: 8,
  padding: "1.25rem 1.5rem",
  marginBottom: "1.5rem",
};
const btnStyle: React.CSSProperties = {
  padding: "0.4rem 1rem",
  background: "#4f46e5",
  color: "#fff",
  border: "none",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: "0.875rem",
  whiteSpace: "nowrap",
};
const dangerBtn: React.CSSProperties = {
  padding: "0.3rem 0.7rem",
  background: "none",
  border: "1px solid #fca5a5",
  color: "#dc2626",
  borderRadius: 4,
  cursor: "pointer",
  fontSize: "0.8rem",
};
const inputStyle: React.CSSProperties = {
  padding: "0.4rem 0.7rem",
  border: "1px solid #e2e8f0",
  borderRadius: 4,
  fontSize: "0.875rem",
  outline: "none",
};
const thStyle: React.CSSProperties = { padding: "0.4rem 0.6rem", color: "#64748b", fontWeight: 600, textAlign: "left" };
const tdStyle: React.CSSProperties = { padding: "0.5rem 0.6rem", verticalAlign: "middle", fontSize: "0.875rem" };
const tabBtn = (active: boolean): React.CSSProperties => ({
  padding: "0.45rem 1.2rem",
  border: "none",
  borderBottom: active ? "2px solid #4f46e5" : "2px solid transparent",
  background: "none",
  color: active ? "#4f46e5" : "#64748b",
  fontWeight: active ? 600 : 400,
  cursor: "pointer",
  fontSize: "0.95rem",
});

// ── Main component ────────────────────────────────────────────────────────────

export default function AdminPanel() {
  const adminPhone = localStorage.getItem("alfred_admin_phone") ?? "";
  const [tab, setTab] = useState<"users" | "families">("users");

  if (!adminPhone) {
    return (
      <div style={{ padding: "1.5rem", maxWidth: 620 }}>
        <h2 style={{ marginTop: 0 }}>Admin Panel</h2>
        <div style={{ ...sectionStyle, color: "#92400e" }}>
          Your Alfred phone is not linked yet. Go to{" "}
          <a href="/settings" style={{ color: "#4f46e5" }}>Settings → My Account</a>{" "}
          and enter your phone number first.
        </div>
      </div>
    );
  }

  return (
    <div style={{ padding: "1.5rem", maxWidth: 800 }}>
      <h2 style={{ marginTop: 0 }}>Admin Panel</h2>

      <div style={{ display: "flex", borderBottom: "1px solid #e2e8f0", marginBottom: "1.5rem" }}>
        <button style={tabBtn(tab === "users")} onClick={() => setTab("users")}>Users</button>
        <button style={tabBtn(tab === "families")} onClick={() => setTab("families")}>Families</button>
      </div>

      {tab === "users" && <UsersTab adminPhone={adminPhone} />}
      {tab === "families" && <FamiliesTab adminPhone={adminPhone} />}
    </div>
  );
}

// ── Users Tab ─────────────────────────────────────────────────────────────────

function UsersTab({ adminPhone }: { adminPhone: string }) {
  const [users, setUsers] = useState<AlfredUser[]>([]);
  const [families, setFamilies] = useState<AlfredFamily[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [addPhone, setAddPhone] = useState("");
  const [addName, setAddName] = useState("");
  const [addFamilyId, setAddFamilyId] = useState("");
  const [adding, setAdding] = useState(false);
  const [addMsg, setAddMsg] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      const [u, f] = await Promise.all([
        alfredUsers.list(adminPhone),
        alfredFamilies.list(adminPhone),
      ]);
      setUsers(u);
      setFamilies(f);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load users");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, []);

  async function handleAdd(e: React.FormEvent) {
    e.preventDefault();
    if (!addPhone.trim()) return;
    setAdding(true);
    setAddMsg("");
    setError("");
    try {
      await alfredUsers.create(adminPhone, {
        phone: addPhone.trim(),
        display_name: addName.trim() || undefined,
        family_id: addFamilyId || undefined,
      });
      setAddPhone(""); setAddName(""); setAddFamilyId("");
      setAddMsg("User added.");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to add user");
    } finally {
      setAdding(false);
    }
  }

  async function handleSetRole(phone: string, role: "admin" | "user") {
    setError("");
    try {
      await alfredUsers.update(adminPhone, phone, { role });
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to update role");
    }
  }

  async function handleDelete(phone: string) {
    if (!confirm(`Delete user ${phone}? This is irreversible and will erase all their data.`)) return;
    setError("");
    try {
      await alfredUsers.delete(adminPhone, phone);
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete user");
    }
  }

  const familyName = (id: string | null) =>
    id ? (families.find((f) => f.id === id)?.name ?? id) : "—";

  return (
    <>
      {/* Add user form */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Add User</h3>
        <form onSubmit={handleAdd} style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
          <input
            style={{ ...inputStyle, minWidth: 150 }}
            placeholder="+14081234567"
            value={addPhone}
            onChange={(e) => setAddPhone(e.target.value)}
            required
          />
          <input
            style={{ ...inputStyle, minWidth: 120 }}
            placeholder="Display name"
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
          />
          <select
            style={{ ...inputStyle, minWidth: 140 }}
            value={addFamilyId}
            onChange={(e) => setAddFamilyId(e.target.value)}
          >
            <option value="">No family</option>
            {families.map((f) => (
              <option key={f.id} value={f.id}>{f.name}</option>
            ))}
          </select>
          <button type="submit" disabled={adding} style={btnStyle}>
            {adding ? "Adding…" : "Add"}
          </button>
        </form>
        {addMsg && <p style={{ color: "#16a34a", fontSize: "0.875rem", margin: "0.5rem 0 0" }}>{addMsg}</p>}
      </section>

      {/* Users table */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>All Users</h3>
        {error && <p style={{ color: "#dc2626", fontSize: "0.875rem" }}>{error}</p>}
        {loading ? (
          <p style={{ color: "#64748b", fontSize: "0.875rem" }}>Loading…</p>
        ) : users.length === 0 ? (
          <p style={{ color: "#94a3b8", fontSize: "0.875rem" }}>No users yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
                <th style={thStyle}>Phone</th>
                <th style={thStyle}>Name</th>
                <th style={thStyle}>Role</th>
                <th style={thStyle}>Family</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {users.map((u) => (
                <tr key={u.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={tdStyle}>
                    <code style={{ fontFamily: "monospace", fontSize: "0.875em" }}>{u.phone}</code>
                  </td>
                  <td style={tdStyle}>{u.display_name ?? <span style={{ color: "#94a3b8" }}>—</span>}</td>
                  <td style={tdStyle}>
                    <span style={{
                      display: "inline-block",
                      padding: "0.15rem 0.5rem",
                      borderRadius: 3,
                      fontSize: "0.8rem",
                      background: u.role === "admin" ? "#e0e7ff" : "#f1f5f9",
                      color: u.role === "admin" ? "#4338ca" : "#475569",
                      fontWeight: u.role === "admin" ? 600 : 400,
                    }}>
                      {u.role}
                    </span>
                  </td>
                  <td style={tdStyle}>{familyName(u.family_id)}</td>
                  <td style={{ ...tdStyle, display: "flex", gap: "0.4rem" }}>
                    {u.role === "user" ? (
                      <button style={{ ...dangerBtn, border: "1px solid #bbf7d0", color: "#16a34a" }}
                        onClick={() => handleSetRole(u.phone, "admin")}>
                        Make admin
                      </button>
                    ) : (
                      <button style={{ ...dangerBtn, border: "1px solid #e2e8f0", color: "#64748b" }}
                        onClick={() => handleSetRole(u.phone, "user")}>
                        Demote
                      </button>
                    )}
                    <button style={dangerBtn} onClick={() => handleDelete(u.phone)}>Delete</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  );
}

// ── Families Tab ──────────────────────────────────────────────────────────────

function FamiliesTab({ adminPhone }: { adminPhone: string }) {
  const [families, setFamilies] = useState<AlfredFamily[]>([]);
  const [selected, setSelected] = useState<AlfredFamilyDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [newName, setNewName] = useState("");
  const [creating, setCreating] = useState(false);
  const [createMsg, setCreateMsg] = useState("");

  async function load() {
    setLoading(true);
    setError("");
    try {
      setFamilies(await alfredFamilies.list(adminPhone));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load families");
    } finally {
      setLoading(false);
    }
  }

  async function loadDetail(id: string) {
    setError("");
    try {
      setSelected(await alfredFamilies.get(adminPhone, id));
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to load family detail");
    }
  }

  useEffect(() => { load(); }, []);

  async function handleCreate(e: React.FormEvent) {
    e.preventDefault();
    if (!newName.trim()) return;
    setCreating(true);
    setCreateMsg("");
    setError("");
    try {
      await alfredFamilies.create(adminPhone, newName.trim());
      setNewName("");
      setCreateMsg("Family created.");
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to create family");
    } finally {
      setCreating(false);
    }
  }

  async function handleDissolve(id: string, name: string) {
    if (!confirm(`Dissolve family "${name}"? Members will remain but lose their family association.`)) return;
    setError("");
    try {
      await alfredFamilies.delete(adminPhone, id);
      if (selected?.id === id) setSelected(null);
      load();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to dissolve family");
    }
  }

  return (
    <>
      {/* Create family */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>Create Family</h3>
        <form onSubmit={handleCreate} style={{ display: "flex", gap: "0.5rem" }}>
          <input
            style={{ ...inputStyle, minWidth: 200 }}
            placeholder="Family name"
            value={newName}
            onChange={(e) => setNewName(e.target.value)}
            required
          />
          <button type="submit" disabled={creating} style={btnStyle}>
            {creating ? "Creating…" : "Create"}
          </button>
        </form>
        {createMsg && <p style={{ color: "#16a34a", fontSize: "0.875rem", margin: "0.5rem 0 0" }}>{createMsg}</p>}
      </section>

      {/* Families list */}
      <section style={sectionStyle}>
        <h3 style={{ marginTop: 0 }}>All Families</h3>
        {error && <p style={{ color: "#dc2626", fontSize: "0.875rem" }}>{error}</p>}
        {loading ? (
          <p style={{ color: "#64748b", fontSize: "0.875rem" }}>Loading…</p>
        ) : families.length === 0 ? (
          <p style={{ color: "#94a3b8", fontSize: "0.875rem" }}>No families yet.</p>
        ) : (
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
                <th style={thStyle}>Name</th>
                <th style={thStyle}>ID</th>
                <th style={thStyle}></th>
              </tr>
            </thead>
            <tbody>
              {families.map((f) => (
                <tr key={f.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                  <td style={tdStyle}>
                    <button
                      style={{ background: "none", border: "none", color: "#4f46e5", cursor: "pointer", fontSize: "0.875rem", padding: 0 }}
                      onClick={() => selected?.id === f.id ? setSelected(null) : loadDetail(f.id)}
                    >
                      {f.name}
                    </button>
                  </td>
                  <td style={{ ...tdStyle, color: "#94a3b8", fontFamily: "monospace", fontSize: "0.8em" }}>{f.id}</td>
                  <td style={tdStyle}>
                    <button style={dangerBtn} onClick={() => handleDissolve(f.id, f.name)}>Dissolve</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* Family detail */}
      {selected && (
        <section style={sectionStyle}>
          <h3 style={{ marginTop: 0 }}>Members — {selected.name}</h3>
          {selected.members.length === 0 ? (
            <p style={{ color: "#94a3b8", fontSize: "0.875rem" }}>No members.</p>
          ) : (
            <table style={{ width: "100%", borderCollapse: "collapse" }}>
              <thead>
                <tr style={{ borderBottom: "1px solid #e2e8f0" }}>
                  <th style={thStyle}>Phone</th>
                  <th style={thStyle}>Name</th>
                  <th style={thStyle}>Role</th>
                </tr>
              </thead>
              <tbody>
                {selected.members.map((m) => (
                  <tr key={m.id} style={{ borderBottom: "1px solid #f1f5f9" }}>
                    <td style={tdStyle}><code style={{ fontFamily: "monospace", fontSize: "0.875em" }}>{m.phone}</code></td>
                    <td style={tdStyle}>{m.display_name ?? <span style={{ color: "#94a3b8" }}>—</span>}</td>
                    <td style={tdStyle}>{m.role}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      )}
    </>
  );
}
