import { useEffect, useRef, useCallback } from 'react';

interface UseAdaptivePollingOptions {
  callback: () => Promise<void> | void;
  enabled: boolean;
  minIntervalMs?: number; // Minimum wait time between consecutive requests (default 3000ms = 3s)
  idleTimeoutMs?: number; // Idle timeout to stop polling when user is inactive (default 45000ms = 45s)
}

/**
 * Adaptive Hybrid Polling Hook:
 * Only sends polling requests when:
 * 1. `enabled` is true (e.g. active parsing jobs exist), AND
 * 2. The user interacts (mouse move, keyboard press, click, scroll), AND
 * 3. At least `minIntervalMs` (3 sec) has elapsed since the last request.
 * Pauses automatically if user is idle or tab is hidden.
 */
export const useAdaptivePolling = ({
  callback,
  enabled,
  minIntervalMs = 3000,
  idleTimeoutMs = 45000,
}: UseAdaptivePollingOptions) => {
  const lastRequestTimeRef = useRef<number>(0);
  const isRequestingRef = useRef<boolean>(false);
  const idleTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const isUserActiveRef = useRef<boolean>(true);
  const callbackRef = useRef(callback);
  callbackRef.current = callback;

  const triggerPoll = useCallback(async () => {
    if (!enabled || !isUserActiveRef.current || document.hidden) {
      return;
    }

    const now = Date.now();
    const elapsed = now - lastRequestTimeRef.current;

    // Enforce 3-second wait between consecutive requests
    if (elapsed < minIntervalMs) {
      return;
    }

    if (isRequestingRef.current) {
      return;
    }

    isRequestingRef.current = true;
    lastRequestTimeRef.current = now;

    try {
      await callbackRef.current();
    } catch (err) {
      console.warn('[AdaptivePolling] Polling callback error:', err);
    } finally {
      isRequestingRef.current = false;
    }
  }, [enabled, minIntervalMs]);

  useEffect(() => {
    if (!enabled) return;

    const resetIdleTimer = () => {
      isUserActiveRef.current = true;
      if (idleTimerRef.current) {
        clearTimeout(idleTimerRef.current);
      }
      idleTimerRef.current = setTimeout(() => {
        isUserActiveRef.current = false;
      }, idleTimeoutMs);
    };

    const handleUserActivity = () => {
      resetIdleTimer();
      triggerPoll();
    };

    const handleVisibilityChange = () => {
      if (!document.hidden) {
        resetIdleTimer();
        triggerPoll();
      }
    };

    // Listen to user input events
    const eventTypes = ['mousemove', 'keydown', 'mousedown', 'touchstart', 'scroll'];
    eventTypes.forEach((evt) => {
      window.addEventListener(evt, handleUserActivity, { passive: true });
    });
    document.addEventListener('visibilitychange', handleVisibilityChange);

    // Initial activity mark & initial fetch if needed
    resetIdleTimer();
    triggerPoll();

    return () => {
      eventTypes.forEach((evt) => {
        window.removeEventListener(evt, handleUserActivity);
      });
      document.removeEventListener('visibilitychange', handleVisibilityChange);
      if (idleTimerRef.current) {
        clearTimeout(idleTimerRef.current);
      }
    };
  }, [enabled, idleTimeoutMs, triggerPoll]);
};
