import { useEffect, useRef, useState, useCallback } from "react";
import * as d3 from "d3";
import type { GraphData, GraphNode, GraphEdge, Weaving } from "../../lib/types/brain";
import { fetchGraph, fetchWeavings, confirmWeaving, correctWeaving } from "../../lib/api/brain";
import WeavingsPanel from "./WeavingsPanel";

// ── Color constants ──────────────────────────────────────────────────────────
const NODE_COLORS: Record<string, string> = {
  thread: "#F59E0B",
  expense: "#3B82F6",
  reminder: "#10B981",
};
const EDGE_GOLD = "#F59E0B";
const EDGE_CORRECTED = "#9CA3AF";

// Derive family_id from localStorage or fetch from gateway
async function resolveFamilyId(): Promise<string> {
  try {
    const raw = localStorage.getItem("alfred_user");
    if (raw) {
      const u = JSON.parse(raw) as Record<string, unknown>;
      if (u.family_id) return String(u.family_id);
    }
  } catch {}

  // Fallback: fetch first family from gateway
  const base = `${window.location.protocol}//${window.location.hostname}:8000`;
  const token = localStorage.getItem("alfred_token");
  const phone = localStorage.getItem("alfred_admin_phone");
  const headers: Record<string, string> = {};
  if (token) headers["Authorization"] = `Bearer ${token}`;
  if (phone) headers["X-Alfred-Phone"] = phone;
  const res = await fetch(`${base}/api/alfred/families`, { headers });
  if (res.ok) {
    const families = await res.json() as Array<{ id: string }>;
    if (families.length > 0) return families[0].id;
  }
  return "";
}

interface TooltipState {
  weaving: Weaving | null;
  x: number;
  y: number;
}

export default function GraphPage() {
  const svgRef = useRef<SVGSVGElement>(null);
  const [graphData, setGraphData] = useState<GraphData | null>(null);
  const [weavings, setWeavings] = useState<Weaving[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tooltip, setTooltip] = useState<TooltipState>({ weaving: null, x: 0, y: 0 });
  const [activeTab, setActiveTab] = useState<"graph" | "list">("graph");
  const [familyId, setFamilyId] = useState<string>("");

  const load = useCallback(async () => {
    try {
      setLoading(true);
      const fid = familyId || (await resolveFamilyId());
      if (!fid) {
        setError("No family found. Bootstrap the system first at /settings.");
        setLoading(false);
        return;
      }
      if (!familyId) setFamilyId(fid);
      const [gd, wv] = await Promise.all([
        fetchGraph(fid),
        fetchWeavings(fid),
      ]);
      setGraphData(gd);
      setWeavings(wv);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load graph");
    } finally {
      setLoading(false);
    }
  }, [familyId]);

  useEffect(() => { load(); }, [load]);

  // ── D3 render ──────────────────────────────────────────────────────────────
  useEffect(() => {
    if (!graphData || !svgRef.current) return;

    const svg = d3.select(svgRef.current);
    svg.selectAll("*").remove();

    const width = svgRef.current.clientWidth || 800;
    const height = svgRef.current.clientHeight || 500;

    const nodes: (GraphNode & d3.SimulationNodeDatum)[] = graphData.nodes.map((n) => ({ ...n }));
    const nodeById = new Map(nodes.map((n) => [n.id, n]));

    type SimNode = GraphNode & d3.SimulationNodeDatum;
    type SimLink = Omit<GraphEdge, "source" | "target"> &
      d3.SimulationLinkDatum<SimNode> & {
        source: SimNode | string;
        target: SimNode | string;
      };

    const links: SimLink[] = graphData.edges
      .map((e) => ({
        ...e,
        source: (nodeById.get(e.source) ?? e.source) as SimNode | string,
        target: (nodeById.get(e.target) ?? e.target) as SimNode | string,
      }))
      .filter((e) => typeof e.source === "object" && typeof e.target === "object");

    const simulation = d3
      .forceSimulation<SimNode>(nodes)
      .force("link", d3.forceLink<SimNode, SimLink>(links).id((d) => d.id).distance(150))
      .force("charge", d3.forceManyBody().strength(-300))
      .force("center", d3.forceCenter(width / 2, height / 2))
      .force("collision", d3.forceCollide(30));

    const g = svg.append("g");

    // Zoom
    svg.call(
      d3.zoom<SVGSVGElement, unknown>().scaleExtent([0.3, 3]).on("zoom", (event) => {
        g.attr("transform", event.transform);
      })
    );

    // Edges
    const linkEl = g
      .selectAll("line")
      .data(links)
      .enter()
      .append("line")
      .attr("stroke", (d) => d.status === "corrected" ? EDGE_CORRECTED : EDGE_GOLD)
      .attr("stroke-width", (d) => d.status === "confirmed" ? 3 : 2)
      .attr("stroke-dasharray", (d) => d.status === "proposed" ? "8,4" : "none")
      .attr("opacity", (d) => d.status === "corrected" ? 0.4 : 1)
      .style("cursor", "pointer")
      .on("click", (event, d) => {
        const weaving = weavings.find((w) => w.id === d.weaving_id) ?? null;
        if (weaving) {
          setTooltip({ weaving, x: event.clientX, y: event.clientY });
        }
      });

    // Nodes
    const nodeEl = g
      .selectAll("circle")
      .data(nodes)
      .enter()
      .append("circle")
      .attr("r", (d) => (d.heat > 0.7 ? 16 : d.heat > 0.3 ? 12 : 9))
      .attr("fill", (d) => NODE_COLORS[d.type] ?? "#94A3B8")
      .attr("opacity", (d) => (d.heat < 0.3 ? 0.6 : 1))
      .attr("stroke", "#fff")
      .attr("stroke-width", 2)
      .attr("class", (d) => (d.lock_status === "conflict" ? "conflict-node" : ""))
      .style("cursor", "pointer")
      .call(
        d3
          .drag<SVGCircleElement, GraphNode & d3.SimulationNodeDatum>()
          .on("start", (event, d) => {
            if (!event.active) simulation.alphaTarget(0.3).restart();
            d.fx = d.x;
            d.fy = d.y;
          })
          .on("drag", (event, d) => {
            d.fx = event.x;
            d.fy = event.y;
          })
          .on("end", (event, d) => {
            if (!event.active) simulation.alphaTarget(0);
            d.fx = null;
            d.fy = null;
          })
      );

    // Labels
    const labelEl = g
      .selectAll("text.node-label")
      .data(nodes)
      .enter()
      .append("text")
      .attr("class", "node-label")
      .text((d) => d.label.slice(0, 20) + (d.label.length > 20 ? "…" : ""))
      .attr("text-anchor", "middle")
      .attr("dy", (d) => (d.heat > 0.7 ? 28 : d.heat > 0.3 ? 24 : 20))
      .attr("font-size", "11px")
      .attr("fill", "#374151")
      .attr("opacity", (d) => (d.heat < 0.1 ? 0 : 1))
      .style("pointer-events", "none");

    // Trigger icons (🕐 once, 🔁 recurring, 📍 geofence) — top-right of node
    const TRIGGER_EMOJI: Record<string, string> = {
      once: "🕐", recurring: "🔁", geofence: "📍",
    };
    const triggerNodes = nodes.filter(
      (d) => d.trigger_type && d.trigger_type !== "none"
    );
    const triggerEl = g
      .selectAll("text.trigger-icon")
      .data(triggerNodes)
      .enter()
      .append("text")
      .attr("class", "trigger-icon")
      .text((d) => TRIGGER_EMOJI[d.trigger_type!] ?? "")
      .attr("text-anchor", "middle")
      .attr("font-size", "10px")
      .style("pointer-events", "none");

    simulation.on("tick", () => {
      linkEl
        .attr("x1", (d) => (d.source as GraphNode & d3.SimulationNodeDatum).x ?? 0)
        .attr("y1", (d) => (d.source as GraphNode & d3.SimulationNodeDatum).y ?? 0)
        .attr("x2", (d) => (d.target as GraphNode & d3.SimulationNodeDatum).x ?? 0)
        .attr("y2", (d) => (d.target as GraphNode & d3.SimulationNodeDatum).y ?? 0);
      nodeEl.attr("cx", (d) => d.x ?? 0).attr("cy", (d) => d.y ?? 0);
      labelEl.attr("x", (d) => d.x ?? 0).attr("y", (d) => d.y ?? 0);
      // Position trigger icon at top-right of each node
      triggerEl
        .attr("x", (d) => {
          const n = nodes.find((n) => n.id === d.id);
          const r = n && n.heat > 0.7 ? 16 : n && n.heat > 0.3 ? 12 : 9;
          return (n?.x ?? 0) + r + 2;
        })
        .attr("y", (d) => {
          const n = nodes.find((n) => n.id === d.id);
          const r = n && n.heat > 0.7 ? 16 : n && n.heat > 0.3 ? 12 : 9;
          return (n?.y ?? 0) - r + 2;
        });
    });
  }, [graphData, weavings]);

  async function handleConfirmFromTooltip(weavingId: string) {
    await confirmWeaving(weavingId);
    setTooltip({ weaving: null, x: 0, y: 0 });
    await load();
  }

  async function handleCorrectFromTooltip(weavingId: string) {
    await correctWeaving(weavingId, familyId);
    setTooltip({ weaving: null, x: 0, y: 0 });
    await load();
  }

  return (
    <div style={{ display: "flex", flexDirection: "column", height: "100%", padding: "1.5rem" }}>
      <style>{`
        @keyframes conflict-pulse {
          0%, 100% { transform: scale(0.95); }
          50% { transform: scale(1.05); }
        }
        .conflict-node { animation: conflict-pulse 2s ease-in-out infinite; transform-origin: center; transform-box: fill-box; }
      `}</style>
      {/* Header */}
      <div style={{ display: "flex", alignItems: "center", gap: "1rem", marginBottom: "1rem" }}>
        <h2 style={{ margin: 0, fontSize: "1.2rem", color: "#1F2937" }}>Knowledge Graph</h2>
        <button
          onClick={load}
          style={{
            padding: "0.3rem 0.8rem", fontSize: "0.8rem", border: "1px solid #D1D5DB",
            borderRadius: 4, cursor: "pointer", background: "none", color: "#6B7280",
          }}
        >
          Refresh
        </button>
        <div style={{ marginLeft: "auto", display: "flex", gap: "0.5rem" }}>
          {(["graph", "list"] as const).map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{
                padding: "0.3rem 0.8rem", fontSize: "0.8rem", borderRadius: 4, cursor: "pointer",
                border: "1px solid #D1D5DB",
                background: activeTab === tab ? "#F59E0B" : "none",
                color: activeTab === tab ? "#fff" : "#6B7280",
                fontWeight: activeTab === tab ? 600 : 400,
              }}
            >
              {tab === "graph" ? "Graph" : "Weavings"}
            </button>
          ))}
        </div>
      </div>

      {/* Legend */}
      {activeTab === "graph" && (
        <div style={{ display: "flex", gap: "1rem", fontSize: "0.78rem", color: "#6B7280", marginBottom: "0.75rem" }}>
          <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: "#F59E0B", marginRight: 4 }} />Thread</span>
          <span><span style={{ display: "inline-block", width: 10, height: 10, borderRadius: "50%", background: "#3B82F6", marginRight: 4 }} />Expense</span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#F59E0B" strokeWidth="2" strokeDasharray="6,3" /></svg>
            Proposed
          </span>
          <span style={{ display: "flex", alignItems: "center", gap: 4 }}>
            <svg width="24" height="8"><line x1="0" y1="4" x2="24" y2="4" stroke="#F59E0B" strokeWidth="3" /></svg>
            Confirmed
          </span>
          <span>🕐 Once &nbsp; 🔁 Recurring &nbsp; 📍 Geofence</span>
          <span style={{ marginLeft: "auto", color: "#94A3B8" }}>Click an edge to confirm/disconnect</span>
        </div>
      )}

      {/* Content */}
      {loading && <div style={{ color: "#9CA3AF", padding: "2rem", textAlign: "center" }}>Loading graph…</div>}
      {error && <div style={{ color: "#EF4444", padding: "1rem" }}>{error}</div>}

      {!loading && !error && (
        <>
          {activeTab === "graph" ? (
            <div style={{ flex: 1, border: "1px solid #E5E7EB", borderRadius: 8, overflow: "hidden", background: "#F9FAFB", position: "relative" }}>
              {graphData && graphData.nodes.length === 0 ? (
                <div style={{ display: "flex", alignItems: "center", justifyContent: "center", height: "100%", color: "#9CA3AF" }}>
                  No nodes yet — send a WhatsApp thread or add an OurCents expense to see the graph populate.
                </div>
              ) : (
                <svg ref={svgRef} width="100%" height="100%" style={{ minHeight: 460 }} />
              )}
            </div>
          ) : (
            <div style={{ flex: 1, overflowY: "auto" }}>
              <WeavingsPanel weavings={weavings} familyId={familyId} onUpdate={load} />
            </div>
          )}
        </>
      )}

      {/* Edge tooltip */}
      {tooltip.weaving && (
        <>
          <div
            onClick={() => setTooltip({ weaving: null, x: 0, y: 0 })}
            style={{ position: "fixed", inset: 0, zIndex: 99 }}
          />
          <div
            style={{
              position: "fixed",
              left: Math.min(tooltip.x + 8, window.innerWidth - 260),
              top: Math.min(tooltip.y + 8, window.innerHeight - 160),
              zIndex: 100,
              background: "#fff",
              border: "1px solid #E5E7EB",
              borderRadius: 8,
              boxShadow: "0 4px 16px rgba(0,0,0,0.12)",
              padding: "0.75rem 1rem",
              minWidth: 240,
            }}
          >
            <div style={{ fontWeight: 600, fontSize: "0.9rem", marginBottom: "0.4rem", color: "#1F2937" }}>
              {tooltip.weaving.title ?? "Weaving"}
            </div>
            <div style={{ fontSize: "0.78rem", color: "#6B7280", marginBottom: "0.6rem" }}>
              Similarity: {((tooltip.weaving.fact_cosine ?? 0) * 100).toFixed(0)}% · Status: {tooltip.weaving.status}
            </div>
            {tooltip.weaving.status === "proposed" && (
              <div style={{ display: "flex", gap: "0.5rem" }}>
                <button
                  onClick={() => handleConfirmFromTooltip(tooltip.weaving!.id)}
                  style={{
                    flex: 1, padding: "0.35rem", fontSize: "0.8rem",
                    background: "#F59E0B", color: "#fff", border: "none",
                    borderRadius: 4, cursor: "pointer", fontWeight: 600,
                  }}
                >
                  Confirm
                </button>
                <button
                  onClick={() => handleCorrectFromTooltip(tooltip.weaving!.id)}
                  style={{
                    flex: 1, padding: "0.35rem", fontSize: "0.8rem",
                    background: "none", color: "#6B7280", border: "1px solid #D1D5DB",
                    borderRadius: 4, cursor: "pointer",
                  }}
                >
                  Disconnect
                </button>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
