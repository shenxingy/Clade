import { useEffect, useRef, useCallback, useState } from 'react';
import type { WsMessage, StatusMessage } from '../lib/types';

interface UseWebSocketOptions {
  sessionId: string | null;
  onStatus?: (msg: StatusMessage) => void;
}

export function useWebSocket({ sessionId, onStatus }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const [connected, setConnected] = useState(false);
  const pingRef = useRef<ReturnType<typeof setInterval>>(undefined);
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;

  const connect = useCallback(() => {
    if (!sessionId) return;
    if (wsRef.current?.readyState === WebSocket.OPEN) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const host = window.location.host;
    const ws = new WebSocket(`${protocol}//${host}/ws/status?session_id=${sessionId}`);

    ws.onopen = () => {
      setConnected(true);
      // Send ping every 20s to keep alive
      pingRef.current = setInterval(() => {
        if (ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify({ type: 'ping' }));
        }
      }, 20_000);
    };

    ws.onmessage = (event) => {
      try {
        const msg: WsMessage = JSON.parse(event.data as string);
        if (msg.type === 'status' && onStatusRef.current) {
          onStatusRef.current(msg as StatusMessage);
        }
      } catch {
        // ignore parse errors
      }
    };

    ws.onclose = () => {
      setConnected(false);
      clearInterval(pingRef.current);
      // Reconnect after 3s
      setTimeout(connect, 3_000);
    };

    ws.onerror = () => ws.close();

    wsRef.current = ws;
  }, [sessionId]);

  useEffect(() => {
    connect();
    return () => {
      clearInterval(pingRef.current);
      wsRef.current?.close();
    };
  }, [connect]);

  return { connected };
}
