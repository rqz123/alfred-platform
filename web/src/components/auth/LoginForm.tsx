import { FormEvent, useState } from "react";

type LoginFormProps = {
  onSubmit: (credentials: { username: string; password: string }) => Promise<void>;
  error: string | null;
};

export function LoginForm({ onSubmit, error }: LoginFormProps) {
  const [username, setUsername] = useState("admin");
  const [password, setPassword] = useState("admin123");
  const [submitting, setSubmitting] = useState(false);

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({ username, password });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form className="login-card" onSubmit={handleSubmit}>
      <div>
        <p className="eyebrow">Alfred</p>
        <h1>Admin Sign In</h1>
        <p className="muted">Use the single administrator account to manage WhatsApp conversations.</p>
      </div>
      <label>
        Username
        <input value={username} onChange={(event) => setUsername(event.target.value)} />
      </label>
      <label>
        Password
        <input
          type="password"
          value={password}
          onChange={(event) => setPassword(event.target.value)}
        />
      </label>
      {error ? <p className="error-text">{error}</p> : null}
      <button type="submit" disabled={submitting}>
        {submitting ? "Signing in..." : "Sign In"}
      </button>
    </form>
  );
}