import React, { useEffect, useState } from "react";
import { listReceipts, getReceipt, confirmReceipt, deleteReceipt } from "../../lib/api/ourcents";

const OURCENTS_BASE = `${window.location.protocol}//${window.location.hostname}:8001`;
const CATEGORIES = ["food", "transportation", "healthcare", "shopping", "entertainment", "utilities", "tools", "other"];
const DEDUCTION_TYPES = ["none", "business", "medical", "charity", "education", "other"];

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

interface Item {
  description: string;
  quantity: number;
  unit_price: number | null;
  total_price: number;
  category: string;
}

interface Deduction {
  is_deductible: number | boolean;
  deduction_type: string;
  evidence_text: string;
  evidence_level: string;
  amount: number;
}

interface ReceiptDetail extends Receipt {
  notes?: string;
  storage_path?: string;
  items: Item[];
  deduction?: Deduction;
}

const STATUS_LABELS: Record<string, string> = {
  pending: "Pending",
  pending_confirmation: "Pending",
  confirmed: "Confirmed",
  rejected: "Rejected",
  duplicate_suspected: "Duplicate?",
  duplicate_confirmed: "Duplicate",
};

const STATUS_COLORS: Record<string, string> = {
  pending: "#fbbf24",
  pending_confirmation: "#fbbf24",
  confirmed: "#22c55e",
  rejected: "#ef4444",
  duplicate_suspected: "#f97316",
  duplicate_confirmed: "#94a3b8",
};

const PENDING = ["pending", "pending_confirmation", "duplicate_suspected"];

export default function Receipts() {
  const [receipts, setReceipts] = useState<Receipt[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [selected, setSelected] = useState<Receipt | null>(null);
  const [detail, setDetail] = useState<ReceiptDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [imageBlobUrl, setImageBlobUrl] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // editable fields
  const [editMerchant, setEditMerchant] = useState("");
  const [editDate, setEditDate] = useState("");
  const [editAmount, setEditAmount] = useState("");
  const [editCategory, setEditCategory] = useState("");
  const [editNotes, setEditNotes] = useState("");
  const [editDeductible, setEditDeductible] = useState(false);
  const [editDeductionType, setEditDeductionType] = useState("none");
  const [editEvidence, setEditEvidence] = useState("");

  function loadReceipts(silent = false) {
    if (!silent) setLoading(true);
    listReceipts({ status_filter: statusFilter || undefined })
      .then((rows) => setReceipts(rows as unknown as Receipt[]))
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }

  useEffect(() => { loadReceipts(); }, [statusFilter]);

  // Auto-refresh every 30s without showing the loading spinner
  useEffect(() => {
    const id = setInterval(() => loadReceipts(true), 30_000);
    return () => clearInterval(id);
  }, [statusFilter]);

  // fetch image as blob (needs auth header)
  useEffect(() => {
    if (!selected) { setImageBlobUrl(null); return; }
    const token = localStorage.getItem("ourcents_token");
    let alive = true;
    fetch(`${OURCENTS_BASE}/api/ourcents/receipts/${selected.id}/image`, {
      headers: token ? { Authorization: `Bearer ${token}` } : {},
    })
      .then((r) => r.ok ? r.blob() : Promise.reject())
      .then((blob) => { if (alive) setImageBlobUrl(URL.createObjectURL(blob)); })
      .catch(() => { if (alive) setImageBlobUrl(null); });
    return () => {
      alive = false;
      setImageBlobUrl((prev) => { if (prev) URL.revokeObjectURL(prev); return null; });
    };
  }, [selected?.id]);

  function openDetail(r: Receipt) {
    setSelected(r);
    setDetail(null);
    setDetailLoading(true);
    getReceipt(r.id)
      .then((d) => {
        const det = d as unknown as ReceiptDetail;
        setDetail(det);
        setEditMerchant(det.merchant_name ?? "");
        setEditDate(det.purchase_date ?? "");
        setEditAmount(String(det.total_amount ?? ""));
        setEditCategory(det.category ?? "other");
        setEditNotes(det.notes ?? "");
        setEditDeductible(!!det.deduction?.is_deductible);
        setEditDeductionType(det.deduction?.deduction_type ?? "none");
        setEditEvidence(det.deduction?.evidence_text ?? "");
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setDetailLoading(false));
  }

  async function handleDelete() {
    if (!selected) return;
    if (!confirm(`Delete receipt from ${selected.merchant_name}? This cannot be undone.`)) return;
    setSaving(true);
    try {
      await deleteReceipt(selected.id);
      setSelected(null);
      setDetail(null);
      loadReceipts();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to delete");
    } finally {
      setSaving(false);
    }
  }

  async function handleConfirm(markAs?: string) {
    if (!selected) return;
    setSaving(true);
    try {
      await confirmReceipt(selected.id, {
        merchant_name: editMerchant,
        purchase_date: editDate,
        total_amount: parseFloat(editAmount) || 0,
        category: editCategory,
        is_deductible: editDeductible,
        deduction_type: editDeductionType,
        deduction_evidence: editEvidence,
        notes: markAs === "duplicate" ? "duplicate" : editNotes,
      });
      loadReceipts();
      setSelected(null);
      setDetail(null);
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed");
    } finally {
      setSaving(false);
    }
  }

  const isPending = selected ? PENDING.includes(selected.status) : false;

  return (
    <div style={{ display: "flex", height: "100vh", overflow: "hidden" }}>

      {/* ── Left: receipt list ──────────────────────────── */}
      <div style={{ width: selected ? 320 : "100%", flexShrink: 0, borderRight: "1px solid #e2e8f0", display: "flex", flexDirection: "column", overflow: "hidden" }}>

        {/* Toolbar */}
        <div style={{ padding: "0.9rem 1rem", borderBottom: "1px solid #e2e8f0", display: "flex", gap: "0.5rem", alignItems: "center" }}>
          <h2 style={{ margin: 0, fontSize: "1.05rem", flex: 1 }}>Receipts</h2>
          <select value={statusFilter} onChange={(e) => setStatusFilter(e.target.value)}
            style={{ padding: "0.25rem 0.4rem", borderRadius: 4, border: "1px solid #e2e8f0", fontSize: "0.82rem" }}>
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="confirmed">Confirmed</option>
            <option value="rejected">Rejected</option>
          </select>
          <button onClick={() => loadReceipts()} style={{ padding: "0.25rem 0.5rem", borderRadius: 4, border: "1px solid #e2e8f0", cursor: "pointer", background: "white", fontSize: "0.85rem" }}>↺</button>
        </div>

        {error && <p style={{ color: "#ef4444", padding: "0.5rem 1rem", margin: 0, fontSize: "0.85rem" }}>{error}</p>}

        {/* List */}
        <div style={{ flex: 1, overflowY: "auto" }}>
          {loading && <p style={{ padding: "1rem", color: "#94a3b8" }}>Loading…</p>}
          {!loading && receipts.length === 0 && <p style={{ padding: "1rem", color: "#94a3b8", textAlign: "center" }}>No receipts found</p>}
          {receipts.map((r) => (
            <div key={r.id} onClick={() => openDetail(r)}
              style={{ padding: "0.75rem 1rem", borderBottom: "1px solid #f1f5f9", cursor: "pointer",
                background: selected?.id === r.id ? "#eef2ff" : "white",
                display: "flex", justifyContent: "space-between", alignItems: "center", gap: "0.5rem" }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 600, fontSize: "0.88rem", color: "#1e293b", overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>
                  {r.merchant_name}
                </div>
                <div style={{ fontSize: "0.78rem", color: "#64748b", marginTop: 2 }}>
                  {r.purchase_date?.slice(0, 10)} · <span style={{ textTransform: "capitalize" }}>{r.category}</span>
                </div>
              </div>
              <div style={{ textAlign: "right", flexShrink: 0 }}>
                <div style={{ fontWeight: 700, fontSize: "0.9rem" }}>${r.total_amount?.toFixed(2)}</div>
                <StatusBadge status={r.status} />
              </div>
            </div>
          ))}
        </div>
      </div>

      {/* ── Right: detail panel ─────────────────────────── */}
      {selected && (
        <div style={{ flex: 1, display: "flex", flexDirection: "column", overflow: "hidden", minWidth: 0 }}>

          {/* Panel header */}
          <div style={{ padding: "0.75rem 1rem", borderBottom: "1px solid #e2e8f0", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <div>
              <span style={{ fontWeight: 700, fontSize: "1rem" }}>{selected.merchant_name}</span>
              <StatusBadge status={selected.status} style={{ marginLeft: 8 }} />
            </div>
            <div style={{ display: "flex", alignItems: "center", gap: "0.5rem" }}>
              <button onClick={handleDelete} disabled={saving}
                style={{ padding: "0.3rem 0.7rem", background: "none", border: "1px solid #fca5a5", color: "#dc2626", borderRadius: 4, cursor: "pointer", fontSize: "0.8rem" }}>
                Delete
              </button>
              <button onClick={() => { setSelected(null); setDetail(null); }}
                style={{ background: "none", border: "none", cursor: "pointer", fontSize: "1.1rem", color: "#94a3b8" }}>✕</button>
            </div>
          </div>

          {/* Two-column body */}
          <div style={{ flex: 1, display: "flex", overflow: "hidden" }}>

            {/* Fields + items */}
            <div style={{ width: 300, flexShrink: 0, borderRight: "1px solid #e2e8f0", overflowY: "auto", padding: "1rem", display: "flex", flexDirection: "column", gap: "0.75rem" }}>
              {detailLoading && <p style={{ color: "#94a3b8" }}>Loading…</p>}

              {detail && (
                <>
                  {/* Core fields */}
                  <section>
                    <SectionLabel>Receipt Info</SectionLabel>
                    <Field label="Merchant"><input value={editMerchant} onChange={(e) => setEditMerchant(e.target.value)} style={inp} disabled={!isPending} /></Field>
                    <Field label="Date"><input type="date" value={editDate} onChange={(e) => setEditDate(e.target.value)} style={inp} disabled={!isPending} /></Field>
                    <Field label="Amount ($)"><input type="number" step="0.01" value={editAmount} onChange={(e) => setEditAmount(e.target.value)} style={inp} disabled={!isPending} /></Field>
                    <Field label="Category">
                      <select value={editCategory} onChange={(e) => setEditCategory(e.target.value)} style={inp} disabled={!isPending}>
                        {CATEGORIES.map((c) => <option key={c} value={c}>{c.charAt(0).toUpperCase() + c.slice(1)}</option>)}
                      </select>
                    </Field>
                    {detail.confidence_score !== undefined && (
                      <Field label="AI Confidence"><span style={{ fontSize: "0.85rem" }}>{Math.round(detail.confidence_score * 100)}%</span></Field>
                    )}
                    <Field label="Uploaded by"><span style={{ fontSize: "0.85rem" }}>{detail.username}</span></Field>
                  </section>

                  {/* Line items */}
                  {detail.items?.length > 0 && (
                    <section>
                      <SectionLabel>Line Items</SectionLabel>
                      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: "0.8rem" }}>
                        <thead>
                          <tr style={{ background: "#f8fafc" }}>
                            <th style={th}>Description</th>
                            <th style={{ ...th, textAlign: "right" }}>Qty</th>
                            <th style={{ ...th, textAlign: "right" }}>Price</th>
                          </tr>
                        </thead>
                        <tbody>
                          {detail.items.map((item, i) => (
                            <tr key={i} style={{ borderBottom: "1px solid #f1f5f9" }}>
                              <td style={td}>{item.description}</td>
                              <td style={{ ...td, textAlign: "right" }}>{item.quantity}</td>
                              <td style={{ ...td, textAlign: "right" }}>${item.total_price?.toFixed(2)}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </section>
                  )}

                  {/* Deduction */}
                  <section>
                    <SectionLabel>Tax Deduction</SectionLabel>
                    <Field label="Deductible">
                      <label style={{ display: "flex", alignItems: "center", gap: 6, fontSize: "0.85rem" }}>
                        <input type="checkbox" checked={editDeductible} onChange={(e) => setEditDeductible(e.target.checked)} disabled={!isPending} />
                        Yes
                      </label>
                    </Field>
                    {editDeductible && (
                      <>
                        <Field label="Deduction Type">
                          <select value={editDeductionType} onChange={(e) => setEditDeductionType(e.target.value)} style={inp} disabled={!isPending}>
                            {DEDUCTION_TYPES.map((t) => <option key={t} value={t}>{t.charAt(0).toUpperCase() + t.slice(1)}</option>)}
                          </select>
                        </Field>
                        <Field label="Evidence">
                          <textarea value={editEvidence} onChange={(e) => setEditEvidence(e.target.value)} style={{ ...inp, resize: "vertical", minHeight: 56 }} disabled={!isPending} />
                        </Field>
                      </>
                    )}
                  </section>

                  {/* Notes */}
                  <section>
                    <SectionLabel>Notes</SectionLabel>
                    <textarea value={editNotes} onChange={(e) => setEditNotes(e.target.value)} style={{ ...inp, resize: "vertical", minHeight: 48, width: "100%", boxSizing: "border-box" }} disabled={!isPending} placeholder="Optional notes…" />
                  </section>

                  {/* Actions */}
                  {isPending ? (
                    <div style={{ display: "flex", flexDirection: "column", gap: "0.4rem", paddingTop: "0.5rem" }}>
                      <button onClick={() => handleConfirm()} disabled={saving}
                        style={{ padding: "0.5rem", borderRadius: 6, border: "none", background: "#22c55e", color: "white", fontWeight: 600, cursor: "pointer", fontSize: "0.9rem" }}>
                        ✓ Confirm Receipt
                      </button>
                      <div style={{ display: "flex", gap: "0.4rem" }}>
                        <button onClick={() => handleConfirm("duplicate")} disabled={saving}
                          style={{ flex: 1, padding: "0.45rem", borderRadius: 6, border: "1px solid #e2e8f0", background: "white", color: "#64748b", cursor: "pointer", fontSize: "0.82rem" }}>
                          Mark Duplicate
                        </button>
                        <button onClick={() => handleConfirm("reject")} disabled={saving}
                          style={{ flex: 1, padding: "0.45rem", borderRadius: 6, border: "none", background: "#ef4444", color: "white", cursor: "pointer", fontSize: "0.82rem" }}>
                          ✗ Reject
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div style={{ padding: "0.5rem", borderRadius: 6, background: selected.status === "confirmed" ? "#dcfce7" : "#f1f5f9",
                      color: selected.status === "confirmed" ? "#16a34a" : "#64748b", fontWeight: 600, textAlign: "center", fontSize: "0.88rem" }}>
                      {STATUS_LABELS[selected.status] ?? selected.status}
                    </div>
                  )}
                </>
              )}
            </div>

            {/* Receipt image */}
            <div style={{ flex: 1, background: "#f8fafc", display: "flex", alignItems: "center", justifyContent: "center", overflow: "auto", padding: "1rem" }}>
              {imageBlobUrl ? (
                <img src={imageBlobUrl} alt="Receipt"
                  style={{ maxWidth: "100%", maxHeight: "100%", objectFit: "contain", borderRadius: 6, boxShadow: "0 2px 16px rgba(0,0,0,0.1)" }} />
              ) : (
                <span style={{ color: "#94a3b8", fontSize: "0.9rem" }}>No image available</span>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function StatusBadge({ status, style }: { status: string; style?: React.CSSProperties }) {
  const color = STATUS_COLORS[status] ?? "#94a3b8";
  return (
    <span style={{ display: "inline-block", padding: "1px 7px", borderRadius: 10, fontSize: "0.75rem",
      background: color + "22", color, fontWeight: 600, ...style }}>
      {STATUS_LABELS[status] ?? status}
    </span>
  );
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: "0.72rem", fontWeight: 700, color: "#94a3b8", letterSpacing: "0.06em", textTransform: "uppercase", marginBottom: 6 }}>{children}</div>;
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div style={{ marginBottom: 8 }}>
      <div style={{ fontSize: "0.75rem", color: "#64748b", marginBottom: 2 }}>{label}</div>
      {children}
    </div>
  );
}

const inp: React.CSSProperties = { width: "100%", padding: "0.3rem 0.45rem", borderRadius: 4, border: "1px solid #e2e8f0", fontSize: "0.85rem", boxSizing: "border-box", background: "white" };
const th: React.CSSProperties = { padding: "0.3rem 0.4rem", textAlign: "left", fontWeight: 600, color: "#64748b", borderBottom: "1px solid #e2e8f0" };
const td: React.CSSProperties = { padding: "0.3rem 0.4rem", color: "#1e293b", verticalAlign: "top" };
