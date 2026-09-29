/** JSON utilities: validation, pretty printing, lightweight tokenizing. */

export type JsonToken = { text: string; kind: "key" | "string" | "number" | "boolean" | "null" | "punct" };

export function isValidJson(text: string): boolean {
  try {
    JSON.parse(text);
    return true;
  } catch {
    return false;
  }
}

export function jsonError(text: string): string | null {
  try {
    JSON.parse(text);
    return null;
  } catch (error) {
    return error instanceof Error ? error.message : "Invalid JSON";
  }
}

export function prettyPrint(value: unknown, indent = 2): string {
  return JSON.stringify(value, null, indent);
}

/**
 * Tokenize pretty-printed JSON for syntax highlighting.
 * Renders as plain React spans downstream — never HTML, so webhook bodies
 * (untrusted input) cannot inject markup.
 */
export function tokenizeJson(text: string): JsonToken[] {
  const tokens: JsonToken[] = [];
  // Keys ("..." followed by colon), strings, numbers, literals, punctuation.
  const pattern =
    /("(?:\\.|[^"\\])*")(\s*:)?|(-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?)|(\btrue\b|\bfalse\b)|(\bnull\b)|([{}[\],:])/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = pattern.exec(text)) !== null) {
    if (match.index > lastIndex) {
      tokens.push({ text: text.slice(lastIndex, match.index), kind: "punct" });
    }
    if (match[1] !== undefined) {
      if (match[2]) {
        tokens.push({ text: match[1], kind: "key" });
        tokens.push({ text: match[2], kind: "punct" });
      } else {
        tokens.push({ text: match[1], kind: "string" });
      }
    } else if (match[3] !== undefined) {
      tokens.push({ text: match[3], kind: "number" });
    } else if (match[4] !== undefined) {
      tokens.push({ text: match[4], kind: "boolean" });
    } else if (match[5] !== undefined) {
      tokens.push({ text: match[5], kind: "null" });
    } else {
      tokens.push({ text: match[6], kind: "punct" });
    }
    lastIndex = pattern.lastIndex;
  }
  if (lastIndex < text.length) {
    tokens.push({ text: text.slice(lastIndex), kind: "punct" });
  }
  return tokens;
}
