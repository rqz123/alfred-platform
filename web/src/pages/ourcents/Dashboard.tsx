import React, { useEffect, useState } from "react";
import {
  PieChart,
  Pie,
  Cell,
  Tooltip,
  ResponsiveContainer,
} from "recharts";
import { getDashboard } from "../../lib/api/ourcents";

const PERIOD_OPTIONS = ["week", "month", "year"];
const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#3b82f6", "#ec4899", "#14b8a6", "#f97316"];

interface ApiResponse {
  total_amount: number;
  receipt_count: number;
  average_amount: number;
  deductible_total: number;
  category_breakdown: Record<string, number>;
  recent_receipts: { merchant_name: string; total_amount: number; purchase_date: string; category: string }[];
}

export default function Dashboard() {
  const [period, setPeriod] = useState("month");
  const [data, setData] = useState<ApiResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const familyName = (() => {
    try {
      const raw = localStorage.getItem("ourcents_user");
      return raw ? (JSON.parse(raw) as { family_name: string }).family_name : null;
    } catch { return null; }
  })();

  useEffect(() => {
    setLoading(true);
    setError("");
    getDashboard(period)
      .then((d) => setData(d as unknown as ApiResponse))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [period]);

  const categoryData = Object.entries(data?.category_breakdown ?? {}).map(([name, value]) => ({
    name,
    value,
  }));

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.5rem", flexWrap: "wrap" }}>
        <h2 style={{ margin: 0 }}>Dashboard</h2>
        {familyName && (
          <span style={{ fontSize: 13, color: "#6b7280", background: "#f3f4f6", padding: "2px 10px", borderRadius: 99 }}>
            {familyName}
          </span>
        )}
        <select
          value={period}
          onChange={(e) => setPeriod(e.target.value)}
          style={{ padding: "0.3rem 0.6rem", borderRadius: 4 }}
        >
          {PERIOD_OPTIONS.map((p) => (
            <option key={p} value={p}>{p.charAt(0).toUpperCase() + p.slice(1)}</option>
          ))}
        </select>
      </div>

      {loading && <p>Loading…</p>}
      {error && <p style={{ color: "red" }}>{error}</p>}

      {!loading && !error && data && (
        <>
          {/* Summary cards */}
          <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem", flexWrap: "wrap" }}>
            <StatCard label="Total Spent" value={`$${data.total_amount?.toFixed(2) ?? "0.00"}`} />
            <StatCard label="Receipts" value={String(data.receipt_count ?? 0)} />
            <StatCard label="Average" value={`$${data.average_amount?.toFixed(2) ?? "0.00"}`} />
            <StatCard label="Deductible" value={`$${data.deductible_total?.toFixed(2) ?? "0.00"}`} />
          </div>

          <div style={{ display: "flex", gap: "2rem", flexWrap: "wrap" }}>
            {/* Category breakdown pie chart */}
            {categoryData.length > 0 && (
              <div style={{ flex: 1, minWidth: 280 }}>
                <h3>By Category</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <PieChart>
                    <Pie
                      data={categoryData}
                      dataKey="value"
                      nameKey="name"
                      cx="50%"
                      cy="50%"
                      outerRadius={100}
                      label={({ name, percent }) => `${name} ${(percent * 100).toFixed(0)}%`}
                    >
                      {categoryData.map((_, i) => (
                        <Cell key={i} fill={COLORS[i % COLORS.length]} />
                      ))}
                    </Pie>
                    <Tooltip formatter={(v: number) => `$${v.toFixed(2)}`} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}

            {/* Recent receipts */}
            {data.recent_receipts.length > 0 && (
              <div style={{ flex: 2, minWidth: 300 }}>
                <h3>Recent Receipts</h3>
                <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
                  <thead>
                    <tr style={{ background: "#f1f5f9" }}>
                      <th style={thStyle}>Merchant</th>
                      <th style={thStyle}>Date</th>
                      <th style={thStyle}>Category</th>
                      <th style={{ ...thStyle, textAlign: "right" }}>Amount</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.recent_receipts.map((r, i) => (
                      <tr key={i} style={{ borderBottom: "1px solid #e2e8f0" }}>
                        <td style={tdStyle}>{r.merchant_name}</td>
                        <td style={tdStyle}>{r.purchase_date?.slice(0, 10)}</td>
                        <td style={tdStyle}>{r.category}</td>
                        <td style={{ ...tdStyle, textAlign: "right" }}>${r.total_amount?.toFixed(2)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

const thStyle: React.CSSProperties = { padding: "0.4rem 0.6rem", textAlign: "left", fontWeight: 600, color: "#475569" };
const tdStyle: React.CSSProperties = { padding: "0.4rem 0.6rem", color: "#1e293b" };

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        padding: "1rem 1.5rem",
        background: "#f8f9fa",
        borderRadius: 8,
        border: "1px solid #e2e8f0",
        minWidth: 140,
      }}
    >
      <div style={{ fontSize: "0.85rem", color: "#64748b" }}>{label}</div>
      <div style={{ fontSize: "1.5rem", fontWeight: 700 }}>{value}</div>
    </div>
  );
}
