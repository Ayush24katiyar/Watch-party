import { useCallback, useEffect, useRef, useState } from "react";
import { NO_RETRY_CLOSE_CODES, RETRY_ONCE_CLOSE_CODES } from "../lib/protocol";

export type ConnectionStatus = "connecting" | "open" | "closed";

const BASE_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 15_000;

/** Exponential backoff with jitter: 1s -> 2s -> 4s -> ... capped at 15s (16). */
function backoffDelay(attempt: number): number {
  const exponential = Math.min(MAX_BACKOFF_MS, BASE_BACKOFF_MS * 2 ** attempt);
  return exponential / 2 + Math.random() * (exponential / 2);
}

export type WebSocketHandle = {
  status: ConnectionStatus;
  /** Set after a terminal (no-retry) close or an exhausted retry. */
  closeInfo: { code: number; reason: string } | null;
  /** Most recent server event (ping/echo/error/room_joined/...). */
  lastEvent: { type: string; payload: Record<string, unknown> } | null;
  send: (event: { type: string; payload: Record<string, unknown> }) => void;
};

export function useWebSocket(url: string): WebSocketHandle {
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const [closeInfo, setCloseInfo] = useState<{ code: number; reason: string } | null>(null);
  const [lastEvent, setLastEvent] = useState<{ type: string; payload: Record<string, unknown> } | null>(
    null,
  );

  const socketRef = useRef<WebSocket | null>(null);
  const queueRef = useRef<string[]>([]);
  const timerRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const retriedOnceRef = useRef(false);
  const cancelledRef = useRef(false);

  const connect = useCallback(() => {
    if (cancelledRef.current) {
      return;
    }
    setStatus("connecting");
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setStatus("open");
      // Flush anything queued while connecting.
      for (const queued of queueRef.current) {
        socket.send(queued);
      }
      queueRef.current = [];
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      let parsed: { type?: string; payload?: Record<string, unknown> };
      try {
        parsed = JSON.parse(event.data) as typeof parsed;
      } catch {
        return;
      }
      setLastEvent({ type: parsed.type ?? "", payload: parsed.payload ?? {} });
      if (parsed.type === "ping") {
        // Reply to the server heartbeat (10.6).
        socket.send(JSON.stringify({ type: "pong", payload: {} }));
      }
      // Other events are surfaced through lastEvent.
    };

    socket.onclose = (event: CloseEvent) => {
      if (cancelledRef.current) {
        return;
      }
      setCloseInfo({ code: event.code, reason: event.reason });
      if (NO_RETRY_CLOSE_CODES.has(event.code)) {
        setStatus("closed"); // terminal: show the close code, do not retry
        return;
      }
      if (RETRY_ONCE_CLOSE_CODES.has(event.code)) {
        if (!retriedOnceRef.current) {
          retriedOnceRef.current = true;
          connect();
          return;
        }
        setStatus("closed");
        return;
      }
      // Network drop, 1001 (incl. heartbeat timeout), 1012 restart, 4008: back off and retry.
      setStatus("connecting");
      const delay = backoffDelay(attemptRef.current);
      attemptRef.current += 1;
      timerRef.current = window.setTimeout(connect, delay);
    };

    // Browsers fire onerror before onclose; force the close path so policy applies.
    socket.onerror = () => socket.close();
  }, [url]);

  useEffect(() => {
    cancelledRef.current = false;
    connect();
    return () => {
      cancelledRef.current = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      socketRef.current?.close();
    };
  }, [connect]);

  const send = useCallback((event: { type: string; payload: Record<string, unknown> }) => {
    const data = JSON.stringify(event);
    const socket = socketRef.current;
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(data);
    } else {
      queueRef.current.push(data);
    }
  }, []);

  return { status, closeInfo, lastEvent, send };
}
