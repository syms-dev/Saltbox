import { useEffect, useRef, useState } from 'react';

import { jobStreamUrl } from '../api/client';
import type { Job, StreamMessage } from '../api/types';

const MAX_LOG_CHARS = 2_000_000;
const RECONNECT_DELAY_MS = 1_500;

type JobStream = {
  connected: boolean;
  done: Job | null;
  text: string;
};

/**
 * Follow a job's log over the daemon's WebSocket. Reconnects until the daemon
 * sends the final record, so a flaky proxy does not leave the page stale.
 */
export function useJobStream(id: string): JobStream {
  const [text, setText] = useState('');
  const [done, setDone] = useState<Job | null>(null);
  const [connected, setConnected] = useState(false);
  const finished = useRef(false);

  useEffect(() => {
    finished.current = false;
    setText('');
    setDone(null);
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | null = null;
    let closedByUs = false;

    function connect(): void {
      setText('');
      socket = new WebSocket(jobStreamUrl(id));
      socket.onopen = () => setConnected(true);
      socket.onmessage = (event: MessageEvent<string>) => {
        const message = JSON.parse(event.data) as StreamMessage;
        if (message.type === 'log') {
          setText((previous) => {
            const next = previous + message.text;
            return next.length > MAX_LOG_CHARS ? next.slice(next.length - MAX_LOG_CHARS) : next;
          });
        } else {
          finished.current = true;
          setDone(message.job);
        }
      };
      socket.onclose = () => {
        setConnected(false);
        if (!finished.current && !closedByUs) timer = setTimeout(connect, RECONNECT_DELAY_MS);
      };
    }

    connect();
    return () => {
      closedByUs = true;
      if (timer !== null) clearTimeout(timer);
      socket?.close();
    };
  }, [id]);

  return { connected, done, text };
}
