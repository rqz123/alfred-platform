export type NodeType = "thread" | "expense" | "reminder";
export type WeavingStatus = "proposed" | "confirmed" | "corrected";

export interface GraphNode {
  id: string;
  type: NodeType;
  label: string;
  heat: number;
  urgency: number;
  social_bond: number;
  goal_alignment: number;
  created_at: string;
  family_id: string;
  trigger_type?: "none" | "once" | "recurring" | "geofence" | null;
  lock_status?: string | null;
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: "cross_skill";
  weight: number;
  status: WeavingStatus;
  weaving_id: string;
}

export interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
  family_id: string;
  generated_at: string;
}

export interface Weaving {
  id: string;
  family_id: string;
  title: string | null;
  source_thread_id: string | null;
  source_expense_id: string | null;
  fact_cosine: number | null;
  status: WeavingStatus;
  created_at: string;
  confirmed_at: string | null;
}
