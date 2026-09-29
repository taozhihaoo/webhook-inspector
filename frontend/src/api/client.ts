import type {
  CloneDraft,
  Endpoint,
  EndpointCreateInput,
  EndpointPatchInput,
  Health,
  Page,
  ReplayInput,
  ReplayRecord,
  RequestDetail,
  RequestSummary,
} from "./types";

const TOKEN_KEY = "webhook-inspector.admin-token";

export function getStoredToken(): string {
  return localStorage.getItem(TOKEN_KEY) ?? "";
}

export function storeToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export class ApiError extends Error {
  code: string;
  status: number;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.status = status;
    this.code = code;
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(init.headers as Record<string, string> | undefined),
  };
  const token = getStoredToken();
  if (token) {
    headers.Authorization = `Bearer ${token}`;
  }
  if (init.body !== undefined && !headers["Content-Type"]) {
    headers["Content-Type"] = "application/json";
  }

  let response: Response;
  try {
    response = await fetch(path, { ...init, headers });
  } catch {
    throw new ApiError(0, "network_error", "Cannot reach the server. Is the backend running?");
  }

  if (response.status === 204) {
    return undefined as T;
  }

  let payload: unknown = null;
  try {
    payload = await response.json();
  } catch {
    payload = null;
  }

  const envelope = payload as { data?: T; error?: { code: string; message: string } } | null;
  if (!response.ok) {
    throw new ApiError(
      response.status,
      envelope?.error?.code ?? "http_error",
      envelope?.error?.message ?? `Request failed with status ${response.status}`,
    );
  }
  return envelope?.data as T;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  }
  const qs = search.toString();
  return qs ? `?${qs}` : "";
}

export const api = {
  health: () => request<Health>("/api/health"),

  listEndpoints: () => request<Endpoint[]>("/api/endpoints"),

  createEndpoint: (input: EndpointCreateInput) =>
    request<Endpoint>("/api/endpoints", {
      method: "POST",
      body: JSON.stringify(input),
    }),

  getEndpoint: (id: number) => request<Endpoint>(`/api/endpoints/${id}`),

  patchEndpoint: (id: number, input: EndpointPatchInput) =>
    request<Endpoint>(`/api/endpoints/${id}`, {
      method: "PATCH",
      body: JSON.stringify(input),
    }),

  deleteEndpoint: (id: number) =>
    request<Endpoint>(`/api/endpoints/${id}`, { method: "DELETE" }),

  listRequests: (
    endpointId: number,
    filters: {
      search?: string;
      method?: string;
      date_from?: string;
      date_to?: string;
      page?: number;
      page_size?: number;
    } = {},
  ) =>
    request<Page<RequestSummary>>(
      `/api/endpoints/${endpointId}/requests${query(filters)}`,
    ),

  clearRequests: (endpointId: number) =>
    request<{ deleted: boolean; count: number | null }>(
      `/api/endpoints/${endpointId}/requests`,
      { method: "DELETE" },
    ),

  getRequest: (id: number) => request<RequestDetail>(`/api/requests/${id}`),

  deleteRequest: (id: number) =>
    request<{ deleted: boolean }>(`/api/requests/${id}`, { method: "DELETE" }),

  cloneRequest: (id: number) =>
    request<CloneDraft>(`/api/requests/${id}/clone`, { method: "POST" }),

  replayRequest: (id: number, input: ReplayInput) =>
    request<ReplayRecord>(`/api/requests/${id}/replay`, {
      method: "POST",
      body: JSON.stringify(input),
    }),

  listReplays: (id: number) => request<ReplayRecord[]>(`/api/requests/${id}/replays`),
};
