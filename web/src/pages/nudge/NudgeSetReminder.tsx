import { useEffect, useReducer, useState } from "react";
import { NudgeInput } from "./NudgeInput";
import { ParsePreview } from "./ParsePreview";
import { parseReminder, saveReminder } from "../../lib/api/nudge";
import { listPhoneBindings } from "../../lib/api/ourcents";
import type { ParseResponse, Reminder, ReminderCreate } from "../../lib/types/nudge";

type Phase = "idle" | "parsing" | "confirming" | "saving" | "done" | "error";

interface State {
  phase: Phase;
  parseResult: ParseResponse | null;
  lastSaved: Reminder | null;
  error: string | null;
}

type Action =
  | { type: "PARSE_START" }
  | { type: "PARSE_SUCCESS"; payload: ParseResponse }
  | { type: "PARSE_ERROR"; payload: string }
  | { type: "CANCEL" }
  | { type: "SAVE_START" }
  | { type: "SAVE_SUCCESS"; payload: Reminder };

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case "PARSE_START": return { ...state, phase: "parsing", error: null };
    case "PARSE_SUCCESS": return { ...state, phase: "confirming", parseResult: action.payload };
    case "PARSE_ERROR": return { ...state, phase: "error", error: action.payload };
    case "CANCEL": return { ...state, phase: "idle", parseResult: null, error: null };
    case "SAVE_START": return { ...state, phase: "saving" };
    case "SAVE_SUCCESS": return { ...state, phase: "done", parseResult: null, lastSaved: action.payload };
    default: return state;
  }
}

export default function NudgeSetReminder() {
  const [state, dispatch] = useReducer(reducer, { phase: "idle", parseResult: null, lastSaved: null, error: null });
  const [boundPhone, setBoundPhone] = useState<string | null>(null);

  useEffect(() => {
    listPhoneBindings()
      .then((bindings) => { if (bindings.length > 0) setBoundPhone(bindings[0].phone); })
      .catch(() => {});
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
      const payload = boundPhone ? { ...data, triggerSource: boundPhone } : data;
      const saved = await saveReminder(payload);
      dispatch({ type: "SAVE_SUCCESS", payload: saved });
    } catch (e) { dispatch({ type: "PARSE_ERROR", payload: String(e) }); }
  }

  return (
    <div style={{ padding: "1.5rem" }}>
      <div style={{ maxWidth: 560, display: "flex", flexDirection: "column", gap: 20 }}>
        <div>
          <h2 style={{ margin: 0 }}>Set Reminder</h2>
          <p style={{ margin: "4px 0 0", color: "#6b7280", fontSize: 14 }}>
            Create a reminder in natural language
            {boundPhone && <span style={{ marginLeft: 8, color: "#6366f1" }}>· alerts → {boundPhone}</span>}
          </p>
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

        {state.phase === "done" && state.lastSaved && (
          <div style={{ background: "#f0fdf4", border: "1px solid #86efac", borderRadius: 8, padding: "10px 14px", fontSize: 13, color: "#166534", display: "flex", justifyContent: "space-between", alignItems: "center" }}>
            <span>Reminder "{state.lastSaved.title}" saved!</span>
            <button onClick={() => dispatch({ type: "CANCEL" })} style={{ background: "none", border: "none", cursor: "pointer", fontSize: 18, color: "#166534" }}>×</button>
          </div>
        )}
      </div>
    </div>
  );
}
