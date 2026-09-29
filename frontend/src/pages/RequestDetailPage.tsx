import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Endpoint, RequestDetail } from "../api/types";
import { AuthChip, MethodBadge, SignatureChip, StatusPill } from "../components/Badges";
import { CopyButton } from "../components/CopyButton";
import { ConfirmDialog } from "../components/Modal";
import { HeadersTable, ReplayPanel } from "../components/ReplayPanel";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useToast } from "../components/Toast";
import { formatBytes, formatDateTime, formatDuration } from "../lib/format";
import { JsonViewer } from "../components/JsonViewer";

type Tab = "overview" | "headers" | "query" | "body" | "response" | "replay";

const TABS: Array<{ id: Tab; label: string }> = [
  { id: "overview", label: "Overview" },
  { id: "headers", label: "Headers" },
  { id: "query", label: "Query" },
  { id: "body", label: "Body" },
  { id: "response", label: "Response" },
  { id: "replay", label: "Replay" },
];

export function RequestDetailPage() {
  const { requestId } = useParams<{ requestId: string }>();
  const id = Number(requestId);
  const navigate = useNavigate();
  const { showToast, showError } = useToast();
  const [request, setRequest] = useState<RequestDetail | null>(null);
  const [endpoint, setEndpoint] = useState<Endpoint | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("overview");
  const [bodyView, setBodyView] = useState<"formatted" | "raw">("formatted");
  const [confirmDelete, setConfirmDelete] = useState(false);

  const load = useCallback(async () => {
    try {
      const detail = await api.getRequest(id);
      setRequest(detail);
      setError(null);
      void api.getEndpoint(detail.endpoint_id).then(setEndpoint).catch(() => setEndpoint(null));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to load request.");
    }
  }, [id]);

  useEffect(() => {
    void load();
  }, [load]);

  if (error !== null) {
    return (
      <>
        <ErrorState message={error} />
        <p style={{ textAlign: "center" }}>
          <Link to="/">← Back to dashboard</Link>
        </p>
      </>
    );
  }
  if (!Number.isFinite(id) || request === null) {
    return <LoadingState />;
  }

  const bodyIsJson = request.body_json !== null && request.body_json !== undefined;

  const remove = async () => {
    try {
      await api.deleteRequest(id);
      showToast("Request deleted", "success");
      void navigate(`/endpoints/${request.endpoint_id}`);
    } catch (caught) {
      showError(caught);
    }
  };

  return (
    <>
      <div className="page-title">
        <h1 style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <MethodBadge method={request.method} />
          <span className="mono" style={{ fontSize: 16 }}>
            {request.path}
          </span>
        </h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn" onClick={() => void load()}>
            ⟳ Refresh
          </button>
          <Link className="btn" to={`/endpoints/${request.endpoint_id}`}>
            ← Endpoint
          </Link>
          <button
            type="button"
            className="btn btn-danger"
            onClick={() => setConfirmDelete(true)}
          >
            Delete request
          </button>
        </div>
      </div>

      <div className="panel">
        <div className="tabs" role="tablist">
          {TABS.map((entry) => (
            <button
              key={entry.id}
              type="button"
              role="tab"
              aria-selected={tab === entry.id}
              className={tab === entry.id ? "active" : ""}
              onClick={() => setTab(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div className="panel-pad">
          {tab === "overview" && (
            <div className="meta-grid">
              <div className="meta-item">
                <span className="k">Request ID</span>
                <span className="v mono">
                  {request.id} <CopyButton value={String(request.id)} label="Copy ID" />
                </span>
              </div>
              <div className="meta-item">
                <span className="k">Received at</span>
                <span className="v">{formatDateTime(request.received_at)}</span>
              </div>
              <div className="meta-item">
                <span className="k">Method</span>
                <span className="v">
                  <MethodBadge method={request.method} />
                </span>
              </div>
              <div className="meta-item">
                <span className="k">Path</span>
                <span className="v mono">{request.path}</span>
              </div>
              <div className="meta-item">
                <span className="k">Content type</span>
                <span className="v mono">{request.content_type ?? "—"}</span>
              </div>
              <div className="meta-item">
                <span className="k">Body size</span>
                <span className="v mono">{formatBytes(request.body_size)}</span>
              </div>
              <div className="meta-item">
                <span className="k">Processing time</span>
                <span className="v mono">{formatDuration(request.processing_duration_ms)}</span>
              </div>
              <div className="meta-item">
                <span className="k">Source IP</span>
                <span className="v mono">{request.source_ip ?? "—"}</span>
              </div>
              <div className="meta-item">
                <span className="k">Signature</span>
                <span className="v">
                  <SignatureChip status={request.signature_status} />
                </span>
              </div>
              <div className="meta-item">
                <span className="k">Ingest auth</span>
                <span className="v">
                  <AuthChip status={request.ingest_auth_status} />
                </span>
              </div>
              <div className="meta-item">
                <span className="k">Response status</span>
                <span className="v">
                  <StatusPill status={request.response_status} />
                </span>
              </div>
            </div>
          )}

          {tab === "headers" && <HeadersTable headers={request.headers} />}

          {tab === "query" &&
            (Object.keys(request.query_parameters).length === 0 ? (
              <EmptyState icon="🔍" title="No query parameters" />
            ) : (
              <HeadersTable headers={request.query_parameters} title="Parameter" />
            ))}

          {tab === "body" &&
            (request.body_text === null ? (
              <EmptyState icon="📭" title="No body" hint="This request had no content." />
            ) : bodyIsJson && bodyView === "formatted" ? (
              <>
                <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  <button
                    type="button"
                    className="btn btn-sm"
                    onClick={() => setBodyView("raw")}
                  >
                    Raw view
                  </button>
                  <CopyButton value={request.body_text} label="Copy body" className="btn btn-sm" />
                </div>
                <JsonViewer data={request.body_json} />
              </>
            ) : (
              <>
                <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
                  {bodyIsJson && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => setBodyView("formatted")}
                    >
                      JSON view
                    </button>
                  )}
                  <CopyButton value={request.body_text} label="Copy body" className="btn btn-sm" />
                </div>
                <pre className="json-viewer" style={{ whiteSpace: "pre-wrap" }}>
                  {request.body_text}
                </pre>
              </>
            ))}

          {tab === "response" && (
            <div className="meta-grid">
              <div className="meta-item">
                <span className="k">Status returned to sender</span>
                <span className="v">
                  <StatusPill status={request.response_status} />
                </span>
              </div>
            </div>
          )}

          {tab === "replay" && (
            <ReplayPanel
              requestId={request.id}
              defaultTarget={endpoint?.replay_target_url ?? null}
              initialMethod={request.method}
              initialHeaders={request.headers}
              initialBody={request.body_text ?? ""}
            />
          )}
        </div>
      </div>

      {confirmDelete && (
        <ConfirmDialog
          title="Delete request?"
          message="This permanently deletes this request and its replay records. This cannot be undone."
          confirmLabel="Delete request"
          onConfirm={() => {
            setConfirmDelete(false);
            void remove();
          }}
          onCancel={() => setConfirmDelete(false)}
        />
      )}
    </>
  );
}
