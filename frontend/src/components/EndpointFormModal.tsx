import { useState } from "react";
import { ApiError, api } from "../api/client";
import type { Endpoint, SignatureInput } from "../api/types";
import { useToast } from "./Toast";
import { Modal } from "./Modal";

const TTL_OPTIONS = [
  { label: "1 hour", hours: 1 },
  { label: "6 hours", hours: 6 },
  { label: "24 hours", hours: 24 },
  { label: "7 days", hours: 168 },
  { label: "30 days", hours: 720 },
  { label: "Custom…", hours: -1 },
];

const DEFAULT_FORM = {
  name: "",
  ttlChoice: 24,
  customTtl: 48,
  maxRequests: 1000,
  requestRetentionHours: "",
  responseStatus: 200,
  responseBody: '{"received": true}',
  responseContentType: "application/json",
  responseDelayMs: 0,
  replayTargetUrl: "",
  ingestToken: "",
  // advanced / signature
  signatureEnabled: false,
  signatureHeader: "X-Signature",
  signatureAlgorithm: "hmac-sha256" as SignatureInput["algorithm"],
  signatureEncoding: "hex" as SignatureInput["encoding"],
  signatureSecret: "",
};

type FormState = typeof DEFAULT_FORM;

export function EndpointFormModal({
  existing,
  onClose,
  onSaved,
}: {
  existing?: Endpoint | null;
  onClose: () => void;
  onSaved: (endpoint: Endpoint) => void;
}) {
  const { showToast, showError } = useToast();
  const [form, setForm] = useState<FormState>(() => ({
    ...DEFAULT_FORM,
    ...(existing
      ? {
          name: existing.name,
          maxRequests: existing.max_requests,
          requestRetentionHours: existing.request_retention_hours?.toString() ?? "",
          responseStatus: existing.response_status,
          responseBody: existing.response_body,
          responseContentType: existing.response_content_type,
          responseDelayMs: existing.response_delay_ms,
          replayTargetUrl: existing.replay_target_url ?? "",
        }
      : {}),
  }));
  const [showAdvanced, setShowAdvanced] = useState(existing?.signature.enabled ?? false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const set = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((current) => ({ ...current, [key]: value }));

  const effectiveTtl =
    form.ttlChoice === -1
      ? Math.max(1, Math.floor(form.customTtl) || 0)
      : form.ttlChoice;

  const submit = async () => {
    if (!form.name.trim()) {
      setError("Name is required.");
      return;
    }
    if (effectiveTtl < 1) {
      setError("TTL must be at least 1 hour.");
      return;
    }
    if (form.signatureEnabled && !existing?.signature.configured && !form.signatureSecret) {
      setError("A signature secret is required to enable verification.");
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (existing) {
        const patch: Record<string, unknown> = {
          name: form.name,
          max_requests: form.maxRequests,
          response_status: form.responseStatus,
          response_body: form.responseBody,
          response_content_type: form.responseContentType,
          response_delay_ms: form.responseDelayMs,
          replay_target_url: form.replayTargetUrl || null,
        };
        if (form.requestRetentionHours !== "") {
          patch.request_retention_hours = Number(form.requestRetentionHours);
        }
        if (form.signatureSecret) {
          patch.signature = {
            enabled: form.signatureEnabled,
            header: form.signatureHeader,
            algorithm: form.signatureAlgorithm,
            encoding: form.signatureEncoding,
            secret: form.signatureSecret,
          };
        } else {
          patch.signature = {
            enabled: form.signatureEnabled,
            header: form.signatureHeader,
            algorithm: form.signatureAlgorithm,
            encoding: form.signatureEncoding,
          };
        }
        if (form.ingestToken) {
          patch.ingest_token = form.ingestToken;
        }
        const updated = await api.patchEndpoint(existing.id, patch);
        showToast("Endpoint updated", "success");
        onSaved(updated);
      } else {
        const created = await api.createEndpoint({
          name: form.name,
          ttl_hours: effectiveTtl,
          max_requests: form.maxRequests,
          request_retention_hours:
            form.requestRetentionHours !== "" ? Number(form.requestRetentionHours) : null,
          response_status: form.responseStatus,
          response_body: form.responseBody,
          response_content_type: form.responseContentType,
          response_delay_ms: form.responseDelayMs,
          replay_target_url: form.replayTargetUrl || null,
          signature: form.signatureEnabled
            ? {
                enabled: true,
                header: form.signatureHeader,
                algorithm: form.signatureAlgorithm,
                encoding: form.signatureEncoding,
                secret: form.signatureSecret,
              }
            : null,
          ingest_token: form.ingestToken || null,
        });
        showToast("Endpoint created", "success");
        onSaved(created);
      }
      onClose();
    } catch (caught) {
      if (caught instanceof ApiError) {
        setError(caught.message);
      } else {
        showError(caught);
        setError("Failed to save the endpoint.");
      }
    } finally {
      setSaving(false);
    }
  };

  return (
    <Modal
      title={existing ? "Edit endpoint" : "Create webhook endpoint"}
      onClose={onClose}
      wide
      footer={
        <>
          <button type="button" className="btn" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={saving}>
            {saving ? "Saving…" : existing ? "Save changes" : "Create endpoint"}
          </button>
        </>
      }
    >
      <div className="form-row">
        <div className="field">
          <label htmlFor="ep-name">Name</label>
          <input
            id="ep-name"
            type="text"
            value={form.name}
            onChange={(event) => set("name", event.target.value)}
            placeholder="e.g. Stripe sandbox"
          />
        </div>
        <div className="field">
          <label htmlFor="ep-ttl">Expires after</label>
          <select
            id="ep-ttl"
            value={form.ttlChoice}
            onChange={(event) => set("ttlChoice", Number(event.target.value))}
          >
            {TTL_OPTIONS.map((option) => (
              <option key={option.hours} value={option.hours}>
                {option.label}
              </option>
            ))}
          </select>
        </div>
        {form.ttlChoice === -1 && (
          <div className="field">
            <label htmlFor="ep-ttl-custom">Custom TTL (hours)</label>
            <input
              id="ep-ttl-custom"
              type="number"
              min={1}
              value={form.customTtl}
              onChange={(event) => set("customTtl", Number(event.target.value))}
            />
          </div>
        )}
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="ep-max-requests">
            Max retained requests <span className="hint">(oldest pruned)</span>
          </label>
          <input
            id="ep-max-requests"
            type="number"
            min={1}
            value={form.maxRequests}
            onChange={(event) => set("maxRequests", Number(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="ep-retention">
            Request retention (hours) <span className="hint">(optional)</span>
          </label>
          <input
            id="ep-retention"
            type="number"
            min={1}
            placeholder="keep until endpoint cleanup"
            value={form.requestRetentionHours}
            onChange={(event) => set("requestRetentionHours", event.target.value)}
          />
        </div>
      </div>

      <div className="form-row">
        <div className="field">
          <label htmlFor="ep-status">Response status</label>
          <input
            id="ep-status"
            type="number"
            min={100}
            max={599}
            value={form.responseStatus}
            onChange={(event) => set("responseStatus", Number(event.target.value))}
          />
        </div>
        <div className="field">
          <label htmlFor="ep-content-type">Response content type</label>
          <input
            id="ep-content-type"
            type="text"
            value={form.responseContentType}
            onChange={(event) => set("responseContentType", event.target.value)}
          />
        </div>
        <div className="field">
          <label htmlFor="ep-delay">Response delay (ms, 0–10000)</label>
          <input
            id="ep-delay"
            type="number"
            min={0}
            max={10000}
            value={form.responseDelayMs}
            onChange={(event) => set("responseDelayMs", Number(event.target.value))}
          />
        </div>
      </div>

      <div className="field">
        <label htmlFor="ep-body">Response body</label>
        <textarea
          id="ep-body"
          rows={2}
          value={form.responseBody}
          onChange={(event) => set("responseBody", event.target.value)}
        />
      </div>

      <button
        type="button"
        className="advanced-toggle"
        onClick={() => setShowAdvanced((current) => !current)}
      >
        {showAdvanced ? "▾" : "▸"} Security & replay
      </button>

      {showAdvanced && (
        <div style={{ marginTop: 12 }}>
          <div className="field">
            <label htmlFor="ep-replay-url">
              Default replay target URL{" "}
              <span className="hint">(https recommended; used as the replay default)</span>
            </label>
            <input
              id="ep-replay-url"
              type="url"
              placeholder="https://your-service.example.com/webhooks"
              value={form.replayTargetUrl}
              onChange={(event) => set("replayTargetUrl", event.target.value)}
            />
          </div>
          <div className="field">
            <label htmlFor="ep-ingest-token">
              Ingest token (X-Webhook-Token){" "}
              <span className="hint">
                (optional; stored hashed. {existing?.ingest_token_configured ? "A token is currently set." : ""}
              </span>
            </label>
            <input
              id="ep-ingest-token"
              type="password"
              autoComplete="off"
              placeholder={existing?.ingest_token_configured ? "Set to rotate" : "Leave empty to disable"}
              value={form.ingestToken}
              onChange={(event) => set("ingestToken", event.target.value)}
            />
          </div>

          <div className="field">
            <label style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text)" }}>
              <input
                type="checkbox"
                checked={form.signatureEnabled}
                onChange={(event) => set("signatureEnabled", event.target.checked)}
              />
              Verify HMAC signatures
            </label>
          </div>
          {form.signatureEnabled && (
            <>
              <div className="form-row">
                <div className="field">
                  <label htmlFor="ep-sig-header">Signature header</label>
                  <input
                    id="ep-sig-header"
                    type="text"
                    value={form.signatureHeader}
                    onChange={(event) => set("signatureHeader", event.target.value)}
                  />
                </div>
                <div className="field">
                  <label htmlFor="ep-sig-alg">Algorithm</label>
                  <select
                    id="ep-sig-alg"
                    value={form.signatureAlgorithm}
                    onChange={(event) =>
                      set("signatureAlgorithm", event.target.value as SignatureInput["algorithm"])
                    }
                  >
                    <option value="hmac-sha256">HMAC-SHA256</option>
                    <option value="hmac-sha1">HMAC-SHA1</option>
                    <option value="hmac-sha384">HMAC-SHA384</option>
                    <option value="hmac-sha512">HMAC-SHA512</option>
                  </select>
                </div>
                <div className="field">
                  <label htmlFor="ep-sig-enc">Encoding</label>
                  <select
                    id="ep-sig-enc"
                    value={form.signatureEncoding}
                    onChange={(event) =>
                      set("signatureEncoding", event.target.value as SignatureInput["encoding"])
                    }
                  >
                    <option value="hex">hex</option>
                    <option value="base64">base64</option>
                  </select>
                </div>
              </div>
              <div className="field">
                <label htmlFor="ep-sig-secret">
                  Secret{" "}
                  <span className="hint">
                    (encrypted at rest;{" "}
                    {existing?.signature.configured ? "leave empty to keep current secret" : "required"}
                  )
                </span>
              </label>
              <input
                id="ep-sig-secret"
                type="password"
                autoComplete="off"
                value={form.signatureSecret}
                onChange={(event) => set("signatureSecret", event.target.value)}
              />
            </div>
            </>
          )}
        </div>
      )}

      {error !== null && <p className="inline-error">{error}</p>}
    </Modal>
  );
}
