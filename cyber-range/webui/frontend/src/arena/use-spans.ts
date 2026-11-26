// The arena's spans: history once, then the push stream (OBS-04). Shared by
// the Live view (the step log) and the Timeline page (the world tree).
import { useCallback, useEffect, useState } from "react";
import { getJson } from "../api";
import type { Span } from "../types";
import type { SpanFeed } from "./live-view";

export function useArenaSpans(arenaId: string, feed: SpanFeed) {
  const [spans, setSpans] = useState<Span[]>([]);
  const [loadError, setLoadError] = useState("");
  const [loaded, setLoaded] = useState(false);
  const merge = useCallback((incoming: Span[]) => {
    if (!incoming.length) return;
    setSpans((current) => {
      const last = current.length ? current[current.length - 1].id : 0;
      // Stream frames are ordered; anything not newer is already known.
      const fresh = incoming.filter((span) => span.id > last);
      if (fresh.length === incoming.length && !current.length) return incoming;
      if (!fresh.length) {
        const known = new Set(current.map((span) => span.id));
        const late = incoming.filter((span) => !known.has(span.id));
        return late.length
          ? [...current, ...late].sort((a, b) => a.id - b.id)
          : current;
      }
      return [...current, ...fresh];
    });
  }, []);
  useEffect(() => {
    let cancelled = false;
    getJson<{ spans: Span[] }>(
      `/api/console/arenas/${encodeURIComponent(arenaId)}/spans?limit=5000`,
    )
      .then((data) => {
        if (!cancelled) merge(data.spans);
      })
      .catch((reason: unknown) => {
        if (!cancelled)
          setLoadError(
            reason instanceof Error
              ? reason.message
              : "Span timeline unavailable",
          );
      })
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [arenaId, merge]);
  useEffect(() => feed.subscribe(merge), [feed, merge]);
  return { spans, loadError, loaded };
}
