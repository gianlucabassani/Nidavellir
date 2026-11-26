import { useEffect, useMemo, useRef, useState } from "react";
import { ForwardsWorkbench, ScoreWorkbench } from "./record";
import type { ArenaData } from "../types";
import { useWorkspaceData, Loading, ErrorState, ErrorBoundary } from "../ui";
import { PocWorkbench } from "./poc";
import { FindingsWorkbench } from "./findings";
import { HttpWorkbench } from "./http";
import { TerminalWorkbench } from "./terminal";
import { EvidenceWorkbench } from "./evidence";
import { SetupWorkbench } from "./setup";
import { AgentAccess } from "./access";
import { useArenaLive } from "./live";
import { Infrastructure } from "./infrastructure";
import { BrowserWorkbench } from "./browser";
import { TransferWorkbench } from "./transfer";
import { ArenaDashboard } from "./dashboard";
import { ArenaHeader } from "./header";
import "./forge.css";
import { ArenaRail, categories } from "./navigation";
import { usePaletteActions } from "../shared/palette";
import { navigate } from "../router";
import { LaunchProgress } from "./progress";
import { AgentLiveView, type SpanFeed } from "./live-view";
import type { Span } from "../types";

export function ArenaWorkspace({ id }: { id: string }) {
  const [activeTab, setActiveTab] = useState(
    new URLSearchParams(window.location.search).get("tab"),
  );
  useEffect(() => {
    const sync = () =>
      setActiveTab(new URLSearchParams(window.location.search).get("tab"));
    window.addEventListener("popstate", sync);
    return () => window.removeEventListener("popstate", sync);
  }, []);
  const { value, error, loading, refresh, mutate } =
    useWorkspaceData<ArenaData>(
      `/api/console/arenas/${encodeURIComponent(id)}`,
    );
  // OBS-05: span frames from the stream fan out to the live view.
  const spanListeners = useRef(new Set<(spans: Span[]) => void>());
  const spanFeed = useMemo<SpanFeed>(
    () => ({
      subscribe: (listener) => {
        spanListeners.current.add(listener);
        return () => spanListeners.current.delete(listener);
      },
    }),
    [],
  );
  // OBS-04: one push stream for every non-archived arena, launching included.
  const liveState = useArenaLive(id, !!value && value.state !== "destroyed", {
    refresh,
    onSpans: (spans) =>
      spanListeners.current.forEach((listener) =>
        listener(spans as unknown as Span[]),
      ),
    onState: (next) =>
      mutate((current) =>
        current ? { ...current, state: next.status } : current,
      ),
    onEvents: (events) =>
      mutate((current) => {
        if (!current) return current;
        // Merge by id, newest first: backfill may be older than the projection.
        const merged = new Map(
          current.events.map((event) => [
            event.id ?? `${event.ts}:${event.type}`,
            event,
          ]),
        );
        for (const event of events)
          merged.set(event.id, {
            id: event.id,
            type: event.type,
            ts: event.ts,
            actor: event.actor || "system",
          });
        const next = [...merged.values()]
          .sort((a, b) => (b.id ?? 0) - (a.id ?? 0))
          .slice(0, 12);
        return next.length === current.events.length &&
          next.every((event, i) => event.id === current.events[i].id)
          ? current
          : { ...current, events: next };
      }),
  });
  const [confirmAction, setConfirmAction] = useState<
    "stop" | "resume" | "reset" | "destroy" | null
  >(null);
  const [gatePending, setGatePending] = useState(false);
  const [gateMessage, setGateMessage] = useState("");
  const [gateError, setGateError] = useState("");
  const [replacementId, setReplacementId] = useState("");
  const gateDialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = gateDialog.current;
    if (confirmAction && dialog && !dialog.open) dialog.showModal();
    if (!confirmAction && dialog?.open) dialog.close();
  }, [confirmAction]);
  async function submitGateAction() {
    if (!confirmAction || !value || gatePending) return;
    setGatePending(true);
    setGateError("");
    try {
      const lifecycle =
        confirmAction === "reset" || confirmAction === "destroy";
      const response = await fetch(
        `/api/console/arenas/${encodeURIComponent(id)}/${lifecycle ? "lifecycle" : "research-gate"}`,
        {
          method: "POST",
          credentials: "same-origin",
          headers: {
            "Content-Type": "application/json",
            Accept: "application/json",
            "X-CSRFToken":
              document.querySelector<HTMLMetaElement>('meta[name="csrf-token"]')
                ?.content || "",
          },
          body: JSON.stringify(
            lifecycle
              ? { action: confirmAction }
              : {
                  action: confirmAction,
                  reason: `Operator confirmed ${confirmAction} for ${value.name}`,
                },
          ),
        },
      );
      if (response.redirected && new URL(response.url).pathname === "/login") {
        window.location.assign(
          `/login?next=${encodeURIComponent(window.location.pathname)}`,
        );
        return;
      }
      const payload: { error?: string; replacement_id?: string } =
        await response.json();
      if (!response.ok)
        throw new Error(
          payload.error || `Action rejected (${response.status})`,
        );
      setReplacementId(payload.replacement_id || "");
      setGateMessage(
        `${confirmAction[0].toUpperCase() + confirmAction.slice(1)} accepted by the service. Refreshing state…`,
      );
      setConfirmAction(null);
      refresh();
    } catch (reason) {
      setGateError(reason instanceof Error ? reason.message : "Action failed");
    } finally {
      setGatePending(false);
    }
  }
  // UX-13: the arena's tools and its primary action in the command palette.
  // Stop opens the same confirmation dialog as the button.
  usePaletteActions(`arena:${id}`, [
    ...(value?.state === "active"
      ? [
          {
            id: "stop",
            label: "Stop research on this arena…",
            hint: "asks to confirm",
            run: () => {
              setGateError("");
              setConfirmAction("stop");
            },
          },
        ]
      : []),
    {
      id: "tab:live",
      label: "Open agent live view",
      run: () => navigate(`/console/arena/${encodeURIComponent(id)}?tab=live`),
    },
    ...categories.flatMap((category) =>
      category.items.map((item) => ({
        id: `tab:${item.tab}`,
        label: `Open ${item.label}`,
        hint: category.label,
        run: () =>
          navigate(`/console/arena/${encodeURIComponent(id)}?tab=${item.tab}`),
      })),
    ),
  ]);
  if (loading && !value) return <Loading />;
  if (error && !value) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  // OBS-05: an active arena opens on the agent live view.
  const tab = activeTab || (value.state === "active" ? "live" : "forge");
  return (
    <>
      <ArenaHeader
        arena={value}
        liveState={liveState}
        onAction={(action) => {
          setGateError("");
          setConfirmAction(action);
        }}
        onChanged={refresh}
      />
      {gateMessage && (
        <p className="gate-message" role="status">
          {gateMessage}
          {replacementId && (
            <a href={`/console/arena/${encodeURIComponent(replacementId)}`}>
              {" "}
              Open replacement arena ↗
            </a>
          )}
        </p>
      )}
      <ArenaRail arena={value} tab={tab} />
      <LaunchProgress arena={value} />
      <div className="arena-layout forge-layout">
        <div className="arena-workspace-body">
          <ErrorBoundary key={tab} label="This tool">
            {tab === "live" ? (
              <AgentLiveView
                arena={value}
                feed={spanFeed}
                onStop={() => {
                  setGateError("");
                  setConfirmAction("stop");
                }}
              />
            ) : tab === "browser" ? (
              <BrowserWorkbench arena={value} />
            ) : tab === "transfer" ? (
              <TransferWorkbench arena={value} />
            ) : tab === "infrastructure" ? (
              <Infrastructure arena={value} />
            ) : tab === "access" ? (
              <AgentAccess arena={value} />
            ) : tab === "setup" ? (
              <SetupWorkbench arena={value} compactFlow />
            ) : tab === "http" ? (
              <HttpWorkbench arena={value} />
            ) : tab === "terminal" ? (
              <TerminalWorkbench arena={value} />
            ) : tab === "poc" ? (
              <PocWorkbench arena={value} />
            ) : tab === "findings" ? (
              <FindingsWorkbench arena={value} />
            ) : tab === "evidence" ? (
              <EvidenceWorkbench arena={value} />
            ) : tab === "score" ? (
              <ScoreWorkbench arena={value} />
            ) : tab === "forwards" ? (
              <ForwardsWorkbench arena={value} />
            ) : (
              <ArenaDashboard arena={value} />
            )}
          </ErrorBoundary>
        </div>
      </div>
      <dialog
        ref={gateDialog}
        className="gate-dialog"
        onClose={() => setConfirmAction(null)}
        onCancel={(event) => {
          if (gatePending) event.preventDefault();
        }}
      >
        <span className="eyebrow">CONFIRM LIFECYCLE ACTION</span>
        <h2>
          {confirmAction === "stop" || confirmAction === "resume"
            ? `${confirmAction === "stop" ? "Stop" : "Resume"} research on ${value.name}?`
            : `${confirmAction === "reset" ? "Reset" : "Destroy"} arena ${value.name}?`}
        </h2>
        <p>
          {confirmAction === "stop"
            ? "New research actions will be refused and running helpers may be cancelled. Evidence remains in the record."
            : confirmAction === "resume"
              ? "The service will reopen the arena gate if policy and budget still allow it."
              : confirmAction === "reset"
                ? "The service will create a replacement from the immutable recipe and compare its observed starting state. The original record remains available."
                : "The service will tear down this arena and cancel active helpers. Its retained record and evidence remain available."}
        </p>
        {gateError && (
          <div className="form-error" role="alert">
            {gateError}
          </div>
        )}
        <div>
          <button
            type="button"
            className="button button-outline"
            disabled={gatePending}
            onClick={() => setConfirmAction(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={`button ${confirmAction === "stop" || confirmAction === "destroy" ? "button-danger" : "button-gold"}`}
            disabled={gatePending}
            onClick={submitGateAction}
          >
            {gatePending ? "Sending…" : `Confirm ${confirmAction}`}
          </button>
        </div>
      </dialog>
    </>
  );
}
