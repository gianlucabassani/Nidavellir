import { useState } from "react";
import type React from "react";
import { postJson } from "../api";
import { paths } from "../types";
import type { BenchmarkData } from "../types";
import {
  Empty,
  ErrorState,
  Loading,
  PageHead,
  Panel,
  useWorkspaceData,
} from "../ui";

type Kind = "builds" | "challenges" | "suites";
const kinds: Kind[] = ["builds", "challenges", "suites"];

export function BenchmarkRegistry() {
  const requested = new URLSearchParams(window.location.search).get("kind");
  const [kind, setKind] = useState<Kind>(
    kinds.includes(requested as Kind) ? (requested as Kind) : "builds",
  );
  const { value, error, loading, refresh } = useWorkspaceData<BenchmarkData>(
    paths.benchmark,
  );
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const [driver, setDriver] = useState("scripted-mcp/v1");
  const [selectedChallenges, setSelectedChallenges] = useState<string[]>([]);

  function selectKind(next: Kind) {
    setKind(next);
    const url = new URL(window.location.href);
    url.searchParams.set("kind", next);
    window.history.replaceState(null, "", url);
    setMessage("");
  }

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    const form = event.currentTarget;
    const fields = new FormData(form);
    const name = String(fields.get("name") || "").trim();
    const version = String(fields.get("version") || "").trim();
    let payload: Record<string, unknown> = { name, version };
    try {
      if (kind === "builds") {
        if (driver === "scripted-mcp/v1") {
          const plan: unknown = JSON.parse(String(fields.get("plan") || ""));
          if (!Array.isArray(plan) || !plan.length || plan.length > 20)
            throw new Error(
              "Provide a JSON array with 1–20 scripted MCP steps.",
            );
          payload = { ...payload, driver, plan };
        } else {
          payload = {
            ...payload,
            driver,
            goal: String(fields.get("goal") || "").trim(),
          };
        }
      } else if (kind === "challenges") {
        payload = {
          ...payload,
          source_arena_id: String(fields.get("source_arena_id") || ""),
          label: "calibration",
        };
      } else {
        const seeds = String(fields.get("seeds") || "")
          .split(",")
          .map((item) => Number(item.trim()));
        if (seeds.some((seed) => !Number.isInteger(seed)))
          throw new Error("Seeds must be whole numbers.");
        payload = {
          ...payload,
          challenge_ids: selectedChallenges,
          seeds,
          action_cap: Number(fields.get("action_cap")),
          deadline_seconds: Number(fields.get("deadline_seconds")),
        };
      }
      setPending(true);
      setMessage("");
      await postJson(`/api/console/benchmark/${kind}`, payload);
      setMessage(
        `${kind === "builds" ? "Build" : kind === "challenges" ? "Challenge" : "Suite"} registered. The pinned record is available below.`,
      );
      form.reset();
      setSelectedChallenges([]);
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Registration failed",
      );
    } finally {
      setPending(false);
    }
  }

  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  const records =
    kind === "builds"
      ? value.builds
      : kind === "challenges"
        ? value.challenges
        : value.suites;
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=benchmark">← Benchmark</a>
        <span>/</span>
        <span>Registry</span>
      </div>
      <PageHead
        overline="BENCHMARK / PINNED MATERIAL"
        title="Evaluation registry"
        subtitle="Register versioned builds, source-backed calibration challenges, and matched suites."
        observed={value.observed_at}
        action={
          <a className="button button-outline" href="/console/evaluations/new">
            New comparison ↗
          </a>
        }
        refresh={refresh}
      />
      <div className="scope-note">
        <strong>Calibration material</strong>
        <span>
          Public synthetic fixtures and scripted drivers verify the workbench.
          Results do not establish held-out capability.
        </span>
        <b>SERVICE PINNED</b>
      </div>
      <nav className="registry-tabs" aria-label="Evaluation registry sections">
        {kinds.map((item) => (
          <button
            key={item}
            type="button"
            aria-current={kind === item ? "page" : undefined}
            onClick={() => selectKind(item)}
          >
            {item[0].toUpperCase() + item.slice(1)} <b>{value[item].length}</b>
          </button>
        ))}
      </nav>
      <div className="registry-work-grid">
        <Panel
          eyebrow="01 / REGISTER"
          title={
            kind === "builds"
              ? "Agent build"
              : kind === "challenges"
                ? "Calibration challenge"
                : "Matched suite"
          }
        >
          <form className="registry-form" onSubmit={submit}>
            <p>
              {kind === "builds"
                ? "Pin a complete driver configuration. Scripted plans contain 1–20 supported MCP steps."
                : kind === "challenges"
                  ? "Select an active Docker-local arena with a reproducible reset and observed starting state. The service verifies eligibility."
                  : "Group 1–8 registered challenges over 3–20 matched seeds. The same suite runs for baseline and candidate."}
            </p>
            <div className="registry-form-pair">
              <label>
                Name
                <input
                  name="name"
                  required
                  maxLength={100}
                  placeholder={
                    kind === "builds"
                      ? "Authorization agent"
                      : kind === "challenges"
                        ? "Authorization calibration"
                        : "Grant regression"
                  }
                />
              </label>
              <label>
                Version
                <input
                  name="version"
                  required
                  maxLength={100}
                  placeholder="v1"
                />
              </label>
            </div>
            {kind === "builds" && (
              <>
                <label>
                  Driver
                  <select
                    value={driver}
                    onChange={(event) => setDriver(event.target.value)}
                  >
                    <option value="scripted-mcp/v1">Scripted MCP / v1</option>
                    <option value="model-mcp/v1">Model MCP / v1</option>
                  </select>
                </label>
                {driver === "scripted-mcp/v1" ? (
                  <label>
                    Script plan · JSON
                    <textarea
                      name="plan"
                      required
                      rows={9}
                      spellCheck={false}
                      defaultValue={
                        '[\n  {"tool": "get_briefing", "args": {}}\n]'
                      }
                    />
                  </label>
                ) : (
                  <label>
                    Agent goal
                    <textarea
                      name="goal"
                      required
                      rows={5}
                      maxLength={500}
                      placeholder="Investigate the authorization boundary and report reproducible findings."
                    />
                  </label>
                )}
                <small>
                  {driver === "model-mcp/v1"
                    ? "Requires an operator model connection. The service pins the provider, model, and scaffold."
                    : "The service validates allowed tools and assigns the arena to each trial."}
                </small>
              </>
            )}
            {kind === "challenges" && (
              <>
                <label>
                  Source arena
                  <select name="source_arena_id" required defaultValue="">
                    <option value="" disabled>
                      Choose an active Docker-local arena
                    </option>
                    {value.source_arenas.map((arena) => (
                      <option key={arena.id} value={arena.id}>
                        {arena.name} · {arena.id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                </label>
                {!value.source_arenas_available && (
                  <small>
                    Source arena list is temporarily unavailable. Refresh after
                    the arena service recovers.
                  </small>
                )}
                <div className="registry-fixed-label">
                  <strong>Leakage label</strong>
                  <span>Calibration · public/known material</span>
                </div>
              </>
            )}
            {kind === "suites" && (
              <>
                <fieldset>
                  <legend>Challenges</legend>
                  {value.challenges.length ? (
                    value.challenges.map((item) => (
                      <label className="registry-check" key={item.id}>
                        <input
                          type="checkbox"
                          checked={selectedChallenges.includes(item.id)}
                          onChange={(event) =>
                            setSelectedChallenges(
                              event.target.checked
                                ? [...selectedChallenges, item.id]
                                : selectedChallenges.filter(
                                    (id) => id !== item.id,
                                  ),
                            )
                          }
                        />
                        <span>
                          {item.name}{" "}
                          <small>
                            {item.version} · {item.label}
                          </small>
                        </span>
                      </label>
                    ))
                  ) : (
                    <small>Register a calibration challenge first.</small>
                  )}
                </fieldset>
                <label>
                  Matched seeds
                  <input
                    name="seeds"
                    required
                    defaultValue="1, 2, 3, 4, 5"
                    placeholder="1, 2, 3, 4, 5"
                  />
                </label>
                <div className="registry-form-pair">
                  <label>
                    Action cap
                    <input
                      type="number"
                      name="action_cap"
                      required
                      min={1}
                      max={10000}
                      defaultValue={100}
                    />
                  </label>
                  <label>
                    Deadline · seconds
                    <input
                      type="number"
                      name="deadline_seconds"
                      required
                      min={60}
                      max={1800}
                      defaultValue={600}
                    />
                  </label>
                </div>
              </>
            )}
            {message && (
              <p className="poc-message" role="status">
                {message}
              </p>
            )}
            <div className="registry-form-foot">
              <span>Registration is immutable and checked by the service.</span>
              <button
                className="button button-gold"
                disabled={
                  pending ||
                  (kind === "suites" && !selectedChallenges.length) ||
                  (kind === "challenges" && !value.source_arenas.length)
                }
              >
                {pending
                  ? "Registering…"
                  : `Register ${kind === "builds" ? "build" : kind === "challenges" ? "challenge" : "suite"} ↗`}
              </button>
            </div>
          </form>
        </Panel>
        <Panel
          eyebrow="02 / RECORDS"
          title={
            kind === "builds"
              ? "Pinned builds"
              : kind === "challenges"
                ? "Versioned challenges"
                : "Matched suites"
          }
          aside={
            <button type="button" className="subtle-link" onClick={refresh}>
              Refresh ↻
            </button>
          }
        >
          {records.length ? (
            <div className="registry-record-list">
              {records.map((record) => (
                <div key={record.id} className="registry-record">
                  <strong>{record.name}</strong>
                  <small>
                    {record.version} ·{" "}
                    {"driver" in record
                      ? record.driver
                      : "label" in record
                        ? record.label
                        : `${record.challenge_count} challenges · ${record.seed_count} seeds`}
                  </small>
                  <code>{record.id}</code>
                </div>
              ))}
            </div>
          ) : (
            <Empty
              title="No records registered"
              detail="Create the first immutable record with the form at left."
            />
          )}
        </Panel>
      </div>
    </>
  );
}
