import { useCallback, useEffect, useRef, useState } from "react";
import { getStoredToken } from "../api/client";
import type { SseRequestEvent } from "../api/types";

type ConnectionState = "connecting" | "live" | "reconnecting" | "failed";

interface UseSseOptions {
  enabled?: boolean;
  onEvent: (event: SseRequestEvent) => void;
}

const RECONNECT_BASE_MS = 1000;
const RECONNECT_MAX_MS = 10_000;

/**
 * Live request feed via Server-Sent Events.
 *
 * Uses fetch (not EventSource) so the admin token travels in the
 * Authorization header instead of the URL. Reconnects with capped backoff;
 * stops when the component unmounts.
 */
export function useSse(
  endpointId: number | null,
  { enabled = true, onEvent }: UseSseOptions,
): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  const onEventRef = useRef(onEvent);
  onEventRef.current = onEvent;

  useEffect(() => {
    if (endpointId === null || !enabled) {
      return;
    }

    let cancelled = false;
    const controller = new AbortController();
    let attempt = 0;
    let reconnectTimer: number | undefined;

    const connect = async (): Promise<void> => {
      setState(attempt === 0 ? "connecting" : "reconnecting");
      try {
        const response = await fetch(`/api/endpoints/${endpointId}/events`, {
          headers: { Authorization: `Bearer ${getStoredToken()}` },
          signal: controller.signal,
        });
        if (!response.ok || !response.body) {
          throw new Error(`SSE status ${response.status}`);
        }
        attempt = 0;
        setState("live");

        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
          const { done, value } = await reader.read();
          if (cancelled) {
            return;
          }
          if (done) {
            throw new Error("stream closed");
          }
          buffer += decoder.decode(value, { stream: true });
          const events = buffer.split("\n\n");
          buffer = events.pop() ?? "";
          for (const chunk of events) {
            let eventName = "";
            let data = "";
            for (const line of chunk.split("\n")) {
              if (line.startsWith("event:")) {
                eventName = line.slice(6).trim();
              } else if (line.startsWith("data:")) {
                data += line.slice(5).trim();
              }
            }
            if (eventName === "request" && data) {
              try {
                onEventRef.current(JSON.parse(data) as SseRequestEvent);
              } catch {
                // ignore malformed payloads; next event will resync
              }
            }
          }
        }
      } catch (error) {
        if (cancelled || controller.signal.aborted) {
          return;
        }
        attempt += 1;
        const delay = Math.min(RECONNECT_BASE_MS * 2 ** attempt, RECONNECT_MAX_MS);
        setState("reconnecting");
        reconnectTimer = window.setTimeout(() => {
          if (!cancelled) {
            void connect();
          }
        }, delay);
      }
    };

    void connect();
    return () => {
      cancelled = true;
      controller.abort();
      if (reconnectTimer !== undefined) {
        window.clearTimeout(reconnectTimer);
      }
    };
  }, [endpointId, enabled]);

  return state;
}

/** Simple polling that pauses while the page is hidden. */
export function usePolling(callback: () => void, intervalMs: number, enabled = true): void {
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  useEffect(() => {
    if (!enabled) {
      return;
    }
    let timer: number | undefined;

    const tick = (): void => {
      if (document.visibilityState === "visible") {
        callbackRef.current();
      }
    };
    timer = window.setInterval(tick, intervalMs);
    const onVisibility = (): void => {
      if (document.visibilityState === "visible") {
        callbackRef.current();
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      if (timer !== undefined) {
        window.clearInterval(timer);
      }
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, enabled]);
}

export function useLocalStorage<T>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const raw = localStorage.getItem(key);
      return raw !== null ? (JSON.parse(raw) as T) : initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback(
    (next: T) => {
      setValue(next);
      try {
        localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // storage unavailable (private mode): value still lives in state
      }
    },
    [key],
  );
  return [value, set];
}
