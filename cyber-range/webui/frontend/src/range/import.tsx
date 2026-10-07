import { useState } from "react";
import { ApiError, postJson } from "../api";
import type { TopologyData } from "../types";
import { Empty, PageHead, Panel } from "../ui";
import { TopologyPreview } from "./topology";

type Mode = "spec" | "vulhub" | "generate";
type Review = {
  valid: boolean;
  errors?: string[];
  warnings?: string[];
  suggested_id?: string;
  summary?: {
    name?: string;
    nodes?: number;
    provider_class?: string;
  };
  topology?: TopologyData["topology"];
  spec?: unknown;
};
type ImportResult = { id: string; status: string };

export function ScenarioImport() {
  const requestedMode = new URLSearchParams(window.location.search).get("mode");
  const [mode, setMode] = useState<Mode>(
    requestedMode === "vulhub" || requestedMode === "generate"
      ? requestedMode
      : "spec",
  );
  const [scenarioId, setScenarioId] = useState("");
  const [specText, setSpecText] = useState("");
  const [generatedDraft, setGeneratedDraft] = useState("");
  const [vulhubSource, setVulhubSource] = useState<"path" | "compose">("path");
  const [vulhubPath, setVulhubPath] = useState("");
  const [vulhubCompose, setVulhubCompose] = useState("");
  const [vulhubRef, setVulhubRef] = useState("master");
  const [includeAttacker, setIncludeAttacker] = useState(true);
  const [prompt, setPrompt] = useState("");
  const [providerClass, setProviderClass] = useState("container");
  const [review, setReview] = useState<Review | null>(null);
  const [reviewKey, setReviewKey] = useState("");
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");

  const specKey = JSON.stringify({
    mode,
    id: scenarioId.trim(),
    spec: specText.trim(),
  });
  const vulhubBody = {
    ...(vulhubSource === "path"
      ? { path: vulhubPath.trim() }
      : { compose: vulhubCompose.trim() }),
    ref: vulhubRef.trim() || "master",
    include_attacker: includeAttacker,
    id: scenarioId.trim() || null,
  };
  const currentKey =
    mode === "vulhub" ? JSON.stringify({ mode, ...vulhubBody }) : specKey;
  const reviewed = review?.valid === true && reviewKey === currentKey;

  function selectMode(next: Mode) {
    setMode(next);
    setReview(null);
    setReviewKey("");
    setMessage("");
    const url = new URL(window.location.href);
    url.searchParams.set("mode", next);
    window.history.replaceState(null, "", url);
  }

  async function preview() {
    if (pending) return;
    if (
      mode === "vulhub" &&
      !(vulhubSource === "path" ? vulhubPath : vulhubCompose).trim()
    ) {
      setMessage(
        vulhubSource === "path"
          ? "Enter a Vulhub environment path."
          : "Paste a Compose spec.",
      );
      return;
    }
    if (mode !== "vulhub" && !specText.trim()) {
      setMessage("Paste or generate a scenario spec first.");
      return;
    }
    setPending(true);
    setMessage("");
    setReview(null);
    setReviewKey("");
    try {
      const result =
        mode === "vulhub"
          ? await postJson<Review>("/api/scenarios/import/vulhub", {
              ...vulhubBody,
              dry_run: true,
            })
          : await postJson<Review>("/api/scenarios/preview", {
              spec: specText.trim(),
            });
      setReview(result);
      setReviewKey(currentKey);
      if (!result.valid) setMessage("The service rejected this scenario spec.");
      if (!scenarioId && result.suggested_id) {
        setScenarioId(result.suggested_id);
        setReviewKey(
          mode === "vulhub"
            ? JSON.stringify({ mode, ...vulhubBody, id: result.suggested_id })
            : JSON.stringify({
                mode,
                id: result.suggested_id,
                spec: specText.trim(),
              }),
        );
      }
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Preview failed");
    } finally {
      setPending(false);
    }
  }

  async function generate() {
    if (pending) return;
    if (!prompt.trim()) {
      setMessage("Describe the scenario before generating it.");
      return;
    }
    setPending(true);
    setMessage("");
    setReview(null);
    setReviewKey("");
    try {
      const result = await postJson<Review>("/api/scenarios/generate", {
        prompt: prompt.trim(),
        provider_class: providerClass,
      });
      if (!result.valid || !result.spec) {
        setReview(result);
        setMessage(
          "The model did not produce a valid scenario. Revise the prompt and try again.",
        );
        return;
      }
      const draft = JSON.stringify(result.spec, null, 2);
      setSpecText(draft);
      setGeneratedDraft(draft);
      setReview(result);
      const nextId = scenarioId || result.suggested_id || "";
      if (!scenarioId && result.suggested_id)
        setScenarioId(result.suggested_id);
      setReviewKey(JSON.stringify({ mode, id: nextId, spec: draft.trim() }));
    } catch (reason) {
      setMessage(
        reason instanceof ApiError && reason.status === 409
          ? "Connect an operator model in Settings before generating a scenario."
          : reason instanceof Error
            ? reason.message
            : "Generation failed",
      );
    } finally {
      setPending(false);
    }
  }

  async function importPack() {
    if (!reviewed || pending) return;
    setPending(true);
    setMessage("");
    try {
      const result =
        mode === "vulhub"
          ? await postJson<ImportResult>("/api/scenarios/import/vulhub", {
              ...vulhubBody,
              dry_run: false,
            })
          : await postJson<ImportResult>("/api/scenarios/import", {
              spec: specText.trim(),
              id: scenarioId.trim() || null,
              overwrite: false,
            });
      if (!result.id)
        throw new Error("The service did not return a scenario id.");
      window.location.assign(
        `/console/scenarios?id=${encodeURIComponent(result.id)}`,
      );
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Import failed");
    } finally {
      setPending(false);
    }
  }

  return (
    <>
      <div className="arena-return">
        <a href="/console/scenarios">← Scenario library</a>
        <span>/</span>
        <span>Import</span>
      </div>
      <PageHead
        overline="CYBER RANGE / AUTHORING"
        title="Import a scenario"
        subtitle="Validate a topology before saving it. Import never launches an arena."
        observed={undefined}
        action={null}
      />
      <div className="scenario-author-modes" aria-label="Scenario source">
        {(
          [
            ["spec", "Paste spec"],
            ["vulhub", "Vulhub"],
            ["generate", "Generate"],
          ] as const
        ).map(([item, label]) => (
          <button
            type="button"
            key={item}
            className={mode === item ? "selected" : ""}
            aria-pressed={mode === item}
            onClick={() => selectMode(item)}
          >
            {label}
          </button>
        ))}
      </div>
      <div className="scenario-author-grid">
        <Panel
          eyebrow="01 / SOURCE"
          title={
            mode === "spec"
              ? "Pasted topology"
              : mode === "vulhub"
                ? "Vulhub environment"
                : "Model draft"
          }
        >
          {mode === "spec" && (
            <p className="scenario-description">
              Paste a Nidavellir v3 YAML or JSON spec. The service checks
              schema, images and topology before the pack can be saved.
            </p>
          )}
          {mode === "vulhub" && (
            <p className="scenario-description">
              Convert a Vulhub Docker environment into a reusable pack. Use a
              repository path or paste Compose YAML for an offline import.
            </p>
          )}
          {mode === "generate" && (
            <p className="scenario-description">
              Your connected model drafts a topology. Review its spec, edit it,
              and validate again before saving. No scenario is deployed here.
            </p>
          )}
          <div className="scenario-author-form">
            {mode === "vulhub" && (
              <>
                <fieldset>
                  <legend>Source</legend>
                  <label>
                    <input
                      type="radio"
                      checked={vulhubSource === "path"}
                      onChange={() => setVulhubSource("path")}
                    />{" "}
                    Repository path
                  </label>
                  <label>
                    <input
                      type="radio"
                      checked={vulhubSource === "compose"}
                      onChange={() => setVulhubSource("compose")}
                    />{" "}
                    Pasted Compose
                  </label>
                </fieldset>
                {vulhubSource === "path" ? (
                  <label>
                    Environment path
                    <input
                      value={vulhubPath}
                      onChange={(event) => setVulhubPath(event.target.value)}
                      placeholder="weblogic/CVE-2017-10271"
                      maxLength={240}
                    />
                  </label>
                ) : (
                  <label>
                    Docker Compose YAML
                    <textarea
                      value={vulhubCompose}
                      onChange={(event) => setVulhubCompose(event.target.value)}
                      rows={12}
                      spellCheck={false}
                      maxLength={200000}
                      placeholder="services:\n  web:\n    image: nginx:1.27"
                    />
                  </label>
                )}
                <label>
                  Git ref
                  <input
                    value={vulhubRef}
                    onChange={(event) => setVulhubRef(event.target.value)}
                    maxLength={120}
                    disabled={vulhubSource === "compose"}
                  />
                </label>
                <label className="scenario-author-check">
                  <input
                    type="checkbox"
                    checked={includeAttacker}
                    onChange={(event) =>
                      setIncludeAttacker(event.target.checked)
                    }
                  />
                  Add an attacker foothold
                </label>
              </>
            )}
            {mode === "generate" && (
              <>
                <label>
                  Scenario brief
                  <textarea
                    value={prompt}
                    onChange={(event) => setPrompt(event.target.value)}
                    rows={4}
                    maxLength={4000}
                    placeholder="An isolated web service and a contained attacker foothold…"
                  />
                </label>
                <label>
                  Provider class
                  <select
                    value={providerClass}
                    onChange={(event) => setProviderClass(event.target.value)}
                  >
                    <option value="container">Container · Docker-local</option>
                    <option value="any">Any · review before launch</option>
                    <option value="vm">VM · no verified local launch</option>
                  </select>
                </label>
                <button
                  type="button"
                  className="button button-outline"
                  disabled={pending}
                  onClick={() => void generate()}
                >
                  {pending ? "Generating…" : "Generate draft ↗"}
                </button>
                {message.includes("Connect an operator model") && (
                  <a className="inline-action" href="/console/settings">
                    Open model settings ↗
                  </a>
                )}
              </>
            )}
            {mode !== "vulhub" && (
              <label>
                {mode === "generate"
                  ? "Generated spec · review and edit"
                  : "Scenario spec · YAML or JSON"}
                <textarea
                  value={specText}
                  onChange={(event) => setSpecText(event.target.value)}
                  rows={15}
                  spellCheck={false}
                  maxLength={200000}
                  placeholder={
                    mode === "spec"
                      ? "schema: nidavellir/v3\nname: my-scenario\nnetwork:\n  segments: [{name: lab}]"
                      : "Generate a draft to review here."
                  }
                />
              </label>
            )}
            {mode === "generate" &&
              generatedDraft &&
              specText !== generatedDraft && (
                <details className="scenario-original-draft">
                  <summary>Compare with original model draft</summary>
                  <pre>{generatedDraft}</pre>
                </details>
              )}
            <label>
              Scenario id · optional
              <input
                value={scenarioId}
                onChange={(event) => setScenarioId(event.target.value)}
                pattern="[a-z0-9][a-z0-9_-]{0,63}"
                maxLength={64}
                placeholder="Derived from the spec"
              />
            </label>
            <div className="scenario-author-actions">
              <button
                type="button"
                className="button button-outline"
                disabled={pending}
                onClick={() => void preview()}
              >
                {pending ? "Checking…" : "Validate & preview"}
              </button>
              <button
                type="button"
                className="button button-gold"
                disabled={!reviewed || pending}
                onClick={() => void importPack()}
              >
                {pending ? "Saving…" : "Import reviewed pack ↗"}
              </button>
            </div>
          </div>
          {message && (
            <p className="form-error" role="alert">
              {message}
            </p>
          )}
        </Panel>
        <Panel
          eyebrow="02 / REVIEW"
          title={review?.summary?.name || "Topology preview"}
        >
          {review ? (
            <div className="scenario-review">
              <div className="scenario-review-status" role="status">
                <strong>
                  {review.valid ? "Valid spec" : "Validation failed"}
                </strong>
                {review.summary && (
                  <span>
                    {review.summary.nodes} nodes ·{" "}
                    {review.summary.provider_class}
                  </span>
                )}
              </div>
              {review.errors?.length ? (
                <ul className="scenario-review-errors">
                  {review.errors.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : null}
              {review.warnings?.length ? (
                <ul className="scenario-review-warnings">
                  {review.warnings.map((item, index) => (
                    <li key={index}>{item}</li>
                  ))}
                </ul>
              ) : null}
              {review.topology && (
                <TopologyPreview topology={review.topology} />
              )}
              {review.valid && !reviewed && (
                <p className="state-note">
                  Source changed after review. Validate again before importing.
                </p>
              )}
              {reviewed && (
                <p className="state-note">
                  The reviewed pack can now be imported. Launch remains a
                  separate action.
                </p>
              )}
            </div>
          ) : (
            <Empty
              title="No review yet"
              detail="Validate the source to inspect topology, warnings and the proposed scenario id."
            />
          )}
        </Panel>
      </div>
    </>
  );
}
