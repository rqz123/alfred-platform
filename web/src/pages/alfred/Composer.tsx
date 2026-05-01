import { FormEvent, useRef, useState } from "react";

type ComposerProps = {
  disabled?: boolean;
  onSend: (body: string, options: { sendAsVoice: boolean }) => Promise<void>;
  onSendImage: (file: File) => Promise<void>;
  onClear: () => Promise<void>;
};

export function Composer({ disabled, onSend, onSendImage, onClear }: ComposerProps) {
  const [body, setBody] = useState("");
  const [sending, setSending] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [sendAsVoice, setSendAsVoice] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!body.trim()) {
      return;
    }

    setSending(true);
    try {
      await onSend(body.trim(), { sendAsVoice });
      setBody("");
    } finally {
      setSending(false);
    }
  }

  async function handleClear() {
    setClearing(true);
    try {
      await onClear();
    } finally {
      setClearing(false);
    }
  }

  async function handleImageChange(event: React.ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";
    setSending(true);
    try {
      await onSendImage(file);
    } finally {
      setSending(false);
    }
  }

  return (
    <form className="composer" onSubmit={handleSubmit}>
      <input
        placeholder="Reply to the conversation"
        value={body}
        onChange={(event) => setBody(event.target.value)}
        disabled={disabled || sending}
      />
      <div className="composer-actions">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          style={{ display: "none" }}
          onChange={handleImageChange}
        />
        <button
          type="button"
          className={`secondary-button image-btn${sendAsVoice ? " voice-active" : ""}`}
          title="Send as voice"
          onClick={() => setSendAsVoice((v) => !v)}
          disabled={disabled || sending}
        >
          🎤
        </button>
        <button
          type="button"
          className="secondary-button image-btn"
          title="Send image"
          onClick={() => fileInputRef.current?.click()}
          disabled={disabled || sending}
        >
          🖼
        </button>
        <button type="button" className="secondary-button" onClick={handleClear} disabled={disabled || clearing}>
          {clearing ? "Clearing..." : "Clear"}
        </button>
        <button type="submit" disabled={disabled || sending}>
          {sending ? "Sending..." : sendAsVoice ? "Send Voice" : "Send"}
        </button>
      </div>
    </form>
  );
}