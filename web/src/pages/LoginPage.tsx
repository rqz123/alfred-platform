import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LoginForm } from "../components/auth/LoginForm";
import { login as gatewayLogin } from "../lib/api/gateway";
import { register as ourcentsRegister, login as ourcentsLogin } from "../lib/api/ourcents";

export default function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(creds: { username: string; password: string }) {
    setError(null);
    try {
      const result = await gatewayLogin(creds);
      localStorage.setItem("alfred_token", result.access_token);
      localStorage.setItem("alfred_user", JSON.stringify(result));

      // Auto-login to OurCents with the same credentials.
      // register() is a no-op if already registered.
      try {
        await ourcentsRegister(creds.username, creds.username, creds.password);
        await ourcentsLogin(creds.username, creds.password);
      } catch {
        // OurCents unavailable — main app still works
      }

      navigate("/alfred");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Login failed");
    }
  }

  return (
    <main className="login-shell">
      <LoginForm onSubmit={handleSubmit} error={error} />
    </main>
  );
}
