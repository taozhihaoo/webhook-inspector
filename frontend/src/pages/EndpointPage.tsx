import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ApiError, api } from "../api/client";
import type { Endpoint, RequestSummary } from "../api/types";
import { AuthChip, MethodBadge, SignatureChip, StatusPill } from "../components/Badges";
import { CopyButton } from "../components/CopyButton";
import { ConfirmDialog } from "../components/Modal";
import { EndpointFormModal } from "../components/EndpointFormModal";
import { EmptyState, ErrorState, LoadingState } from "../components/States";
import { useToast } from "../components/Toast";
import { usePolling, useSse } from "../hooks/useSse";
import { formatBytes, formatDateTime, formatRelative } from "../lib/format";

const PAGE_SIZE = 20;

export function EndpointPage() {
  const { endpointId } = useParams<{ endpointId: string }>();
  const id = Number(endpointId);
  const navigate = useNavigate();
  const { showToast, showError } = useToast();

  const [endpoint, setEndpoint] = useState<Endpoint | null>(null);
  const [requests, setRequests] = useState<RequestSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [search, setSearch] = useState("");
  const [searchInput, setSearchInput] = useState("");
  const [method, setMethod] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [showEdit, setShowEdit] = useState(false);
  const [confirm, setConfirm] = useState<"delete-endpoint" | "clear-history" | null>(null);

  const loadEndpoint = useCallback(async () => {
    try {
      setEndpoint(await api.getEndpoint(id));
      setError(null);
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Failed to load endpoint.");
    }
  }, [id]);

  const loadRequests = useCallback(async () => {
    try {
      const result = await api.listRequests(id, {
        search,
        method,
        date_from: dateFrom || undefined,
        date_to: dateTo || undefined,
        page,
        page_size: PAGE_SIZE,
      });
      setRequests(result.items);
      setTotal(result.total);
    } catch (caught) {
      showError(caught);
    }
  }, [id, search, method, dateFrom, dateTo, page, showError]);

  useEffect(() => {
    void loadEndpoint();
  }, [loadEndpoint]);
  useEffect(() => {
    void loadRequests();
  }, [loadRequests]);

  // Live updates over SSE (falls back to polling when the stream fails).
  const onEvent = useCallback(() => {
    void loadEndpoint();
    void loadRequests();
  }, [loadEndpoint, loadRequests]);
  const sseState = useSse(Number.isFinite(id) ? id : null, { onEvent });
  usePolling(loadRequests, 4000, sseState !== "live");

  if (error !== null && endpoint === null) {
    return <ErrorState message={error} />;
  }
  if (!Number.isFinite(id) || endpoint === null) {
    return <LoadingState />;
  }

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  const applySearch = () => {
    setPage(1);
    setSearch(searchInput.trim());
  };

  const toggleEnabled = async () => {
    try {
      setEndpoint(await api.patchEndpoint(id, { enabled: !endpoint.enabled }));
      showToast(endpoint.enabled ? "Endpoint disabled" : "Endpoint enabled", "success");
    } catch (caught) {
      showError(caught);
    }
  };

  const removeEndpoint = async () => {
    await api.deleteEndpoint(id);
    showToast("Endpoint deleted", "success");
    void navigate("/");
  };

  const clearHistory = async () => {
    try {
      const result = await api.clearRequests(id);
      showToast(`Deleted ${result.count ?? 0} requests`, "success");
      await Promise.all([loadEndpoint(), loadRequests()]);
    } catch (caught) {
      showError(caught);
    }
  };

  return (
    <>
      <div className="page-title">
        <h1>
          {endpoint.name}{" "}
          <span className="chip chip-muted">{endpoint.status}</span>
        </h1>
        <div style={{ display: "flex", gap: 8, flexWrap: "wrap" }}>
          <button type="button" className="btn" onClick={() => void loadEndpoint()}>
            ⟳ Refresh
          </button>
          <button type="button" className="btn" onClick={toggleEnabled}>
            {endpoint.enabled ? "⏸ Disable" : "▶ Enable"}
          </button>
          <button type="button" className="btn" onClick={() => setShowEdit(true)}>
            ✎ Edit
          </button>
          <button
            type="button"
            className="btn"
            onClick={() => setConfirm("clear-history")}
            disabled={total === 0}
          >
            Clear history
          </button>
          <button type="button" className="btn btn-danger" onClick={() => setConfirm("delete-endpoint")}>
            Delete
          </button>
        </div>
      </div>

      <div className="panel panel-pad endpoint-card">
        <div>
          <span className="section-title" style={{ display: "block" }}>
            Webhook URL — configure this in your provider
          </span>
          <div className="url-box">
            <span style={{ flex: 1, overflowWrap: "anywhere" }}>{endpoint.webhook_url}</span>
            <CopyButton value={endpoint.webhook_url} label="Copy URL" />
          </div>
        </div>
        <div className="meta-grid">
          <div className="meta-item">
            <span className="k">Requests received</span>
            <span className="v mono">{endpoint.request_count}</span>
          </div>
          <div className="meta-item">
            <span className="k">History cap</span>
            <span className="v mono">{endpoint.max_requests} retained</span>
          </div>
          <div className="meta-item">
            <span className="k">Expires</span>
            <span className="v">
              {formatRelative(endpoint.expires_at)}{" "}
              <span className="count-note">({formatDateTime(endpoint.expires_at)})</span>
            </span>
          </div>
          <div className="meta-item">
            <span className="k">Responds with</span>
            <span className="v">
              <StatusPill status={endpoint.response_status} />
            </span>
          </div>
          <div className="meta-item">
            <span className="k">Signature</span>
            <span className="v">
              {endpoint.signature.enabled
                ? `${endpoint.signature.algorithm} → ${endpoint.signature.header}`
                : "not configured"}
            </span>
          </div>
          <div className="meta-item">
            <span className="k">Ingest token</span>
            <span className="v">{endpoint.ingest_token_configured ? "required ✓" : "off"}</span>
          </div>
          <div className="meta-item">
            <span className="k">Default replay target</span>
            <span className="v mono" style={{ overflowWrap: "anywhere" }}>
              {endpoint.replay_target_url ?? "not set"}
            </span>
          </div>
          <div className="meta-item">
            <span className="k">Live</span>
            <span className={`live-dot ${sseState === "live" ? "live" : ""}`}>
              <span className="dot" aria-hidden />
              {sseState === "live"
                ? "streaming (SSE)"
                : sseState === "failed"
                  ? "offline — polling fallback"
                  : "connecting…"}
            </span>
          </div>
        </div>
      </div>

      <h2 style={{ fontSize: 16, margin: "20px 0 8px" }}>Request history</h2>
      <div className="panel">
        <div className="toolbar">
          <input
            type="text"
            placeholder="Search body, headers, path…"
            value={searchInput}
            onChange={(event) => setSearchInput(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") {
                applySearch();
              }
            }}
            style={{ flex: 2, minWidth: 180 }}
            aria-label="Search requests"
          />
          <select
            value={method}
            onChange={(event) => {
              setMethod(event.target.value);
              setPage(1);
            }}
            aria-label="Filter by method"
          >
            <option value="">All methods</option>
            {["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"].map((m) => (
              <option key={m} value={m}>
                {m}
              </option>
            ))}
          </select>
          <input
            type="datetime-local"
            value={dateFrom}
            onChange={(event) => {
              setDateFrom(event.target.value);
              setPage(1);
            }}
            aria-label="From date"
            title="From"
          />
          <input
            type="datetime-local"
            value={dateTo}
            onChange={(event) => {
              setDateTo(event.target.value);
              setPage(1);
            }}
            aria-label="To date"
            title="To"
          />
          <button type="button" className="btn btn-primary btn-sm" onClick={applySearch}>
            Search
          </button>
          {(search !== "" || method !== "" || dateFrom !== "" || dateTo !== "") && (
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => {
                setSearch("");
                setSearchInput("");
                setMethod("");
                setDateFrom("");
                setDateTo("");
                setPage(1);
              }}
            >
              Reset
            </button>
          )}
          <span className="count-note" style={{ marginLeft: "auto" }}>
            {total} request{total === 1 ? "" : "s"}
          </span>
        </div>

        {requests === null ? (
          <LoadingState />
        ) : requests.length === 0 ? (
          <EmptyState
            icon="📥"
            title="No requests match"
            hint="Send a webhook to the URL above, or adjust the filters."
          />
        ) : (
          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>Received</th>
                <th>Method</th>
                <th>Path</th>
                <th>Content type</th>
                <th style={{ textAlign: "right" }}>Size</th>
                <th>Signature</th>
                <th>Auth</th>
                <th>Response</th>
              </tr>
            </thead>
            <tbody>
              {requests.map((request) => (
                <tr
                  key={request.id}
                  className="rowlink"
                  onClick={() => navigate(`/requests/${request.id}`)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter") {
                      navigate(`/requests/${request.id}`);
                    }
                  }}
                  tabIndex={0}
                  role="link"
                  aria-label={`Open request ${request.id}`}
                >
                  <td className="mono">{request.id}</td>
                  <td title={formatDateTime(request.received_at)}>
                    {formatRelative(request.received_at)}
                  </td>
                  <td>
                    <MethodBadge method={request.method} />
                  </td>
                  <td className="mono" style={{ maxWidth: 220, overflow: "hidden", textOverflow: "ellipsis" }}>
                    {request.path}
                  </td>
                  <td className="mono" style={{ fontSize: 12 }}>
                    {request.content_type ?? "—"}
                  </td>
                  <td style={{ textAlign: "right" }} className="mono">
                    {formatBytes(request.body_size)}
                  </td>
                  <td>
                    <SignatureChip status={request.signature_status} />
                  </td>
                  <td>
                    <AuthChip status={request.ingest_auth_status} />
                  </td>
                  <td>
                    <StatusPill status={request.response_status} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}

        <div className="pagination">
          <button
            type="button"
            className="btn btn-sm"
            disabled={page <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            ← Prev
          </button>
          <span>
            Page {page} / {totalPages}
          </span>
          <button
            type="button"
            className="btn btn-sm"
            disabled={page >= totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
          >
            Next →
          </button>
          <Link to="/" className="count-note" style={{ marginLeft: 12 }}>
            all endpoints
          </Link>
        </div>
      </div>

      {showEdit && (
        <EndpointFormModal
          existing={endpoint}
          onClose={() => setShowEdit(false)}
          onSaved={(updated) => {
            setEndpoint(updated);
            setShowEdit(false);
          }}
        />
      )}
      {confirm === "delete-endpoint" && (
        <ConfirmDialog
          title="Delete endpoint?"
          message={`This permanently deletes "${endpoint.name}" and its entire request history. This cannot be undone.`}
          confirmLabel="Delete endpoint"
          onConfirm={() => void removeEndpoint()}
          onCancel={() => setConfirm(null)}
        />
      )}
      {confirm === "clear-history" && (
        <ConfirmDialog
          title="Clear request history?"
          message={`All ${total} recorded requests for "${endpoint.name}" will be permanently deleted. The endpoint itself stays active.`}
          confirmLabel="Clear history"
          onConfirm={() => {
            setConfirm(null);
            void clearHistory();
          }}
          onCancel={() => setConfirm(null)}
        />
      )}
    </>
  );
}
