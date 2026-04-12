import { NavLink, useNavigate } from "react-router-dom";

const NAV_ITEMS = [
  { label: "WhatsApp", icon: "💬", path: "/alfred" },
  { label: "OurCents", icon: "💰", children: [
    { label: "Dashboard", path: "/ourcents/dashboard" },
    { label: "Upload Receipt", path: "/ourcents/upload" },
    { label: "Receipts", path: "/ourcents/receipts" },
  ]},
  { label: "Nudge", icon: "🔔", path: "/nudge" },
  { label: "Settings", icon: "⚙", path: "/settings" },
];

const activeLinkStyle = {
  background: "#e0e7ff",
  color: "#4338ca",
  fontWeight: 600,
};

export default function Sidebar() {
  const navigate = useNavigate();
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
        {NAV_ITEMS.map((item) =>
          "children" in item ? (
            <div key={item.label}>
              <div style={{ padding: "0.5rem 1.2rem", fontSize: "0.8rem", fontWeight: 600, color: "#64748b", textTransform: "uppercase", letterSpacing: "0.05em" }}>
                {item.icon} {item.label}
              </div>
              {(item.children ?? []).map((child) => (
                <NavLink
                  key={child.path}
                  to={child.path}
                  style={({ isActive }) => ({
                    display: "block",
                    padding: "0.4rem 1.2rem 0.4rem 2rem",
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
