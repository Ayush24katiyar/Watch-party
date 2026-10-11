/**
 * The only module that touches the WebSocket (architecture 8.2, 10.1).
 *
 * Owns: connect, the 5s join deadline, ping/pong, reconnect with backoff, and
 * the close-code policy. Components never see a socket, and all server state
 * is delivered to the reducer as a typed event.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { backoffDelay, classifyClose } from "../lib/protocol";
import type { ClientEvent, Identity, ServerEvent } from "../lib/types";

export type ConnectionStatus = "idle" | "connecting" | "open" | "reconnecting" | "closed";

export type SocketHandle = {
  status: ConnectionStatus;
  /** Last decoded server event; the reducer keys off object identity. */
  lastEvent: ServerEvent | null;
  /** Non-null when we stopped for good; drives the terminal screens. */
  fatal: { reason: string; code: number } | null;
  /** Seconds until the next reconnect attempt; 0 when not reconnecting. */
  retryIn: number;
  send: (event: ClientEvent) => void;
};

export function useRoomSocket({
  url,
  identity,
  username,
  enabled,
}: {
  url: string;
  identity: Identity | null;
  username: string;
  enabled: boolean;
}): SocketHandle {
  const [status, setStatus] = useState<ConnectionStatus>("idle");
  const [lastEvent, setLastEvent] = useState<ServerEvent | null>(null);
  const [fatal, setFatal] = useState<{ reason: string; code: number } | null>(null);
  const [retryIn, setRetryIn] = useState(0);

  const socketRef = useRef<WebSocket | null>(null);
  const queueRef = useRef<string[]>([]);
  const timerRef = useRef<number | null>(null);
  const countdownRef = useRef<number | null>(null);
  const attemptRef = useRef(0);
  const retryOnceUsedRef = useRef(false);
  const stoppedRef = useRef(false);
  // Latest values for the connect callback, which is memoized on nothing.
  const identityRef = useRef(identity);
  const usernameRef = useRef(username);
  // Latest connect, for the retry paths (a closure would capture a stale URL).
  const connectRef = useRef<() => void>(() => {});
  useEffect(() => {
    identityRef.current = identity;
    usernameRef.current = username;
  });

  const connect = useCallback(() => {
    if (stoppedRef.current || !identityRef.current) {
      return;
    }
    setStatus(attemptRef.current === 0 ? "connecting" : "reconnecting");

    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onopen = () => {
      attemptRef.current = 0;
      setStatus("open");
      setRetryIn(0);
      // join_room must be the first message (10.1).
      const current = identityRef.current;
      if (current) {
        socket.send(
          JSON.stringify({
            type: "join_room",
            payload: {
              roomId: url.split("/").pop() ?? "",
              username: usernameRef.current,
              userId: current.userId,
              token: current.token,
            },
          }),
        );
      }
      for (const queued of queueRef.current) {
        socket.send(queued);
      }
      queueRef.current = [];
    };

    socket.onmessage = (event: MessageEvent<string>) => {
      let parsed: ServerEvent;
      try {
        parsed = JSON.parse(event.data) as ServerEvent;
      } catch {
        return;
      }
      if (parsed.type === "ping") {
        socket.send(JSON.stringify({ type: "pong", payload: {} }));
        return;
      }
      // A joined room proves a healthy session: reset the one-shot 4007 budget.
      if (parsed.type === "room_joined") {
        retryOnceUsedRef.current = false;
      }
      setLastEvent(parsed);
    };

    socket.onclose = (event) => {
      if (stoppedRef.current) {
        return;
      }
      const outcome = classifyClose(event.code, retryOnceUsedRef.current);
      if (outcome.action === "retry_once") {
        retryOnceUsedRef.current = true;
        connect();
        return;
      }
      if (outcome.action === "retry") {
        scheduleReconnect();
        return;
      }
      setStatus("closed");
      setFatal({ reason: outcome.reason ?? "Connection closed.", code: event.code });
    };

    socket.onerror = () => {
      // Browsers fire error before close; let onclose drive the policy.
      socket.close();
    };
  }, [url]);

  const scheduleReconnect = useCallback(() => {
    const delay = backoffDelay(attemptRef.current);
    attemptRef.current += 1;
    setStatus("reconnecting");
    setRetryIn(Math.ceil(delay / 1000));
    countdownRef.current = window.setInterval(() => {
      setRetryIn((n) => Math.max(0, n - 1));
    }, 1000);
    timerRef.current = window.setTimeout(() => {
      if (countdownRef.current !== null) {
        window.clearInterval(countdownRef.current);
        countdownRef.current = null;
      }
      // Via ref: capturing `connect` here would retry a stale URL.
      connectRef.current();
    }, delay);
  }, []);

  useEffect(() => {
    connectRef.current = connect;
  }, [connect]);

  useEffect(() => {
    if (!enabled || !identity) {
      return;
    }
    stoppedRef.current = false;
    setFatal(null);
    connect();
    return () => {
      stoppedRef.current = true;
      if (timerRef.current !== null) {
        window.clearTimeout(timerRef.current);
      }
      if (countdownRef.current !== null) {
        window.clearInterval(countdownRef.current);
      }
      socketRef.current?.close();
    };
  }, [enabled, identity, connect]);

  const send = useCallback((event: ClientEvent) => {
    const socket = socketRef.current;
    const data = JSON.stringify(event);
    if (socket && socket.readyState === WebSocket.OPEN) {
      socket.send(data);
    } else {
      queueRef.current.push(data);
    }
  }, []);

  return { status, lastEvent, fatal, retryIn, send };
}