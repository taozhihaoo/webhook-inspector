import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Endpoint } from "../api/types";
import { CopyButton } from "../components/CopyButton";
import { EndpointFormModal } from "../components/EndpointFormModal";
import { ConfirmDialog } from "../components/Modal";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useToast } from "../components/Toast";
import { usePolling } from "../hooks/useSse";
import { formatRelative } from "../lib/format";

function EndpointStatusBadge({ endpoint }: { endpoint: Endpoint }) {
  const meta = {
    active: { cls: "chip-ok", label: "● active" },
    expired: { cls: "chip-warn", label: "◌ expired" },
    disabled: { cls: "chip-muted", label: "⏸ disabled" },
  }[endpoint.status];
  return <span className={`chip ${meta.cls}`}>{meta.label}</span>;
}

export function DashboardPage() {
  const { showToast, showError } = useToast();
  const navigate = useNavigate();
  const [endpoints, setEndpoints] = useState<Endpoint[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [deleting, setDeleting] = useState<Endpoint | null>(null);

  const load = useCallback(async () => {
    try {
      setEndpoints(await api.listEndpoints());
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to load endpoints.");
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);
  usePolling(load, 4000, true);

  const remove = async () => {
    if (deleting === null) {
      return;
    }
    try {
      await api.deleteEndpoint(deleting.id);
      showToast("Endpoint deleted", "success");
      setDeleting(null);
      void load();
    } catch (caught) {
      showError(caught);
    }
  };

  if (error !== null && endpoints === null) {
    return <ErrorState message={error} />;
  }
  if (endpoints === null) {
    return <LoadingState />;
  }

  return (
    <>
      <div className="page-title">
        <h1>Webhook endpoints</h1>
        <div style={{ display: "flex", gap: 8 }}>
          <button type="button" className="btn" onClick={() => void load()}>
            ⟳ Refresh
          </button>
          <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
            + New endpoint
          </button>
        </div>
      </div>

      {endpoints.length === 0 ? (
        <div className="panel">
          <EmptyState
            title="No webhook endpoints yet"
            hint="Create an endpoint, point a third-party service at the generated URL, and watch requests arrive live."
          >
            <button type="button" className="btn btn-primary" onClick={() => setShowCreate(true)}>
              + Create your first endpoint
            </button>
          </EmptyState>
        </div>
      ) : (
        <div className="panel">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Webhook URL</th>
                <th>Status</th>
                <th style={{ textAlign: "right" }}>Requests</th>
                <th>Last request</th>
                <th>Expires</th>
                <th aria-label="Actions" />
              </tr>
            </thead>
            <tbody>
              {endpoints.map((endpoint) => (
                <tr key={endpoint.id}>
                  <td>
                    <Link to={`/endpoints/${endpoint.id}`}>{endpoint.name}</Link>
                  </td>
                  <td className="mono" style={{ maxWidth: 320, overflowWrap: "anywhere" }}>
                    {endpoint.webhook_url}
                    <CopyButton value={endpoint.webhook_url} title="Copy webhook URL" />
                  </td>
                  <td>
                    <EndpointStatusBadge endpoint={endpoint} />
                  </td>
                  <td style={{ textAlign: "right" }} className="mono">
                    {endpoint.request_count}
                  </td>
                  <td title={endpoint.last_request_at ?? undefined}>
                    {formatRelative(endpoint.last_request_at)}
                  </td>
                  <td title={endpoint.expires_at}>
                    {formatRelative(endpoint.expires_at)}
                  </td>
                  <td style={{ whiteSpace: "nowrap", textAlign: "right" }}>
                    <Link to={`/endpoints/${endpoint.id}`} className="btn btn-sm">
                      Open
                    </Link>{" "}
                    <button
                      type="button"
                      className="btn btn-sm btn-danger"
                      onClick={() => setDeleting(endpoint)}
                    >
                      Delete
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="pagination">
            <span className="count-note">
              {endpoints.length} endpoint{endpoints.length === 1 ? "" : "s"}
            </span>
          </div>
        </div>
      )}

      {showCreate && (
        <EndpointFormModal
          onClose={() => setShowCreate(false)}
          onSaved={(endpoint) => navigate(`/endpoints/${endpoint.id}`)}
        />
      )}
      {deleting !== null && (
        <ConfirmDialog
          title="Delete endpoint?"
          message={`This permanently deletes "${deleting.name}" and its entire request history. This cannot be undone.`}
          confirmLabel="Delete endpoint"
          onConfirm={() => void remove()}
          onCancel={() => setDeleting(null)}
        />
      )}
    </>
  );
}
