import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { LoginForm } from "../components/auth/LoginForm";
import { login as gatewayLogin } from "../lib/api/gateway";

export default function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(creds: { username: string; password: string }) {
    setError(null);
    try {
      const result = await gatewayLogin(creds);
      localStorage.setItem("alfred_token", result.access_token);
      localStorage.setItem("alfred_user", JSON.stringify(result));
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
