import { useState } from "react";
import { ApiError, api, getStoredToken, storeToken } from "../api/client";
import { useToast } from "../components/Toast";

export function SettingsPage() {
  const { showToast } = useToast();
  const [token, setToken] = useState(getStoredToken());
  const [checking, setChecking] = useState(false);
  const [health, setHealth] = useState<{ version: string; database: string } | null>(null);
  const [healthError, setHealthError] = useState<string | null>(null);

  const save = async () => {
    storeToken(token.trim());
    showToast("Token saved", "success");
    await check();
  };

  const check = async () => {
    setChecking(true);
    setHealthError(null);
    try {
      const status = await api.health();
      setHealth(status);
      // Verify the stored token actually grants management access.
      try {
        await api.listEndpoints();
        showToast("Admin token works ✓", "success");
      } catch (caught) {
        if (caught instanceof ApiError && caught.status === 401) {
          showToast("Backend reachable, but the token was rejected (401)", "error");
        } else {
          throw caught;
        }
      }
    } catch (caught) {
      setHealth(null);
      setHealthError(caught instanceof Error ? caught.message : "Health check failed");
    } finally {
      setChecking(false);
    }
  };

  return (
    <>
      <div className="page-title">
        <h1>Settings</h1>
      </div>

      <div className="panel panel-pad" style={{ maxWidth: 640 }}>
        <h2 className="section-title">Admin API token</h2>
        <p className="count-note">
          The management API is protected by the server's <code>ADMIN_API_TOKEN</code>. Paste it
          here once; it is stored in this browser's local storage and sent as a Bearer token.
        </p>
        <div className="field" style={{ marginTop: 10 }}>
          <label htmlFor="token-input">Token</label>
          <input
            id="token-input"
            type="password"
            autoComplete="off"
            value={token}
            placeholder="paste ADMIN_API_TOKEN"
            onChange={(event) => setToken(event.target.value)}
          />
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn btn-primary" onClick={() => void save()}>
            Save & verify
          </button>
          <button type="button" className="btn" onClick={() => void check()} disabled={checking}>
            {checking ? "Checking…" : "Test connection"}
          </button>
        </div>
        <div style={{ marginTop: 14 }} className="count-note">
          {healthError !== null ? (
            <span style={{ color: "var(--err)" }}>Backend: {healthError}</span>
          ) : health !== null ? (
            <span style={{ color: "var(--ok)" }}>
              Backend v{health.version} — database {health.database}
            </span>
          ) : (
            <span>Connection status appears here.</span>
          )}
        </div>
      </div>

      <div className="panel panel-pad" style={{ maxWidth: 640, marginTop: 16 }}>
        <h2 className="section-title">About this tool</h2>
        <ul style={{ margin: 0, paddingLeft: 18, color: "var(--muted)", fontSize: 13 }}>
          <li>Webhook bodies are treated as untrusted input and are always rendered as text.</li>
          <li>Replay targets must be HTTPS; private networks and metadata IPs are blocked.</li>
          <li>
            Replay triggers <strong>real outbound HTTP requests</strong> — point it at test
            receivers, not production services.
          </li>
          <li>Data auto-expires via endpoint TTL and the cleanup worker.</li>
        </ul>
      </div>
    </>
  );
}
