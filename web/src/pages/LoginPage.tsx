import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LoginForm } from "../components/auth/LoginForm";
import { login as gatewayLogin } from "../lib/api/gateway";
import { login as ourcentsLogin, register as ourcentsRegister } from "../lib/api/ourcents";

export default function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(creds: { username: string; password: string }) {
    setError(null);
    try {
      // Try gateway login first
      const result = await gatewayLogin(creds);
      localStorage.setItem("alfred_token", result.access_token);
      localStorage.setItem("alfred_user", JSON.stringify(result));
      // Auto-provision OurCents account with the same credentials
      await ourcentsRegister(creds.username, creds.username, creds.password).catch(() => {});
      await ourcentsLogin(creds.username, creds.password).catch(() => {});
      navigate("/alfred");
      return;
    } catch {
      // gateway auth failed — try OurCents auth
    }

    try {
      await ourcentsLogin(creds.username, creds.password);
      navigate("/ourcents/dashboard");
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
