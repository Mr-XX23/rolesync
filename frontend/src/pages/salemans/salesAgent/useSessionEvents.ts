import { useEffect, useEffectEvent } from 'react';
import { salesAgentApi } from '../../../api/salesAgentApi';
import type { AgentEvent } from '../../../api/salesAgentApi';

/**
 * Follows a session's live event stream (SSE).
 *
 * Reconnects itself (with backoff) and resumes after the last event it received by
 * passing it as `last_event_id`, rather than relying on the browser's automatic
 * `Last-Event-ID` header, which cross-origin requests may not be allowed to send.
 */
export function useSessionEvents(
  sessionId: string | null,
  startAfter: string | null,
  onEvent: (event: AgentEvent) => void
): void {
  const deliver = useEffectEvent((event: AgentEvent) => onEvent(event));

  useEffect(() => {
    if (!sessionId) {
      return;
    }
    let source: EventSource | null = null;
    let lastId = startAfter;
    let retry: number | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      source = new EventSource(salesAgentApi.eventsUrl(sessionId, lastId), { withCredentials: true });
      source.onopen = () => {
        attempt = 0;
      };
      source.onmessage = (message) => {
        try {
          const envelope = JSON.parse(message.data);
          lastId = message.lastEventId || lastId;
          deliver({ ...envelope, id: message.lastEventId });
        } catch {
          // ignore malformed frames
        }
      };
      source.onerror = () => {
        source?.close();
        if (closed) {
          return;
        }
        attempt += 1;
        retry = window.setTimeout(connect, Math.min(15000, 500 * 2 ** Math.min(attempt, 5)));
      };
    };

    connect();
    return () => {
      closed = true;
      window.clearTimeout(retry);
      source?.close();
    };
    // Reconnect from scratch only when the session (or its snapshot position) changes.
  }, [sessionId, startAfter]);
}
