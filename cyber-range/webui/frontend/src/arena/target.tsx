import { useState } from "react";

/**
 * A station chosen on the Forge map and handed to a tool through `?target=`.
 * The URL value is a preselection only: it is accepted when the tool can use
 * that station, it never submits anything, and the service still authorizes
 * every request.
 */
export function useMapTarget(eligible: string[]) {
  const [requested, setRequested] = useState(
    new URLSearchParams(window.location.search).get("target"),
  );
  const accepted = requested && eligible.includes(requested) ? requested : null;
  function clear() {
    setRequested(null);
    const url = new URL(window.location.href);
    if (!url.searchParams.has("target")) return;
    url.searchParams.delete("target");
    window.history.replaceState(null, "", url);
  }
  return { requested, accepted, clear };
}

export function MapTargetNotice({
  requested,
  accepted,
  tool,
}: {
  requested: string | null;
  accepted: string | null;
  tool: string;
}) {
  if (!requested) return null;
  return (
    <p className={`map-target${accepted ? "" : " refused"}`} role="status">
      {accepted ? (
        <>
          Target from map: <strong>{accepted}</strong>. The service checks
          access when you send.
        </>
      ) : (
        <>
          <strong>{requested}</strong> cannot be used by {tool}. Choose a target
          below.
        </>
      )}
    </p>
  );
}
