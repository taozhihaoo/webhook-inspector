import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { ReplayRecord, ReplayInput } from "../api/types";
import { ReplayResultCard, ReplayStatusChip, StatusPill } from "./Badges";
import { CopyButton } from "./CopyButton";
import { formatDateTime, formatDuration } from "../lib/format";
import { isValidJson } from "../lib/json";
import { useToast } from "./Toast";

interface HeaderRow {
  name: string;
  value: string;
}

function parseHeaderRows(raw: Record<string, string>): HeaderRow[] {
  return Object.entries(raw).map(([name, value]) => ({ name, value }));
}

/**
 * Clone & Edit / Replay panel.
 * The original request is never modified — a replay always creates a new
 * ReplayRecord targeted at the (editable) target URL.
 */
export function ReplayPanel({
  requestId,
  defaultTarget,
  initialMethod,
  initialHeaders,
  initialBody,
}: {
  requestId: number;
  defaultTarget: string | null;
  initialMethod: string;
  initialHeaders: Record<string, string>;
  initialBody: string | null;
}) {
  const { showToast, showError } = useToast();
  const [target, setTarget] = useState(defaultTarget ?? "");
  const [method, setMethod] = useState(initialMethod);
  const [rows, setRows] = useState<HeaderRow[]>(parseHeaderRows(initialHeaders));
  const [bodyText, setBodyText] = useState(initialBody ?? "");
  const [bodyMode, setBodyMode] = useState<"pretty" | "raw">("raw");
  const [sending, setSending] = useState(false);
  const [result, setResult] = useState<ReplayRecord | null>(null);
  const [history, setHistory] = useState<ReplayRecord[]>([]);

  const loadHistory = useCallback(async () => {
    try {
      setHistory(await api.listReplays(requestId));
    } catch {
      // history is supplementary; the send result is shown directly
    }
  }, [requestId]);

  useEffect(() => {
    void loadHistory();
  }, [loadHistory]);

  const jsonInvalid =
    method !== "GET" &&
    bodyText.trim() !== "" &&
    (rows.some((row) => row.name.toLowerCase() === "content-type") ||
      bodyText.trim().startsWith("{") ||
      bodyText.trim().startsWith("[")) &&
    !isValidJson(bodyText);

  const send = async () => {
    if (jsonInvalid) {
      showToast("Invalid JSON — fix the body before sending", "error");
      return;
    }
    setSending(true);
    setResult(null);
    try {
      const headers: Record<string, string> = {};
      for (const row of rows) {
        if (row.name.trim() !== "") {
          headers[row.name.trim()] = row.value;
        }
      }
      const input: ReplayInput = {
        target_url: target || null,
        method,
        headers,
        body_text: method === "GET" ? null : bodyText,
      };
      const record = await api.replayRequest(requestId, input);
      setResult(record);
      showToast(`Replay ${record.status}`, record.status === "success" ? "success" : "error");
      await loadHistory();
    } catch (caught) {
      showError(caught);
    } finally {
      setSending(false);
    }
  };

  const formatJson = () => {
    try {
      setBodyText(JSON.stringify(JSON.parse(bodyText), null, 2));
      setBodyMode("pretty");
    } catch {
      showToast("Invalid JSON — cannot format", "error");
    }
  };

  return (
    <div>
      <p className="count-note" style={{ marginTop: 0 }}>
        Replay sends a <strong>copy</strong> of this request to the target URL. The original
        request stored in the history is never modified. Targets must be HTTPS; private
        networks are blocked by the SSRF guard.
      </p>

      <div className="field">
        <label htmlFor="replay-target">Target URL</label>
        <input
          id="replay-target"
          type="text"
          value={target}
          onChange={(event) => setTarget(event.target.value)}
          placeholder="https://your-service.example.com/webhooks"
          className="mono"
        />
      </div>

      <div className="field">
        <label htmlFor="replay-method">Method</label>
        <select
          id="replay-method"
          value={method}
          onChange={(event) => setMethod(event.target.value)}
          style={{ width: 140 }}
        >
          {["POST", "PUT", "PATCH", "DELETE", "GET", "OPTIONS"].map((m) => (
            <option key={m} value={m}>
              {m}
            </option>
          ))}
        </select>
      </div>

      <div className="field">
        <label>Headers</label>
        {rows.map((row, index) => (
          <div key={index} style={{ display: "flex", gap: 8, marginBottom: 6 }}>
            <input
              type="text"
              value={row.name}
              placeholder="Header-Name"
              className="mono"
              style={{ flex: 2 }}
              onChange={(event) =>
                setRows((current) =>
                  current.map((item, i) =>
                    i === index ? { ...item, name: event.target.value } : item,
                  ),
                )
              }
              aria-label={`Header ${index + 1} name`}
            />
            <input
              type="text"
              value={row.value}
              placeholder="value"
              className="mono"
              style={{ flex: 3 }}
              onChange={(event) =>
                setRows((current) =>
                  current.map((item, i) =>
                    i === index ? { ...item, value: event.target.value } : item,
                  ),
                )
              }
              aria-label={`Header ${index + 1} value`}
            />
            <button
              type="button"
              className="btn btn-sm"
              onClick={() => setRows((current) => current.filter((_, i) => i !== index))}
              aria-label={`Remove header ${index + 1}`}
            >
              ✕
            </button>
          </div>
        ))}
        <div>
          <button
            type="button"
            className="btn btn-sm"
            onClick={() => setRows((current) => [...current, { name: "", value: "" }])}
          >
            + Add header
          </button>
        </div>
      </div>

      <div className="field">
        <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
          <label htmlFor="replay-body" style={{ marginBottom: 0 }}>
            Body
          </label>
          <button type="button" className="btn btn-sm" onClick={formatJson} disabled={method === "GET"}>
            Format JSON
          </button>
          {jsonInvalid && <span className="inline-error" role="alert">Invalid JSON</span>}
        </div>
        <textarea
          id="replay-body"
          rows={10}
          value={bodyText}
          className={bodyMode === "pretty" ? "" : "mono"}
          onChange={(event) => {
            setBodyText(event.target.value);
            setBodyMode("raw");
          }}
          spellCheck={false}
        />
      </div>

      <button type="button" className="btn btn-primary" onClick={() => void send()} disabled={sending || jsonInvalid}>
        {sending ? "Sending…" : "▶ Send replay"}
      </button>

      {result !== null && <ReplayResultCard record={result} />}

      {history.length > 0 && (
        <div style={{ marginTop: 20 }}>
          <h3 className="section-title">Replay history for this request</h3>
          <table className="data">
            <thead>
              <tr>
                <th>When</th>
                <th>Target</th>
                <th>Status</th>
                <th>Response</th>
                <th style={{ textAlign: "right" }}>Duration</th>
              </tr>
            </thead>
            <tbody>
              {history.map((record) => (
                <tr key={record.id}>
                  <td title={formatDateTime(record.created_at)} className="mono" style={{ fontSize: 12 }}>
                    {formatDateTime(record.created_at)}
                  </td>
                  <td className="mono" style={{ maxWidth: 260, overflowWrap: "anywhere", fontSize: 12 }}>
                    {record.target_url}
                  </td>
                  <td>
                    <ReplayStatusChip status={record.status} />
                  </td>
                  <td>
                    {record.response_status !== null ? (
                      <StatusPill status={record.response_status} />
                    ) : (
                      <span className="count-note">{record.error_message ?? "—"}</span>
                    )}
                  </td>
                  <td style={{ textAlign: "right" }} className="mono">
                    {formatDuration(record.duration_ms)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function HeadersTable({
  headers,
  title = "Headers",
}: {
  headers: Record<string, string>;
  title?: string;
}) {
  const [revealed, setRevealed] = useState<Set<string>>(new Set());
  const entries = parseHeaderRows(headers);

  const toggle = (name: string) => {
    setRevealed((current) => {
      const next = new Set(current);
      if (next.has(name)) {
        next.delete(name);
      } else {
        next.add(name);
      }
      return next;
    });
  };

  return (
    <div>
      <table className="data">
        <thead>
          <tr>
            <th style={{ width: "30%" }}>{title}</th>
            <th>Value</th>
            <th aria-label="Actions" style={{ width: 90 }} />
          </tr>
        </thead>
        <tbody>
          {entries.map((row) => {
            const sensitive =
              /authorization|cookie|token|secret|signature|api-?key|password|private/i.test(
                row.name,
              );
            const hidden = sensitive && !revealed.has(row.name);
            return (
              <tr key={row.name}>
                <td className="mono" style={{ overflowWrap: "anywhere" }}>
                  {row.name}
                </td>
                <td className="mono" style={{ overflowWrap: "anywhere" }}>
                  {hidden ? "[REDACTED]" : row.value}
                </td>
                <td style={{ textAlign: "right", whiteSpace: "nowrap" }}>
                  {sensitive && (
                    <button
                      type="button"
                      className="btn btn-sm"
                      onClick={() => toggle(row.name)}
                      aria-label={hidden ? `Reveal ${row.name}` : `Hide ${row.name}`}
                    >
                      {hidden ? "👁 Show" : "🙈 Hide"}
                    </button>
                  )}
                  <CopyButton value={row.value} label="Copy" title={`Copy ${row.name}`} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
