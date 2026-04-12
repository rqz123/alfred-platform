import { useEffect, useState } from "react";
import { listReceipts, getReceipt, confirmReceipt } from "../../lib/api/ourcents";

interface Receipt {
  id: number;
  merchant_name: string;
  purchase_date: string;
  total_amount: number;
  currency: string;
  category: string;
  status: string;
  confidence_score?: number;
  username: string;
}

const STATUS_LABELS: Record<string, string> = {
  pending_confirmation: "Pending",
  confirmed: "Confirmed",
  rejected: "Rejected",
  duplicate_suspected: "Duplicate?",
};

const STATUS_COLORS: Record<string, string> = {
  pending_confirmation: "#fbbf24",
  confirmed: "#22c55e",
  rejected: "#ef4444",
  duplicate_suspected: "#f97316",
};

export default function Receipts() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<Record<string, unknown> | null>(null);
  const [confirming, setConfirming] = useState(false);

  function loadReceipts() {
    setLoading(true);
    listReceipts({ status_filter: statusFilter || undefined })
      .then((rows) => setReceipts(rows as unknown as Receipt[]))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadReceipts(); }, [statusFilter]);

  function openDetail(id: number) {
    setSelected(id);
    setDetail(null);
    getReceipt(id).then(setDetail).catch((e: Error) => setError(e.message));
  }

  async function handleQuickConfirm(receipt: Receipt) {
    setConfirming(true);
    try {
      await confirmReceipt(receipt.id, {
        merchant_name: receipt.merchant_name,
        purchase_date: receipt.purchase_date,
        total_amount: receipt.total_amount,
        category: receipt.category,
        is_deductible: false,
        deduction_type: "none",
        deduction_evidence: "",
        notes: "",
      });
      loadReceipts();
      if (selected === receipt.id) setSelected(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Confirm failed");
    } finally {
      setConfirming(false);
    }
  }

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1.5rem" }}>
        <h2 style={{ margin: 0 }}>Receipts</h2>
        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          style={{ padding: "0.3rem 0.6rem", borderRadius: 4 }}
        >
          <option value="">All Statuses</option>
          <option value="pending">Pending</option>
          <option value="confirmed">Confirmed</option>
          <option value="rejected">Rejected</option>
        </select>
        <button onClick={loadReceipts} style={{ padding: "0.3rem 0.8rem", borderRadius: 4, cursor: "pointer" }}>
          Refresh
        </button>
      </div>

      {error && <p style={{ color: "red" }}>{error}</p>}
      {loading && <p>Loading…</p>}

      {!loading && (
        <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.9rem" }}>
          <thead>
            <tr style={{ borderBottom: "2px solid #e2e8f0", textAlign: "left" }}>
              <th style={{ padding: "0.5rem" }}>Merchant</th>
              <th style={{ padding: "0.5rem" }}>Date</th>
              <th style={{ padding: "0.5rem" }}>Amount</th>
              <th style={{ padding: "0.5rem" }}>Category</th>
              <th style={{ padding: "0.5rem" }}>Status</th>
              <th style={{ padding: "0.5rem" }}>Actions</th>
            </tr>
          </thead>
          <tbody>
            {receipts.map((r) => (
              <tr
                key={r.id}
                style={{
                  borderBottom: "1px solid #f1f5f9",
                  background: selected === r.id ? "#f0f4ff" : "transparent",
                }}
              >
                <td style={{ padding: "0.5rem" }}>
                  <button
                    onClick={() => openDetail(r.id)}
                    style={{ background: "none", border: "none", cursor: "pointer", color: "#6366f1", textDecoration: "underline", padding: 0 }}
                  >
                    {r.merchant_name}
                  </button>
                </td>
                <td style={{ padding: "0.5rem" }}>{r.purchase_date}</td>
                <td style={{ padding: "0.5rem" }}>${r.total_amount?.toFixed(2)}</td>
                <td style={{ padding: "0.5rem", textTransform: "capitalize" }}>{r.category?.replace("_", " ")}</td>
                <td style={{ padding: "0.5rem" }}>
                  <span
                    style={{
                      padding: "2px 8px",
                      borderRadius: 12,
                      fontSize: "0.8rem",
                      background: STATUS_COLORS[r.status] + "22",
                      color: STATUS_COLORS[r.status] ?? "#64748b",
                      fontWeight: 600,
                    }}
                  >
                    {STATUS_LABELS[r.status] ?? r.status}
                  </span>
                </td>
                <td style={{ padding: "0.5rem" }}>
                  {r.status === "pending_confirmation" && (
                    <button
                      onClick={() => handleQuickConfirm(r)}
                      disabled={confirming}
                      style={{ padding: "2px 10px", borderRadius: 4, cursor: "pointer", background: "#22c55e", color: "white", border: "none", fontSize: "0.8rem" }}
                    >
                      Confirm
                    </button>
                  )}
                </td>
              </tr>
            ))}
            {receipts.length === 0 && (
              <tr><td colSpan={6} style={{ padding: "1rem", textAlign: "center", color: "#94a3b8" }}>No receipts found</td></tr>
            )}
          </tbody>
        </table>
      )}

      {/* Detail panel */}
      {selected && detail && (
        <div style={{ marginTop: "1.5rem", padding: "1rem", background: "#f8fafc", borderRadius: 8, border: "1px solid #e2e8f0" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <h3 style={{ margin: 0 }}>Receipt #{selected}</h3>
            <button onClick={() => setSelected(null)} style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1.2rem" }}>✕</button>
          </div>
          <pre style={{ fontSize: "0.8rem", overflow: "auto", maxHeight: 300 }}>{JSON.stringify(detail, null, 2)}</pre>
        </div>
      )}
    </div>
  );
}
