import { useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { getHealth } from "../api/client";
import { ApiResponseError, UnauthorizedError } from "../api/client";

export function LoginForm() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [tokenInput, setTokenInput] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [isVerifying, setIsVerifying] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    const trimmed = tokenInput.trim();
    if (!trimmed) {
      setError("Token cannot be empty.");
      return;
    }

    setError(null);
    setIsVerifying(true);

    // Verify token by making a health check call
    try {
      // First try /health (public, doesn't need token)
      // Then try /orders (protected) to verify token works
      const res = await fetch("/orders", {
        headers: { Authorization: `Bearer ${trimmed}` },
      });

      if (res.status === 401) {
        throw new UnauthorizedError();
      }

      if (!res.ok) {
        throw new ApiResponseError(res.status, res.statusText);
      }

      // Token is valid
      login(trimmed);
      navigate("/");
    } catch (err) {
      if (err instanceof UnauthorizedError) {
        setError("Invalid token. The server rejected the authorization.");
      } else if (err instanceof ApiResponseError) {
        setError(`Server error: ${err.detail}`);
      } else {
        setError("Cannot connect to server. Is the API running?");
      }
    } finally {
      setIsVerifying(false);
    }
  }

  return (
    <div
      style={{
        display: "flex",
        justifyContent: "center",
        alignItems: "center",
        minHeight: "100vh",
        padding: "1rem",
      }}
    >
      <article
        style={{
          maxWidth: "420px",
          width: "100%",
        }}
      >
        <hgroup>
          <h1>🛡️ Admin UI</h1>
          <h2>Inspection Dashboard</h2>
        </hgroup>

        <p style={{ fontSize: "0.9rem", color: "var(--text-muted)" }}>
          Enter your <code>INSPECTION_API_TOKEN</code> to access the dashboard.
          This token is stored in your session only and cleared on logout or tab
          close.
        </p>

        {error && (
          <div
            style={{
              padding: "0.5rem 0.75rem",
              marginBottom: "1rem",
              backgroundColor: "#dc2626",
              color: "#fff",
              borderRadius: "4px",
              fontSize: "0.85rem",
            }}
          >
            ⚠ {error}
          </div>
        )}

        <form onSubmit={handleSubmit}>
          <input
            type="password"
            placeholder="Bearer token"
            value={tokenInput}
            onChange={(e) => setTokenInput(e.target.value)}
            autoFocus
            aria-label="Token"
          />
          <button
            type="submit"
            disabled={isVerifying || !tokenInput.trim()}
            aria-busy={isVerifying}
          >
            {isVerifying ? "Verifying..." : "Enter Dashboard"}
          </button>
        </form>
      </article>
    </div>
  );
}
