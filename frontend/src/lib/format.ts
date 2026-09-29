/** Formatting helpers for bytes, dates and durations. */

export function formatBytes(bytes: number | null | undefined): string {
  if (bytes === null || bytes === undefined) {
    return "—";
  }
  if (bytes < 1024) {
    return `${bytes} B`;
  }
  if (bytes < 1024 * 1024) {
    return `${(bytes / 1024).toFixed(1)} KB`;
  }
  return `${(bytes / (1024 * 1024)).toFixed(2)} MB`;
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return date.toLocaleString(undefined, {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function formatRelative(iso: string | null | undefined): string {
  if (!iso) {
    return "—";
  }
  const date = new Date(iso);
  const diffMs = Date.now() - date.getTime();
  const future = diffMs < 0;
  const seconds = Math.floor(Math.abs(diffMs) / 1000);
  let text: string;
  if (seconds < 5) {
    return future ? "in seconds" : "just now";
  } else if (seconds < 60) {
    text = `${seconds}s`;
  } else if (seconds < 3600) {
    text = `${Math.floor(seconds / 60)}m`;
  } else if (seconds < 86400) {
    text = `${Math.floor(seconds / 3600)}h`;
  } else {
    text = `${Math.floor(seconds / 86400)}d`;
  }
  return future ? `in ${text}` : `${text} ago`;
}

export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) {
    return "—";
  }
  if (ms < 1000) {
    return `${ms} ms`;
  }
  return `${(ms / 1000).toFixed(2)} s`;
}

export function statusClass(status: number | null | undefined): string {
  if (status === null || status === undefined) {
    return "status-5xx";
  }
  const group = Math.floor(status / 100);
  if (group >= 2 && group < 3) {
    return "status-2xx";
  }
  if (group === 3) {
    return "status-3xx";
  }
  if (group === 4) {
    return "status-4xx";
  }
  return "status-5xx";
}
