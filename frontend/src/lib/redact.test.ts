import { describe, expect, it } from "vitest";
import { isSensitiveHeader, redactHeaders } from "./redact";
import { isValidJson, jsonError, prettyPrint, tokenizeJson } from "./json";

describe("header redaction", () => {
  it("flags sensitive headers", () => {
    expect(isSensitiveHeader("Authorization")).toBe(true);
    expect(isSensitiveHeader("x-api-key")).toBe(true);
    expect(isSensitiveHeader("Stripe-Signature")).toBe(true);
    expect(isSensitiveHeader("X-Webhook-Token")).toBe(true);
    expect(isSensitiveHeader("content-type")).toBe(false);
    expect(isSensitiveHeader("user-agent")).toBe(false);
  });

  it("redacts sensitive values and keeps others", () => {
    const rows = redactHeaders({
      Authorization: "Bearer super-secret",
      "Content-Type": "application/json",
    });
    const auth = rows.find((row) => row.name === "Authorization");
    expect(auth?.value).toBe("[REDACTED]");
    expect(auth?.sensitive).toBe(true);
    expect(rows.find((row) => row.name === "Content-Type")?.value).toBe("application/json");
  });

  it("never returns raw sensitive values", () => {
    const rows = redactHeaders({ "Private-Token": "abc" });
    expect(JSON.stringify(rows)).not.toContain("abc");
  });
});

describe("json helpers", () => {
  it("validates json", () => {
    expect(isValidJson('{"a": 1}')).toBe(true);
    expect(isValidJson("{nope}")).toBe(false);
  });

  it("returns error messages for invalid json", () => {
    expect(jsonError("not json")).toBeTruthy();
    expect(jsonError('{"ok": true}')).toBeNull();
  });

  it("pretty prints", () => {
    expect(prettyPrint({ a: 1 })).toBe('{\n  "a": 1\n}');
  });

  it("tokenizes keys, strings, numbers, literals", () => {
    const tokens = tokenizeJson('{"name": "webhook", "count": 3, "ok": true, "x": null}');
    const kinds = tokens.filter((token) => token.text.trim() !== "").map((t) => t.kind);
    expect(kinds).toContain("key");
    expect(kinds).toContain("string");
    expect(kinds).toContain("number");
    expect(kinds).toContain("boolean");
    expect(kinds).toContain("null");
  });

  it("escapes content so injected markup stays text", () => {
    const tokens = tokenizeJson('{"evil": "<script>alert(1)</script>"}');
    const rendered = tokens.map((token) => token.text).join("");
    // The raw script tag must survive as an inert string token — rendering
    // happens through React text nodes, never innerHTML.
    expect(rendered).toContain("<script>");
  });
});
