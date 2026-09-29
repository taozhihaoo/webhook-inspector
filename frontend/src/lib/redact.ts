/** Redact sensitive header values for display. */

const SENSITIVE_PATTERNS = [
  "authorization",
  "cookie",
  "set-cookie",
  "x-api-key",
  "api-key",
  "apikey",
  "token",
  "secret",
  "signature",
  "password",
  "passwd",
  "proxy-authenticate",
  "proxy-authorization",
  "private",
];

export function isSensitiveHeader(name: string): boolean {
  const lower = name.toLowerCase();
  return SENSITIVE_PATTERNS.some((pattern) => lower.includes(pattern));
}

export const REDACTED = "[REDACTED]";

export function redactHeaders(
  headers: Record<string, string>,
): Array<{ name: string; value: string; sensitive: boolean }> {
  return Object.entries(headers).map(([name, value]) => ({
    name,
    value: isSensitiveHeader(name) ? REDACTED : value,
    sensitive: isSensitiveHeader(name),
  }));
}
