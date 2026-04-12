import { WaConnection } from "../../lib/api/gateway";

type ConnectionPanelProps = {
  connections: WaConnection[];
  onCreateConnection: () => void;
  onDeleteConnection: (id: number) => void;
};

export function ConnectionPanel({ connections, onCreateConnection, onDeleteConnection }: ConnectionPanelProps) {
  return (
    <section className="connections-panel">
      <div className="connections-header">
        <p className="eyebrow">WhatsApp Connections</p>
        <button className="add-connection-btn" onClick={onCreateConnection} title="Add WhatsApp connection">
          + Add
        </button>
      </div>

      {connections.length === 0 ? (
        <p className="muted connections-empty">No connections yet. Click Add to connect a WhatsApp account.</p>
      ) : (
        <ul className="connection-list">
          {connections.map((conn) => (
            <li key={conn.id} className={`connection-item ${conn.status === "connected" ? "connected" : ""}`}>
              <div className="connection-item-main">
                <div className="connection-item-info">
                  {conn.status === "connected" ? (
                    <>
                      <span className="connection-dot connected-dot" />
                      <span className="connection-label">
                        {conn.connected_name || conn.label || conn.bridge_session_id.slice(0, 8)}
                        {conn.connected_phone ? <small> · {conn.connected_phone}</small> : null}
                      </span>
                    </>
                  ) : (
                    <>
                      <span className="connection-dot" />
                      <span className="connection-label">
                        {conn.label || conn.bridge_session_id.slice(0, 8)}
                        <small> · {conn.status}</small>
                      </span>
                    </>
                  )}
                </div>
                <button
                  className="connection-delete-btn"
                  onClick={() => onDeleteConnection(conn.id)}
                  title="Remove connection"
                >
                  ✕
                </button>
              </div>

              {conn.qr_code_data_url ? (
                <div className="connection-qr">
                  <p className="muted">Scan with WhatsApp → Linked Devices</p>
                  <img className="qr-image" src={conn.qr_code_data_url} alt="WhatsApp QR code" />
                </div>
              ) : null}

              {conn.last_error && conn.status !== "connected" ? (
                <p className="error-text">{conn.last_error}</p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}