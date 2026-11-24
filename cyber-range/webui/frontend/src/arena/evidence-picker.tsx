import { useEffect, useId, useMemo, useState } from "react";
import { useWorkspaceData } from "../ui";

// UX-06: pick evidence from the arena's own records instead of pasting a
// digest. Pasting stays available as a fallback.
type Transaction = {
  digest: string;
  method: string | null;
  path: string | null;
  status: number | null;
  node: string | null;
  ts: string | null;
  actor: string | null;
};
type Artifact = {
  digest: string;
  kind: string | null;
  node: string | null;
  bytes: number | null;
  ts: string | null;
  actor: string | null;
};
type Candidates = { transactions: Transaction[]; artifacts: Artifact[] };
type Option = {
  digest: string;
  kind: "transaction" | "artifact";
  label: string;
  detail: string;
};

function options(data: Candidates | null, kinds: Option["kind"][]): Option[] {
  if (!data) return [];
  const result: Option[] = [];
  if (kinds.includes("transaction"))
    for (const item of data.transactions)
      result.push({
        digest: item.digest,
        kind: "transaction",
        label: `${item.method || "HTTP"} ${item.path || "/"} → ${item.status ?? "?"}`,
        detail: [item.node, item.actor, item.digest.slice(-12)]
          .filter(Boolean)
          .join(" · "),
      });
  if (kinds.includes("artifact"))
    for (const item of data.artifacts)
      result.push({
        digest: item.digest,
        kind: "artifact",
        label: `${item.kind || "artifact"}${item.node ? ` from ${item.node}` : ""}`,
        detail: [
          item.bytes != null ? `${item.bytes} B` : "",
          item.actor,
          item.digest.slice(-12),
        ]
          .filter(Boolean)
          .join(" · "),
      });
  return result;
}

export function useEvidenceCandidates(arenaId: string, liveKey: string) {
  const data = useWorkspaceData<Candidates>(
    `/api/console/arenas/${encodeURIComponent(arenaId)}/evidence-candidates`,
  );
  const { refresh } = data;
  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [liveKey]);
  return data;
}

export function EvidencePicker({
  label,
  candidates,
  kinds,
  multiple,
  value,
  onChange,
}: {
  label: string;
  candidates: Candidates | null;
  kinds: Option["kind"][];
  multiple: boolean;
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [query, setQuery] = useState("");
  const [manual, setManual] = useState("");
  const searchId = useId();
  const all = useMemo(() => options(candidates, kinds), [candidates, kinds]);
  const known = new Set(all.map((item) => item.digest));
  const needle = query.trim().toLowerCase();
  const shown = all
    .filter(
      (item) =>
        !needle ||
        `${item.label} ${item.detail} ${item.digest}`
          .toLowerCase()
          .includes(needle),
    )
    .slice(0, 50);
  // Digests set outside the list (URL prefill, paste) stay visible and removable.
  const extra = value.filter((digest) => !known.has(digest));
  function toggle(digest: string, on: boolean) {
    if (!multiple) onChange(on ? [digest] : []);
    else
      onChange(
        on
          ? [...new Set([...value, digest])]
          : value.filter((d) => d !== digest),
      );
  }
  return (
    <fieldset className="evidence-picker">
      <legend>{label}</legend>
      <label htmlFor={searchId} className="visually-hidden">
        Search {label.toLowerCase()}
      </label>
      <input
        id={searchId}
        type="search"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        placeholder="Search method, path, status, node or digest"
      />
      <ul role="list">
        {shown.map((item) => (
          <li key={item.digest}>
            <label>
              <input
                type={multiple ? "checkbox" : "radio"}
                name={multiple ? undefined : `pick-${searchId}`}
                checked={value.includes(item.digest)}
                onChange={(event) => toggle(item.digest, event.target.checked)}
              />
              <span>
                <strong>{item.label}</strong>
                <small>
                  {item.kind === "transaction"
                    ? "HTTP transaction"
                    : "Artifact"}{" "}
                  · {item.detail}
                </small>
              </span>
            </label>
          </li>
        ))}
        {!shown.length && (
          <li className="evidence-picker-empty">
            {all.length
              ? "No record matches this search."
              : "This arena has no recorded evidence yet. Capture a request or save a diff first."}
          </li>
        )}
      </ul>
      {extra.map((digest) => (
        <p className="evidence-picker-extra" key={digest}>
          <code>{digest}</code>{" "}
          <button type="button" onClick={() => toggle(digest, false)}>
            Remove
          </button>
        </p>
      ))}
      <details>
        <summary>Paste a digest instead</summary>
        <div className="evidence-picker-paste">
          <input
            value={manual}
            onChange={(event) => setManual(event.target.value)}
            placeholder="sha256:…"
            aria-label={`Paste a digest for ${label.toLowerCase()}`}
          />
          <button
            type="button"
            className="button button-outline"
            disabled={!/^sha256:[0-9a-f]{64}$/.test(manual.trim())}
            aria-describedby={`${searchId}-paste-why`}
            onClick={() => {
              toggle(manual.trim(), true);
              setManual("");
            }}
          >
            Add
          </button>
          <small id={`${searchId}-paste-why`}>
            A digest is sha256: followed by 64 hex characters.
          </small>
        </div>
      </details>
    </fieldset>
  );
}
