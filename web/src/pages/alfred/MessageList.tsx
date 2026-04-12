import { useEffect, useRef } from "react";
import { Message } from "../../lib/api/gateway";

const BACKEND_ORIGIN = `${window.location.protocol}//${window.location.hostname}:8000`;

function resolveMediaUrl(url: string | null | undefined): string | null {
  if (!url) return null;
  if (url.startsWith("/api/media/")) return `${BACKEND_ORIGIN}${url}`;
  return url;
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

const STATUS_ICON: Record<string, string> = {
  queued: "🕐",
  sent: "✓",
  delivered: "✓✓",
  read: "✓✓",
  failed: "!",
};

type MessageListProps = {
  messages: Message[];
};

export function MessageList({ messages }: MessageListProps) {
  const bottomRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  return (
    <div className="message-list">
      {messages.map((message) => {
        const isOut = message.direction === "outbound";
        const statusIcon = isOut ? (STATUS_ICON[message.delivery_status] ?? "") : null;
        const isRead = message.delivery_status === "read";

        return (
          <div key={message.id} className={`bubble-row ${isOut ? "bubble-row--out" : "bubble-row--in"}`}>
            <div className={`bubble ${isOut ? "bubble--out" : "bubble--in"} bubble--${message.message_type}`}>

              {/* IMAGE */}
              {message.message_type === "image" && message.media_url ? (
                <img
                  className="bubble-image"
                  src={resolveMediaUrl(message.media_url)!}
                  alt="Image"
                />
              ) : message.message_type === "image" ? (
                <span className="bubble-media-placeholder">📷 Image (unavailable)</span>
              ) : null}

              {/* AUDIO / VOICE */}
              {(message.message_type === "audio" || message.message_type === "ptt") && message.media_url ? (
                <div className="bubble-audio">
                  <span className="bubble-audio-icon">🎵</span>
                  <audio controls src={resolveMediaUrl(message.media_url)!} className="bubble-audio-player" />
                </div>
              ) : (message.message_type === "audio" || message.message_type === "ptt") && !message.media_url ? (
                <span className="bubble-media-placeholder">🎵 Voice message (unavailable)</span>
              ) : null}

              {/* TEXT BODY */}
              {message.body ? (
                <p className="bubble-text">{message.body}</p>
              ) : message.message_type === "text" ? (
                <p className="bubble-text bubble-text--muted">Unsupported message</p>
              ) : null}

              {/* TRANSCRIPT */}
              {message.transcript && message.message_type !== "text" ? (
                <p className="bubble-transcript">"{message.transcript}"</p>
              ) : null}

              {/* META ROW */}
              <div className="bubble-meta">
                <span className="bubble-time">{formatTime(message.created_at)}</span>
                {statusIcon ? (
                  <span className={`bubble-status ${isRead ? "bubble-status--read" : ""} ${message.delivery_status === "failed" ? "bubble-status--failed" : ""}`}>
                    {statusIcon}
                  </span>
                ) : null}
              </div>
            </div>
          </div>
        );
      })}
      <div ref={bottomRef} />
    </div>
  );
}
