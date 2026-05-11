import { useState } from "react";
import type { Weaving } from "../../lib/types/brain";
import { confirmWeaving, correctWeaving } from "../../lib/api/brain";

interface Props {
  weavings: Weaving[];
  familyId: string;
  onUpdate: () => void;
}

const STATUS_COLOR: Record<string, string> = {
  proposed: "#F59E0B",
  confirmed: "#10B981",
  corrected: "#9CA3AF",
};

export default function WeavingsPanel({ weavings, familyId, onUpdate }: Props) {
  const [loading, setLoading] = useState<string | null>(null);

  async function handleConfirm(id: string) {
    setLoading(id);
    try {
      await confirmWeaving(id);
      onUpdate();
    } finally {
      setLoading(null);
    }
  }

  async function handleCorrect(id: string) {
    setLoading(id);
    try {
      await correctWeaving(id, familyId, "User disconnected from graph");
      onUpdate();
    } finally {
      setLoading(null);
    }
  }

  if (!weavings.length) {
    return (
      <div style={{ padding: "1.5rem", color: "#9CA3AF", fontSize: "0.9rem", textAlign: "center" }}>
        No weavings yet. Send a WhatsApp message and add an expense to see a golden thread appear.
      </div>
    );
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "0.75rem", padding: "0.5rem" }}>
      {weavings.map((w) => (
        <div
          key={w.id}
          style={{
            border: "1px solid #E5E7EB",
            borderRadius: 8,
            padding: "0.75rem 1rem",
            background: "#FAFAFA",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "0.5rem", marginBottom: "0.35rem" }}>
            <span
              style={{
                display: "inline-block",
                width: 8,
                height: 8,
                borderRadius: "50%",
                background: STATUS_COLOR[w.status] ?? "#9CA3AF",
              }}
            />
            <span style={{ fontWeight: 600, fontSize: "0.9rem", color: "#1F2937" }}>
              {w.title ?? "Untitled Weaving"}
            </span>
            <span
              style={{
                marginLeft: "auto",
                fontSize: "0.75rem",
                color: STATUS_COLOR[w.status] ?? "#9CA3AF",
                textTransform: "capitalize",
              }}
            >
              {w.status}
            </span>
          </div>

          {w.fact_cosine !== null && (
            <div style={{ fontSize: "0.78rem", color: "#6B7280", marginBottom: "0.5rem" }}>
              Semantic similarity: {(w.fact_cosine * 100).toFixed(0)}%
            </div>
          )}

          {w.status === "proposed" && (
            <div style={{ display: "flex", gap: "0.5rem", marginTop: "0.35rem" }}>
              <button
                onClick={() => handleConfirm(w.id)}
                disabled={loading === w.id}
                style={{
                  padding: "0.3rem 0.8rem",
                  fontSize: "0.8rem",
                  background: "#F59E0B",
                  color: "#fff",
                  border: "none",
                  borderRadius: 4,
                  cursor: "pointer",
                  fontWeight: 600,
                }}
              >
                Confirm
              </button>
              <button
                onClick={() => handleCorrect(w.id)}
                disabled={loading === w.id}
                style={{
                  padding: "0.3rem 0.8rem",
                  fontSize: "0.8rem",
                  background: "none",
                  color: "#6B7280",
                  border: "1px solid #D1D5DB",
                  borderRadius: 4,
                  cursor: "pointer",
                }}
              >
                Disconnect
              </button>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}
