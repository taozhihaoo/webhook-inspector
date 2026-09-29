import { formatDateTime, formatDuration, statusClass } from "../lib/format";
import type { AuthCheck, ReplayRecord, SignatureCheck } from "../api/types";

export function MethodBadge({ method }: { method: string }) {
  const known = ["GET", "POST", "PUT", "PATCH", "DELETE"];
  const cls = known.includes(method) ? `badge-${method.toLowerCase()}` : "badge-other";
  return <span className={`badge ${cls}`}>{method}</span>;
}

export function StatusPill({ status }: { status: number | null }) {
  return <span className={`status-pill ${statusClass(status)}`}>{status ?? "ERR"}</span>;
}

const SIGNATURE_META: Record<SignatureCheck, { label: string; cls: string }> = {
  verified: { label: "✓ signature verified", cls: "chip-ok" },
  invalid: { label: "✕ signature invalid", cls: "chip-err" },
  not_configured: { label: "signature off", cls: "chip-muted" },
  error: { label: "! signature error", cls: "chip-warn" },
};

export function SignatureChip({ status }: { status: SignatureCheck }) {
  const meta = SIGNATURE_META[status];
  return <span className={`chip ${meta.cls}`}>{meta.label}</span>;
}

const AUTH_META: Record<AuthCheck, { label: string; cls: string }> = {
  valid: { label: "✓ token valid", cls: "chip-ok" },
  invalid: { label: "✕ token invalid", cls: "chip-err" },
  not_configured: { label: "no ingest token", cls: "chip-muted" },
};

export function AuthChip({ status }: { status: AuthCheck }) {
  const meta = AUTH_META[status];
  return <span className={`chip ${meta.cls}`}>{meta.label}</span>;
}

const REPLAY_META: Record<ReplayRecord["status"], { label: string; cls: string }> = {
  success: { label: "success", cls: "chip-ok" },
  error: { label: "error", cls: "chip-err" },
  blocked: { label: "blocked (SSRF guard)", cls: "chip-warn" },
  timeout: { label: "timeout", cls: "chip-warn" },
};

export function ReplayStatusChip({ status }: { status: ReplayRecord["status"] }) {
  const meta = REPLAY_META[status];
  return <span className={`chip ${meta.cls}`}>{meta.label}</span>;
}

export function ReplayResultCard({ record }: { record: ReplayRecord }) {
  return (
    <div className="panel panel-pad" style={{ marginTop: 12 }}>
      <div
        style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}
      >
        <ReplayStatusChip status={record.status} />
        {record.response_status !== null && <StatusPill status={record.response_status} />}
        {record.duration_ms !== null && (
          <span className="count-note mono">{formatDuration(record.duration_ms)}</span>
        )}
        <span className="count-note mono">{formatDateTime(record.created_at)}</span>
        <span className="count-note" style={{ marginLeft: "auto", overflowWrap: "anywhere" }}>
          → <code>{record.target_url}</code>
        </span>
      </div>
      {record.error_message !== null && (
        <p className="inline-error" style={{ marginBottom: 0 }}>
          {record.error_message}
        </p>
      )}
      {record.response_headers !== null && Object.keys(record.response_headers).length > 0 && (
        <details style={{ marginTop: 10 }}>
          <summary style={{ cursor: "pointer", color: "var(--muted)", fontSize: 12 }}>
            Response headers
          </summary>
          <pre
            className="mono"
            style={{ fontSize: 12, overflowX: "auto", margin: "8px 0 0" }}
          >
            {Object.entries(record.response_headers)
              .map(([name, value]) => `${name}: ${value}`)
              .join("\n")}
          </pre>
        </details>
      )}
      {record.response_body_preview !== null && (
        <details style={{ marginTop: 8 }} open>
          <summary style={{ cursor: "pointer", color: "var(--muted)", fontSize: 12 }}>
            Response body (preview)
          </summary>
          <pre className="mono" style={{ fontSize: 12, overflowX: "auto", margin: "8px 0 0" }}>
            {record.response_body_preview}
          </pre>
        </details>
      )}
    </div>
  );
}
