import { useState } from "react";
import { NavLink, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { label: "WhatsApp", icon: "💬", path: "/alfred" },
  { label: "OurCents", icon: "💰", children: [
    { label: "Dashboard", path: "/ourcents/dashboard" },
    { label: "Upload Receipt", path: "/ourcents/upload" },
    { label: "Receipts", path: "/ourcents/receipts" },
  ]},
  { label: "Nudge", icon: "🔔", children: [
    { label: "Dashboard", path: "/nudge/dashboard" },
    { label: "Set Reminder", path: "/nudge/set-reminder" },
  ]},
  { label: "Settings", icon: "⚙", path: "/settings" },
  { label: "Logs", icon: "📋", path: "/logs", adminOnly: true },
];

const activeLinkStyle = {
  background: "#e0e7ff",
  color: "#4338ca",
  fontWeight: 600,
};

export default function Sidebar() {
  const [expanded, setExpanded] = useState<Record<string, boolean>>({});
  const navigate = useNavigate();
  const isAdmin = !!localStorage.getItem("alfred_token");
  const visibleItems = NAV_ITEMS.filter((item) => !("adminOnly" in item && item.adminOnly && !isAdmin));
  const username = (() => {
    try {
      const raw = localStorage.getItem("alfred_user") ?? localStorage.getItem("ourcents_user");
      return raw ? (JSON.parse(raw) as { username: string }).username : "admin";
    } catch { return "admin"; }
  })();

  function handleLogout() {
    localStorage.removeItem("alfred_token");
    localStorage.removeItem("alfred_user");
    localStorage.removeItem("ourcents_token");
    localStorage.removeItem("ourcents_user");
    navigate("/login");
  }

  return (
    <nav
      style={{
        width: 220,
        flexShrink: 0,
        borderRight: "1px solid #e2e8f0",
        display: "flex",
        flexDirection: "column",
        height: "100vh",
        background: "#f8fafc",
        padding: "1rem 0",
      }}
    >
      <div style={{ padding: "0.5rem 1.2rem 1rem", fontWeight: 700, fontSize: "1.1rem", color: "#1e293b" }}>
        Alfred
      </div>

      <div style={{ flex: 1, overflowY: "auto" }}>
        {visibleItems.map((item) =>
          "children" in item ? (
            <div key={item.label}>
              <div
                onClick={() => setExpanded((prev) => ({ ...prev, [item.label]: !prev[item.label] }))}
                style={{ padding: "0.5rem 1.2rem", margin: "0 0.5rem", fontSize: "0.95rem", fontWeight: 400, color: "#475569", cursor: "pointer", userSelect: "none", display: "flex", justifyContent: "space-between", alignItems: "center", borderRadius: 4 }}
              >
                <span>{item.icon} {item.label}</span>
                <span style={{ fontSize: "0.7rem", color: "#94a3b8" }}>{expanded[item.label] ? "▲" : "▼"}</span>
              </div>
              {expanded[item.label] && (item.children ?? []).map((child) => (
                <NavLink
                  key={child.path}
                  to={child.path}
                  style={({ isActive }) => ({
                    display: "block",
                    padding: "0.4rem 1rem 0.4rem 3rem",
                    textDecoration: "none",
                    color: "#475569",
                    fontSize: "0.9rem",
                    borderRadius: 4,
                    margin: "0 0.5rem",
                    ...(isActive ? activeLinkStyle : {}),
                  })}
                >
                  {child.label}
                </NavLink>
              ))}
            </div>
          ) : (
            <NavLink
              key={item.path}
              to={item.path}
              style={({ isActive }) => ({
                display: "block",
                padding: "0.5rem 1.2rem",
                textDecoration: "none",
                color: "#475569",
                fontSize: "0.95rem",
                borderRadius: 4,
                margin: "0 0.5rem",
                ...(isActive ? activeLinkStyle : {}),
              })}
            >
              {item.icon} {item.label}
            </NavLink>
          )
        )}
      </div>

      <div style={{ padding: "1rem 1.2rem", borderTop: "1px solid #e2e8f0" }}>
        <div style={{ fontSize: "0.85rem", color: "#64748b", marginBottom: "0.5rem" }}>{username}</div>
        <button
          onClick={handleLogout}
          style={{
            width: "100%",
            padding: "0.4rem",
            background: "none",
            border: "1px solid #e2e8f0",
            borderRadius: 4,
            cursor: "pointer",
            color: "#64748b",
            fontSize: "0.85rem",
          }}
        >
          Sign out
        </button>
      </div>
    </nav>
  );
}
