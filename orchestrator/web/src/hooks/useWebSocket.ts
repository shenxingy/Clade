import { useEffect, useRef, useState } from 'react';
import type { StatusMessage } from '../lib/types';
import { withToken } from '../lib/auth';

export function useWebSocket({ sessionId, onStatus }: {
  sessionId: string | null;
  onStatus?: (msg: StatusMessage) => void;
}) {
  const [connected, setConnected] = useState(false);
  const onStatusRef = useRef(onStatus);
  onStatusRef.current = onStatus;
  useEffect(() => {
    setConnected(false);
    if (!sessionId) return;
    let disposed = false;
    let socket: WebSocket;
    let retry: ReturnType<typeof setTimeout>;
    let ping: ReturnType<typeof setInterval>;
    const connect = () => {
      const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:';
      socket = new WebSocket(withToken(`${protocol}//${location.host}/ws/status?session=${encodeURIComponent(sessionId)}`));
      socket.onopen = () => {
        if (disposed) return;
        setConnected(true);
        ping = setInterval(() => {
          if (socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'ping' }));
        }, 20_000);
      };
      socket.onmessage = event => {
        if (disposed) return;
        try {
          const msg = JSON.parse(event.data as string) as StatusMessage;
          if (msg.type === 'status' && msg.session_id === sessionId) onStatusRef.current?.(msg);
        } catch { /* Ignore malformed frames; the next snapshot replaces them. */ }
      };
      socket.onclose = () => {
        clearInterval(ping);
        if (disposed) return;
        setConnected(false);
        retry = setTimeout(connect, 3_000);
      };
      socket.onerror = () => socket.close();
    };
    connect();
    return () => {
      disposed = true;
      clearInterval(ping);
      clearTimeout(retry);
      socket.close();
    };
  }, [sessionId]);
  return { connected };
}
