import { useEffect, useRef, useState } from "react";

// OBS-04: the arena's push stream. Frames are applied in place; only events that
// change derived projection data (state, phases, findings, bindings, budget)
// trigger one refetch, never a timer.
export type LiveEvent = {
  id: number;
  type: string;
  ts: string;
  actor: string;
  payload?: Record<string, unknown> | null;
};
export type LiveSpan = {
  id: number;
  span_id: string;
  parent_span_id: string | null;
  name: string;
  kind: string;
  status: string;
  actor: string;
  actor_kind: string;
  started_at: string;
  duration_ms: number | null;
};
export type LiveHandlers = {
  onState?: (state: {
    status: string;
    outputs: Record<string, unknown>;
  }) => void;
  onEvents?: (events: LiveEvent[]) => void;
  onSpans?: (spans: LiveSpan[]) => void;
  refresh: () => void;
};

const PROJECTION_EVENTS = new Set([
  "status",
  "deploy_phase",
  "finding",
  "finding_verification",
  "agent_binding",
  "agent_binding_revoked",
  "agent_binding_paused",
  "agent_binding_resumed",
  "agent_session",
  "budget_policy_revised",
  "arena_stop",
  "stop_cleared",
  "lifecycle_observation",
]);

export function useArenaLive(
  id: string,
  enabled: boolean,
  handlers: LiveHandlers,
) {
  const ref = useRef(handlers);
  ref.current = handlers;
  const [state, setState] = useState<"live" | "reconnecting" | "archive">(
    enabled ? "reconnecting" : "archive",
  );
  useEffect(() => {
    if (!enabled) {
      setState("archive");
      return;
    }
    let lastRefresh = 0;
    let pending: ReturnType<typeof setTimeout> | undefined;
    let fallback: ReturnType<typeof setInterval> | undefined;
    const refreshSoon = () => {
      // Coalesce a burst of projection-changing events into one refetch.
      if (pending) return;
      const wait = Math.max(0, 500 - (Date.now() - lastRefresh));
      pending = setTimeout(() => {
        pending = undefined;
        lastRefresh = Date.now();
        ref.current.refresh();
      }, wait);
    };
    const stream = new EventSource(
      `/api/arenas/${encodeURIComponent(id)}/stream`,
    );
    stream.onopen = () => {
      setState("live");
      if (fallback) {
        clearInterval(fallback);
        fallback = undefined;
      }
    };
    stream.addEventListener("state", (message) => {
      ref.current.onState?.(JSON.parse((message as MessageEvent).data));
    });
    stream.addEventListener("activity", (message) => {
      const events: LiveEvent[] =
        JSON.parse((message as MessageEvent).data).events || [];
      ref.current.onEvents?.(events);
      if (events.some((event) => PROJECTION_EVENTS.has(event.type)))
        refreshSoon();
    });
    stream.addEventListener("spans", (message) => {
      ref.current.onSpans?.(
        JSON.parse((message as MessageEvent).data).spans || [],
      );
    });
    stream.onerror = () => {
      // EventSource reconnects with Last-Event-ID; refresh only while it is down.
      setState("reconnecting");
      if (!fallback) fallback = setInterval(() => ref.current.refresh(), 15000);
    };
    return () => {
      stream.close();
      if (pending) clearTimeout(pending);
      if (fallback) clearInterval(fallback);
    };
  }, [id, enabled]);
  return state;
}
