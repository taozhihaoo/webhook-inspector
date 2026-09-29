import { useCallback, useRef, useState } from "react";

/** Copy-to-clipboard button with brief "Copied" feedback. */
export function CopyButton({
  value,
  label = "Copy",
  className = "copy-btn",
  title,
}: {
  value: string | null | undefined;
  label?: string;
  className?: string;
  title?: string;
}) {
  const [copied, setCopied] = useState(false);
  const timer = useRef<number | undefined>(undefined);

  const copy = useCallback(async () => {
    if (!value) {
      return;
    }
    try {
      await navigator.clipboard.writeText(value);
    } catch {
      // Clipboard API can be unavailable (permissions / insecure context).
      const area = document.createElement("textarea");
      area.value = value;
      document.body.appendChild(area);
      area.select();
      document.execCommand("copy");
      area.remove();
    }
    setCopied(true);
    if (timer.current !== undefined) {
      window.clearTimeout(timer.current);
    }
    timer.current = window.setTimeout(() => setCopied(false), 1600);
  }, [value]);

  return (
    <button type="button" className={className} onClick={copy} title={title ?? "Copy to clipboard"}>
      {copied ? "Copied ✓" : label}
    </button>
  );
}
