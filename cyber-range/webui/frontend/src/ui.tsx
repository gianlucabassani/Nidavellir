import type React from "react";
import { useEffect, useState } from "react";
import { getJson } from "./api";
import type { Workspace } from "./types";

export function useWorkspaceData<T>(path: string) {
  const [value, setValue] = useState<T | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    getJson<T>(path, controller.signal)
      .then((payload) => setValue(payload))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted)
          setError(
            reason instanceof Error
              ? reason.message
              : "Unable to load workspace",
          );
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [path, refreshKey]);
  return {
    value,
    error,
    loading,
    refresh: () => setRefreshKey((key) => key + 1),
  };
}

export function Rune({ kind }: { kind: Workspace }) {
  const shape =
    kind === "research" ? (
      <path d="M5 21V3m0 2 14 7-14 7m14-7V3m0 9v9" />
    ) : kind === "benchmark" ? (
      <path d="m5 3 14 18M19 3 5 21M5 3h14M5 21h14" />
    ) : (
      <path d="m12 2 9 5v10l-9 5-9-5V7zM12 2v20M3 7l18 10M21 7 3 17" />
    );
  return (
    <svg
      className="rune"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      aria-hidden="true"
    >
      {shape}
    </svg>
  );
}

export function Status({ value }: { value: string }) {
  const normal = value.toLowerCase();
  const tone = [
    "active",
    "complete",
    "completed",
    "ready",
    "succeeded",
    "passed",
  ].includes(normal)
    ? "success"
    : ["failed", "error_destroying", "infrastructure_failure"].includes(normal)
      ? "danger"
      : ["pending", "deploying", "destroying", "queued", "running"].includes(
            normal,
          )
        ? "warning"
        : "muted";
  return (
    <span className={`status status-${tone}`}>
      <i aria-hidden="true" />
      {value.replaceAll("_", " ")}
    </span>
  );
}

export function formatObserved(value: string) {
  // The service stores database datetimes as naive UTC; live observation
  // timestamps already carry an offset. Interpret both consistently before
  // formatting in the operator's local time zone.
  const iso = value.replace(/^(\d{4}-\d{2}-\d{2}) (\d)/, "$1T$2");
  const date = new Date(
    /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/.test(iso) &&
      !/(?:Z|[+-]\d{2}:\d{2})$/.test(iso)
      ? `${iso}Z`
      : iso,
  );
  return Number.isNaN(date.getTime())
    ? "time unavailable"
    : new Intl.DateTimeFormat("en", {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

export function Panel({
  eyebrow,
  title,
  aside,
  children,
  className = "",
}: {
  eyebrow: string;
  title: string;
  aside?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`panel ${className}`}>
      <div className="panel-head">
        <div>
          <span className="eyebrow">{eyebrow}</span>
          <h2>{title}</h2>
        </div>
        {aside}
      </div>
      {children}
    </section>
  );
}

export function Empty({
  title,
  detail,
  action,
}: {
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      <p>{detail}</p>
      {action}
    </div>
  );
}

export function PageHead({
  overline,
  title,
  subtitle,
  observed,
  action,
  refresh,
}: {
  overline: string;
  title: string;
  subtitle: string;
  observed?: string;
  action: React.ReactNode;
  refresh?: () => void;
}) {
  return (
    <div className="page-head">
      <div>
        <span className="eyebrow">{overline}</span>
        <h1 tabIndex={-1}>{title}</h1>
        <p>{subtitle}</p>
        {observed && (
          <span className="observed">
            Last observed {formatObserved(observed)}{" "}
            {refresh && (
              <button
                type="button"
                onClick={refresh}
                aria-label="Refresh workspace data"
              >
                Refresh ↻
              </button>
            )}
          </span>
        )}
      </div>
      {action}
    </div>
  );
}

export function Loading() {
  return (
    <div className="message-panel" role="status">
      <strong>Loading workspace</strong>
      <p>Fetching current records from Nidavellir.</p>
    </div>
  );
}
export function ErrorState({
  message,
  refresh,
}: {
  message: string;
  refresh: () => void;
}) {
  return (
    <div className="message-panel error" role="alert">
      <strong>Workspace unavailable</strong>
      <p>{message}</p>
      <button className="button button-outline" type="button" onClick={refresh}>
        Try again
      </button>
    </div>
  );
}
