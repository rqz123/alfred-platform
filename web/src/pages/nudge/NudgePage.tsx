/**
 * Nudge page — contains all state logic from the original Nudge App.tsx.
 */

import { useEffect, useReducer } from "react";
import { NudgeInput } from "./NudgeInput";
import { ParsePreview } from "./ParsePreview";
import { ReminderList } from "./ReminderList";
import { listReminders, parseReminder, saveReminder } from "../../lib/api/nudge";
import type { ParseResponse, Reminder, ReminderCreate } from "../../lib/types/nudge";

type Phase = "idle" | "parsing" | "confirming" | "saving" | "error";

interface State {
  phase: Phase;
  parseResult: ParseResponse | null;
  reminders: Reminder[];
  error: string | null;
}

type Action =
  | { type: "PARSE_START" }
  | { type: "PARSE_SUCCESS"; payload: ParseResponse }
  | { type: "PARSE_ERROR"; payload: string }
  | { type: "CANCEL" }
  | { type: "SAVE_START" }
  | { type: "SAVE_SUCCESS"; payload: Reminder }
  | { type: "LOAD_REMINDERS"; payload: Reminder[] };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "PARSE_START": return { ...state, phase: "parsing", error: null };
    case "PARSE_SUCCESS": return { ...state, phase: "confirming", parseResult: action.payload };
    case "PARSE_ERROR": return { ...state, phase: "error", error: action.payload };
    case "CANCEL": return { ...state, phase: "idle", parseResult: null, error: null };
    case "SAVE_START": return { ...state, phase: "saving" };
    case "SAVE_SUCCESS": return { ...state, phase: "idle", parseResult: null, reminders: [action.payload, ...state.reminders] };
    case "LOAD_REMINDERS": return { ...state, reminders: action.payload };
    default: return state;
  }
}

export default function NudgePage() {
  const [state, dispatch] = useReducer(reducer, { phase: "idle", parseResult: null, reminders: [], error: null });

  useEffect(() => {
    listReminders()
      .then((data) => dispatch({ type: "LOAD_REMINDERS", payload: data }))
      .catch(() => {/* silently ignore — token may not be set yet */});
  }, []);

  async function handleParse(input: string, timezone: string) {
    dispatch({ type: "PARSE_START" });
    try {
      const result = await parseReminder(input, timezone);
      dispatch({ type: "PARSE_SUCCESS", payload: result });
    } catch (e) { dispatch({ type: "PARSE_ERROR", payload: String(e) }); }
  }

  async function handleSave(data: ReminderCreate) {
    dispatch({ type: "SAVE_START" });
    try {
      const saved = await saveReminder(data);
      dispatch({ type: "SAVE_SUCCESS", payload: saved });
    } catch (e) { dispatch({ type: "PARSE_ERROR", payload: String(e) }); }
  }

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h2 style={{ margin: 0 }}>Nudge</h2>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>Create reminders in natural language</p>
        </div>

        <NudgeInput onParse={handleParse} loading={state.phase === "parsing"} />

        {state.phase === "error" && state.error && (
          <div style={{ background: "#fef2f2", border: "1px solid #fca5a5", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#991b1b", display: "flex", justifyContent: "space-between" }}>
            {state.error}
            <button onClick={() => dispatch({ type: "CANCEL" })} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "#991b1b" }}>×</button>
          </div>
        )}

        {(state.phase === "confirming" || state.phase === "saving") && state.parseResult && (
          <ParsePreview
            result={state.parseResult}
            onConfirm={handleSave}
            onCancel={() => dispatch({ type: "CANCEL" })}
            saving={state.phase === "saving"}
          />
        )}

        <div>
          <h3 style={{ margin: "0 0 10px", fontSize: 16, fontWeight: 600, color: "#374151" }}>My Reminders</h3>
          <ReminderList reminders={state.reminders} />
        </div>
      </div>
    </div>
  );
}
