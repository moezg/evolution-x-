"use client";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, apiGet, apiUrl } from "./api";
import type { Job, SimState, StreamPayload } from "./types";

export interface Poll<T> {
  data: T | undefined;
  error: ApiError | Error | undefined;
  loading: boolean;
  refresh: () => void;
}

/**
 * Poll a GET endpoint. Pass `null` as path to disable. Keeps the last good data on transient errors.
 * Polling pauses while the tab is hidden.
 */
export function usePoll<T>(path: string | null, intervalMs = 2000): Poll<T> {
  const [data, setData] = useState<T>();
  const [error, setError] = useState<ApiError | Error>();
  const [loading, setLoading] = useState<boolean>(!!path);
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!path) {
      setLoading(false);
      return;
    }
    let alive = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let ctrl: AbortController | undefined;
    const run = async () => {
      if (typeof document !== "undefined" && document.hidden && intervalMs > 0) {
        timer = setTimeout(run, intervalMs);
        return;
      }
      ctrl = new AbortController();
      try {
        const d = await apiGet<T>(path, ctrl.signal);
        if (!alive) return;
        setData(d);
        setError(undefined);
      } catch (e) {
        if (!alive || (e as Error).name === "AbortError") return;
        setError(e as Error);
      } finally {
        if (alive) setLoading(false);
      }
      if (alive && intervalMs > 0) timer = setTimeout(run, intervalMs);
    };
    run();
    return () => {
      alive = false;
      if (timer) clearTimeout(timer);
      ctrl?.abort();
    };
  }, [path, intervalMs, tick]);

  return { data, error, loading, refresh };
}

/** Live state via SSE (/api/stream) with polling fallback. */
export function useLiveState(): { state: SimState | undefined; payload: StreamPayload | undefined; connected: boolean; error?: string } {
  const [payload, setPayload] = useState<StreamPayload>();
  const [connected, setConnected] = useState(false);
  const [fallback, setFallback] = useState(false);
  const poll = usePoll<SimState>(fallback ? "/api/sim/state" : null, 1000);

  useEffect(() => {
    if (typeof EventSource === "undefined") {
      setFallback(true);
      return;
    }
    let es: EventSource | null = new EventSource(apiUrl("/api/stream"));
    let failures = 0;
    es.onopen = () => {
      setConnected(true);
      failures = 0;
    };
    es.onmessage = (ev) => {
      try {
        setPayload(JSON.parse(ev.data));
        setFallback(false);
      } catch {
        /* ignore malformed frame */
      }
    };
    es.onerror = () => {
      setConnected(false);
      failures += 1;
      if (failures >= 3) {
        es?.close();
        es = null;
        setFallback(true);
      }
    };
    return () => es?.close();
  }, []);

  const state = fallback ? poll.data : payload?.state;
  return { state, payload, connected: connected || (fallback && !!poll.data), error: poll.error?.message };
}

/** Track a background job until it finishes. */
export function useJob(jobId: string | null, onDone?: (j: Job) => void): Job | undefined {
  const [job, setJob] = useState<Job>();
  const cb = useRef(onDone);
  cb.current = onDone;
  useEffect(() => {
    if (!jobId) return;
    let alive = true;
    let timer: ReturnType<typeof setTimeout>;
    const run = async () => {
      try {
        const j = await apiGet<Job>(`/api/jobs/${jobId}`);
        if (!alive) return;
        setJob(j);
        if (j.status === "finished" || j.status === "failed") {
          cb.current?.(j);
          return;
        }
      } catch {
        /* keep polling */
      }
      if (alive) timer = setTimeout(run, 1500);
    };
    run();
    return () => {
      alive = false;
      clearTimeout(timer);
    };
  }, [jobId]);
  return job;
}
