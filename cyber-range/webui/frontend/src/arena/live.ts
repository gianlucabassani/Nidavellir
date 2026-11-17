import { useEffect, useRef, useState } from "react";

export function useArenaLive(
  id: string,
  enabled: boolean,
  refresh: () => void,
) {
  const refreshRef = useRef(refresh);
  refreshRef.current = refresh;
  const [state, setState] = useState<"live" | "reconnecting" | "archive">(
    enabled ? "reconnecting" : "archive",
  );
  useEffect(() => {
    if (!enabled) {
      setState("archive");
      return;
    }
    let lastRefresh = 0;
    let fallback: ReturnType<typeof setInterval> | undefined;
    const stream = new EventSource(
      `/api/arenas/${encodeURIComponent(id)}/stream`,
    );
    const update = () => {
      const now = Date.now();
      if (now - lastRefresh >= 500) {
        lastRefresh = now;
        refreshRef.current();
      }
    };
    stream.onopen = () => {
      setState("live");
      if (fallback) {
        clearInterval(fallback);
        fallback = undefined;
      }
      update();
    };
    stream.addEventListener("state", update);
    stream.addEventListener("activity", update);
    stream.onerror = () => {
      setState("reconnecting");
      if (!fallback) fallback = setInterval(() => refreshRef.current(), 15000);
    };
    return () => {
      stream.close();
      if (fallback) clearInterval(fallback);
    };
  }, [id, enabled]);
  return state;
}
