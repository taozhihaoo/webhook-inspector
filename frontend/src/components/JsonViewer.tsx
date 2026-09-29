import { useState } from "react";
import { tokenizeJson } from "../lib/json";
import type { JsonToken } from "../lib/json";

const MAX_INLINE_LENGTH = 512;
const COLLAPSE_DEPTH = 3;

function TokenSpan({ token }: { token: JsonToken }) {
  return <span className={`tok-${token.kind}`}>{token.text}</span>;
}

/** Recursive collapsible JSON renderer — plain spans only, never HTML. */
export function JsonNode({ value, depth = 0 }: { value: unknown; depth?: number }) {
  const [open, setOpen] = useState(depth < COLLAPSE_DEPTH);

  if (value === null) {
    return <span className="tok-null">null</span>;
  }
  if (typeof value === "string") {
    if (value.length > MAX_INLINE_LENGTH) {
      return <LongString value={value} />;
    }
    return <TokenSpan token={{ text: JSON.stringify(value), kind: "string" }} />;
  }
  if (typeof value === "number") {
    return <TokenSpan token={{ text: String(value), kind: "number" }} />;
  }
  if (typeof value === "boolean") {
    return <TokenSpan token={{ text: String(value), kind: "boolean" }} />;
  }

  const is_array = Array.isArray(value);
  const entries: Array<[string | number, unknown]> = is_array
    ? value.map((item, index) => [index, item] as [number, unknown])
    : Object.entries(value as Record<string, unknown>);

  if (entries.length === 0) {
    return <TokenSpan token={{ text: is_array ? "[]" : "{}", kind: "punct" }} />;
  }

  return (
    <span>
      <button
        type="button"
        className="jv-toggle"
        onClick={() => setOpen((current) => !current)}
        aria-expanded={open}
        title={open ? "Collapse" : "Expand"}
      >
        {open ? "▾" : "▸"}
      </button>
      <TokenSpan token={{ text: is_array ? "[" : "{", kind: "punct" }} />
      {!open && (
        <>
          <span className="tok-punct"> … </span>
          <span className="tok-punct">{entries.length} {is_array ? "items" : "keys"}</span>
          <TokenSpan token={{ text: is_array ? "]" : "}", kind: "punct" }} />
        </>
      )}
      {open && (
        <>
          <div style={{ paddingLeft: 18, borderLeft: "1px dotted var(--border)" }}>
            {entries.map(([key, child]) => (
              <div key={String(key)}>
                {!is_array && (
                  <TokenSpan
                    token={{ text: JSON.stringify(String(key)), kind: "key" }}
                  />
                )}
                {!is_array && <TokenSpan token={{ text: ": ", kind: "punct" }} />}
                <JsonNode value={child} depth={depth + 1} />
                <TokenSpan token={{ text: ",", kind: "punct" }} />
              </div>
            ))}
          </div>
          <TokenSpan token={{ text: is_array ? "]" : "}", kind: "punct" }} />
        </>
      )}
    </span>
  );
}

function LongString({ value }: { value: string }) {
  const [expanded, setExpanded] = useState(false);
  if (expanded) {
    return <TokenSpan token={{ text: JSON.stringify(value), kind: "string" }} />;
  }
  const preview = value.slice(0, MAX_INLINE_LENGTH);
  return (
    <span>
      <TokenSpan
        token={{ text: JSON.stringify(`${preview}…`), kind: "string" }}
      />
      <button type="button" className="jv-toggle" onClick={() => setExpanded(true)}>
        [show all {value.length} chars]
      </button>
    </span>
  );
}

/**
 * JSON viewer with syntax highlighting and collapsible nodes.
 * Body text is rendered as tokens/text — webhook payloads are untrusted
 * input and are never interpreted as HTML.
 */
export function JsonViewer({ data }: { data: unknown }) {
  return (
    <div className="json-viewer" role="region" aria-label="JSON body">
      <JsonNode value={data} />
    </div>
  );
}

/** Syntax-highlighted pretty JSON (non-interactive) for search/preview panes. */
export function JsonHighlight({ text }: { text: string }) {
  const tokens = tokenizeJson(text);
  return (
    <>
      {tokens.map((token, index) => (
        <TokenSpan key={index} token={token} />
      ))}
    </>
  );
}
