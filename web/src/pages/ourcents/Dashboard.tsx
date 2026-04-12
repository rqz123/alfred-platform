import { useEffect, useState } from "react";
import {
  BarChart,
  Bar,
  PieChart,
  Pie,
  Cell,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { getDashboard } from "../../lib/api/ourcents";

const PERIOD_OPTIONS = ["week", "month", "year"];
const COLORS = ["#6366f1", "#22c55e", "#f59e0b", "#ef4444", "#3b82f6", "#ec4899", "#14b8a6", "#f97316"];

interface CategoryData {
  category: string;
  total: number;
}

interface DashboardData {
  summary?: { total_amount: number; receipt_count: number; average_amount: number };
  category_breakdown?: CategoryData[];
  monthly_trends?: { month: string; total: number }[];
}

export default function Dashboard() {
  const [period, setPeriod] = useState("month");
  const [data, setData] = useState<DashboardData>({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    setError("");
    getDashboard(period)
      .then((d) => setData(d as DashboardData))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [period]);

  const categoryData = (data.category_breakdown ?? []).map((c) => ({
    name: c.category,
    value: c.total,
  }));

  const trendData = data.monthly_trends ?? [];

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.5rem" }}>
        <h2 style={{ margin: 0 }}>Dashboard</h2>
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

      {!loading && !error && (
        <>
          {/* Summary cards */}
          {data.summary && (
            <div style={{ display: "flex", gap: "1rem", marginBottom: "2rem", flexWrap: "wrap" }}>
              <StatCard label="Total Spent" value={`$${data.summary.total_amount?.toFixed(2) ?? "0.00"}`} />
              <StatCard label="Receipts" value={String(data.summary.receipt_count ?? 0)} />
              <StatCard label="Average" value={`$${data.summary.average_amount?.toFixed(2) ?? "0.00"}`} />
            </div>
          )}

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

            {/* Monthly trends bar chart */}
            {trendData.length > 0 && (
              <div style={{ flex: 2, minWidth: 300 }}>
                <h3>Monthly Trends</h3>
                <ResponsiveContainer width="100%" height={280}>
                  <BarChart data={trendData}>
                    <XAxis dataKey="month" />
                    <YAxis />
                    <Tooltip formatter={(v: number) => `$${v.toFixed(2)}`} />
                    <Legend />
                    <Bar dataKey="total" fill="#6366f1" name="Spending" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}

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
