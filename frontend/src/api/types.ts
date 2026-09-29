export type EndpointStatus = "active" | "expired" | "disabled";

export interface SignatureStatusInfo {
  enabled: boolean;
  header: string | null;
  algorithm: string | null;
  encoding: string | null;
  configured: boolean;
}

export interface Endpoint {
  id: number;
  name: string;
  public_id: string;
  webhook_url: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  enabled: boolean;
  max_requests: number;
  request_count: number;
  request_retention_hours: number | null;
  status: EndpointStatus;
  last_request_at: string | null;
  response_status: number;
  response_content_type: string;
  response_body: string;
  response_delay_ms: number;
  replay_target_url: string | null;
  signature: SignatureStatusInfo;
  ingest_token_configured: boolean;
}

export interface SignatureInput {
  enabled: boolean;
  header: string;
  algorithm: "hmac-sha256" | "hmac-sha1" | "hmac-sha384" | "hmac-sha512";
  encoding: "hex" | "base64";
  secret?: string;
}

export interface EndpointCreateInput {
  name: string;
  ttl_hours: number;
  max_requests: number;
  request_retention_hours?: number | null;
  response_status: number;
  response_body: string;
  response_content_type: string;
  response_delay_ms: number;
  replay_target_url?: string | null;
  signature?: SignatureInput | null;
  ingest_token?: string | null;
}

export interface EndpointPatchInput {
  name?: string;
  enabled?: boolean;
  ttl_hours?: number;
  max_requests?: number;
  request_retention_hours?: number | null;
  response_status?: number;
  response_body?: string;
  response_content_type?: string;
  response_delay_ms?: number;
  replay_target_url?: string | null;
  signature?: SignatureInput | null;
  ingest_token?: string | null;
  remove_ingest_token?: boolean;
}

export type SignatureCheck = "verified" | "invalid" | "not_configured" | "error";
export type AuthCheck = "not_configured" | "valid" | "invalid";

export interface RequestSummary {
  id: number;
  endpoint_id: number;
  received_at: string;
  method: string;
  path: string;
  content_type: string | null;
  body_size: number;
  signature_status: SignatureCheck;
  ingest_auth_status: AuthCheck;
  response_status: number;
}

export interface RequestDetail extends RequestSummary {
  query_parameters: Record<string, string>;
  headers: Record<string, string>;
  body_text: string | null;
  body_json: unknown | null;
  source_ip: string | null;
  processing_duration_ms: number;
  replayable: boolean;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type ReplayStatus = "success" | "error" | "blocked" | "timeout";

export interface ReplayRecord {
  id: number;
  original_request_id: number;
  target_url: string;
  method: string;
  headers: Record<string, string>;
  status: ReplayStatus;
  response_status: number | null;
  response_headers: Record<string, string> | null;
  response_body_preview: string | null;
  duration_ms: number | null;
  error_message: string | null;
  created_at: string;
}

export interface ReplayInput {
  target_url?: string | null;
  method?: string | null;
  headers?: Record<string, string> | null;
  body_text?: string | null;
}

export interface CloneDraft {
  target_url: string | null;
  method: string;
  headers: Record<string, string>;
  body_text: string | null;
  content_type: string | null;
  query_parameters: Record<string, string>;
}

export interface Health {
  status: "ok";
  version: string;
  database: "ok";
}

export interface SseRequestEvent {
  endpoint_id: number;
  request_id: number;
  method: string;
  received_at: string;
  body_size: number;
  signature_status: string;
  ingest_auth_status: string;
  response_status: number;
}
