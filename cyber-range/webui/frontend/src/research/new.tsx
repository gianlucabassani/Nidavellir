import { useRef, useState } from "react";
import { postForm, postJson } from "../api";
import type { ResearchPreview } from "../types";
import { Panel, Empty, PageHead } from "../ui";
import { SegmentMap } from "../topology/SegmentMap";

type Step = 1 | 2 | 3;
const STEPS: { title: string; detail: string }[] = [
  { title: "Target", detail: "What you stand up" },
  { title: "Consent & limits", detail: "Authority, setup, time" },
  { title: "Review & launch", detail: "Pinned identity, topology" },
];
// What the service does at each step, shown beside the form.
const STEP_NOTES: Record<Step, [string, string][]> = {
  1: [
    [
      "Resolve",
      "Git refs resolve to a commit, OCI tags to a digest, bundles to their upload digest.",
    ],
    [
      "Isolate",
      "The target gets its own network segment, separated from the host.",
    ],
    [
      "Foothold",
      "An optional attacker station joins that segment for the engagement.",
    ],
  ],
  2: [
    [
      "Authorize",
      "Nothing is configured until you confirm scope and authority.",
    ],
    [
      "Bound setup",
      "Git and bundle targets get a time-boxed, step-budgeted setup session.",
    ],
    ["Revoke egress", "Dependency downloads stop before research begins."],
  ],
  3: [
    ["Preview only", "Review resolves the target without deploying anything."],
    [
      "Pinned launch",
      "Launch uses exactly the reviewed identity; any edit needs a new review.",
    ],
    ["Time box", "The engagement clock starts when the arena is created."],
  ],
};

export function NewResearch() {
  const form = useRef<HTMLFormElement>(null);
  const simulationMode =
    document.getElementById("root")?.dataset.simulation === "true";
  const editRevision = useRef(0);
  const requested = new URLSearchParams(window.location.search).get("source");
  const [kind, setKind] = useState<"git" | "oci" | "bundle">(
    requested === "oci" || requested === "bundle" ? requested : "git",
  );
  const [bundle, setBundle] = useState<{
    digest: string;
    filename: string;
    upload_bytes: number;
  } | null>(null);
  const [preview, setPreview] = useState<ResearchPreview | null>(null);
  const [pinned, setPinned] = useState<Record<string, unknown> | null>(null);
  const [pending, setPending] = useState(false);
  const [message, setMessage] = useState("");
  const stepped =
    new URLSearchParams(window.location.search).get("layout") !== "form";
  const [step, setStep] = useState<Step>(1);
  const groups = [useRef<HTMLDivElement>(null), useRef<HTMLDivElement>(null)];
  function stepValid(index: 0 | 1) {
    const fields = groups[index].current?.querySelectorAll<
      HTMLInputElement | HTMLSelectElement
    >("input, select");
    const invalid = [...(fields || [])].find((item) => !item.checkValidity());
    if (invalid) {
      invalid.reportValidity();
      return false;
    }
    if (index === 0 && kind === "bundle" && !bundle) {
      setMessage("Upload the source bundle before continuing.");
      return false;
    }
    return true;
  }
  function goTo(next: Step) {
    if (next > step) {
      if (!stepValid(0)) return;
      if (next === 3 && !stepValid(1)) return;
    }
    setMessage("");
    setStep(next);
    if (next === 3) void review();
  }
  function requestBody() {
    const fields = new FormData(form.current!);
    const ports = String(fields.get("ports") || "")
      .split(/[\s,]+/)
      .filter(Boolean)
      .map(Number);
    return {
      target_type: kind,
      instance_id: String(fields.get("instance_id") || "").trim(),
      repo: String(fields.get("repo") || "").trim(),
      ref: String(fields.get("ref") || "").trim(),
      image: String(fields.get("image") || "").trim(),
      artifact_digest: bundle?.digest || "",
      platform: String(fields.get("platform") || "linux/amd64"),
      ports,
      include_attacker: fields.has("include_attacker"),
      authorization_basis: String(fields.get("authorization_basis") || ""),
      authorization_confirmed: fields.has("authorization_confirmed"),
      scope_note: String(fields.get("scope_note") || "").trim(),
      engagement_purpose: "research",
      participant_mode: String(fields.get("participant_mode") || "operator"),
      engagement_time_box_seconds: Number(
        fields.get("engagement_time_box_seconds") || 3600,
      ),
      setup_mode: String(fields.get("setup_mode") || "operator"),
      time_box_seconds: Number(fields.get("time_box_seconds") || 1800),
      command_budget: Number(fields.get("command_budget") || 50),
      setup_egress: fields.has("setup_egress"),
    };
  }
  async function uploadBundle() {
    const file = new FormData(form.current!).get("file");
    if (!(file instanceof File) || !file.size) {
      setMessage("Choose a .tar, .tar.gz or .tgz archive.");
      return;
    }
    const upload = new FormData();
    upload.set("file", file);
    const revision = editRevision.current;
    setPending(true);
    setMessage("");
    setBundle(null);
    setPreview(null);
    setPinned(null);
    try {
      const result = await postForm<{
        artifact?: {
          digest?: string;
          filename?: string;
          upload_bytes?: number;
        };
      }>("/api/targets/source-bundles", upload);
      if (!result.artifact?.digest)
        throw new Error("The service did not return a bundle digest.");
      if (revision !== editRevision.current) return;
      setBundle({
        digest: result.artifact.digest,
        filename: result.artifact.filename || file.name,
        upload_bytes: result.artifact.upload_bytes || file.size,
      });
      setMessage("Bundle stored by digest. Review its topology before launch.");
    } catch (reason) {
      if (revision === editRevision.current)
        setMessage(reason instanceof Error ? reason.message : "Upload failed");
    } finally {
      setPending(false);
    }
  }
  async function review() {
    if (!form.current?.reportValidity() || pending) return;
    if (kind === "bundle" && !bundle) {
      setMessage("Upload the source bundle before review.");
      return;
    }
    const body = requestBody();
    const revision = editRevision.current;
    setPending(true);
    setMessage("");
    setPreview(null);
    setPinned(null);
    try {
      const result = await postJson<ResearchPreview>(
        "/api/console/research/preview",
        body,
      );
      if (revision !== editRevision.current) return;
      setPreview(result);
      if (!result.valid) {
        setMessage(
          result.errors.join("; ") || "The target could not be reviewed.",
        );
        return;
      }
      const resolved =
        kind === "oci" ? result.runtime_ref : result.resolved_ref;
      if (!resolved) {
        setMessage("The service did not return an immutable target identity.");
        return;
      }
      if (kind === "bundle" && resolved !== bundle?.digest) {
        setMessage(
          "The reviewed bundle identity does not match the uploaded artifact.",
        );
        return;
      }
      setPinned(
        kind === "git"
          ? { ...body, ref: resolved }
          : kind === "oci"
            ? { ...body, image: resolved }
            : { ...body, artifact_digest: resolved },
      );
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Review failed");
    } finally {
      setPending(false);
    }
  }
  async function launch() {
    if (!pinned || pending) return;
    setPending(true);
    setMessage("");
    try {
      const result = await postJson<{
        instance_id?: string;
      }>("/api/console/research/launch", pinned);
      if (!result.instance_id)
        throw new Error("The service did not return an arena ID.");
      window.location.assign(
        `/console/arena/${encodeURIComponent(result.instance_id)}`,
      );
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Launch failed");
      setPending(false);
    }
  }
  return (
    <>
      <div className="arena-return">
        <a href="/console?workspace=research">← Research</a>
        <span>/</span>
        <span>New research</span>
      </div>
      <PageHead
        overline="RESEARCH / TARGET INTAKE"
        title="Start target research"
        subtitle="Resolve an authorized target, review its immutable identity and launch in isolation."
        action={
          <a className="button button-outline" href="/console/library/targets">
            Target sources ↗
          </a>
        }
      />
      <div className="scope-note">
        <strong>Boundary</strong>
        <span>
          {simulationMode
            ? "Preview resolves the target without deploying it. Launch uses the reviewed identity in the mock simulator."
            : "Preview resolves the target without deploying it. Launch uses the reviewed commit, image digest or source-bundle digest on Docker-local."}
        </span>
        <b>{simulationMode ? "MOCK" : "DOCKER-LOCAL"}</b>
      </div>
      {stepped && (
        <ol className="intake-steps" aria-label="Research setup steps">
          {STEPS.map((item, index) => {
            const number = (index + 1) as Step;
            return (
              <li
                key={item.title}
                className={
                  number === step ? "current" : number < step ? "done" : ""
                }
              >
                <button
                  type="button"
                  aria-current={number === step ? "step" : undefined}
                  disabled={number > step || pending}
                  onClick={() => goTo(number)}
                >
                  <span className="intake-step-number">
                    {number < step ? "✓" : number}
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.detail}</small>
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      )}
      <div className={stepped ? "intake-stepper-grid" : "comparison-form-grid"}>
        <form
          className="panel comparison-form"
          ref={form}
          noValidate={stepped}
          onSubmit={(event) => {
            event.preventDefault();
            if (!stepped) review();
            else if (step < 3) goTo((step + 1) as Step);
            else void launch();
          }}
          onChange={() => {
            editRevision.current += 1;
            setPreview(null);
            setPinned(null);
            setMessage("");
          }}
        >
          <div className="panel-head">
            <div>
              <span className="eyebrow">
                {stepped ? `STEP ${step} OF 3` : "01 / TARGET & CONSENT"}
              </span>
              <h2>
                {!stepped
                  ? "Research setup"
                  : step === 1
                    ? "What are you standing up?"
                    : step === 2
                      ? "Consent and limits"
                      : "Review and launch"}
              </h2>
            </div>
          </div>
          <div
            className="comparison-fields research-fields"
            ref={groups[0]}
            hidden={stepped && step !== 1}
          >
            <label>
              Target type
              <select
                value={kind}
                onChange={(event) => {
                  setKind(event.target.value as "git" | "oci" | "bundle");
                  setBundle(null);
                }}
              >
                <option value="git">Git repository</option>
                <option value="oci">Public OCI image</option>
                <option value="bundle">Local source bundle</option>
              </select>
            </label>
            <label>
              Arena name
              <input
                name="instance_id"
                required
                maxLength={40}
                pattern="[a-z0-9][a-z0-9-]{0,39}"
                placeholder="target-research"
              />
            </label>
            {kind === "git" ? (
              <>
                <label>
                  HTTPS repository
                  <input
                    name="repo"
                    required
                    type="url"
                    placeholder="https://github.com/owner/project"
                  />
                </label>
                <label>
                  Branch, tag or commit
                  <input name="ref" placeholder="main" />
                </label>
              </>
            ) : kind === "oci" ? (
              <>
                <label>
                  Public image reference
                  <input name="image" required placeholder="nginx:1.27" />
                </label>
                <label>
                  Runtime platform
                  <select name="platform">
                    <option value="linux/amd64">linux/amd64</option>
                    <option value="linux/arm64">linux/arm64</option>
                  </select>
                </label>
              </>
            ) : (
              <div className="bundle-intake">
                <label>
                  Source archive · .tar, .tar.gz or .tgz
                  <input
                    name="file"
                    type="file"
                    accept=".tar,.tar.gz,.tgz,application/x-tar,application/gzip"
                    onChange={() => setBundle(null)}
                  />
                </label>
                <button
                  type="button"
                  className="button button-outline"
                  disabled={pending}
                  onClick={() => void uploadBundle()}
                >
                  {pending ? "Uploading…" : "Upload bundle ↗"}
                </button>
                {bundle && (
                  <div className="bundle-receipt">
                    <strong>{bundle.filename}</strong>
                    <small>{bundle.upload_bytes} uploaded bytes</small>
                    <code>{bundle.digest}</code>
                  </div>
                )}
              </div>
            )}
            <label>
              Service ports
              <input name="ports" placeholder="80, 443" inputMode="numeric" />
            </label>
            <label className="form-check">
              <input name="include_attacker" type="checkbox" defaultChecked />{" "}
              Add an isolated attacker foothold
            </label>
          </div>
          <div
            className="comparison-fields research-fields"
            ref={groups[1]}
            hidden={stepped && step !== 2}
          >
            <label>
              Participant
              <select name="participant_mode">
                <option value="operator">Operator-led</option>
                <option value="mixed">Mixed</option>
                <option value="agent">Agent-led</option>
              </select>
            </label>
            <label>
              Engagement time box
              <select name="engagement_time_box_seconds">
                <option value="1800">30 minutes</option>
                <option value="3600">1 hour</option>
                <option value="7200">2 hours</option>
                <option value="14400">4 hours</option>
              </select>
            </label>
            <label>
              Authorization basis
              <select name="authorization_basis">
                <option value="public_oss">Public open-source project</option>
                <option value="owned">I own this target</option>
                <option value="authorized_assessment">
                  Explicit assessment authorization
                </option>
              </select>
            </label>
            <label>
              Scope note
              <input
                name="scope_note"
                maxLength={500}
                placeholder="Agreement, ticket or program scope"
              />
            </label>
            {(kind === "git" || kind === "bundle") && (
              <>
                <div className="form-divider">SETUP CONSENT</div>
                <label>
                  Configurator
                  <select name="setup_mode">
                    <option value="operator">Operator</option>
                    <option value="hitl">Agent proposals with approval</option>
                  </select>
                </label>
                <label>
                  Setup time (seconds)
                  <input
                    name="time_box_seconds"
                    type="number"
                    min={60}
                    max={21600}
                    defaultValue={1800}
                    required
                  />
                </label>
                <label>
                  Setup command budget
                  <input
                    name="command_budget"
                    type="number"
                    min={1}
                    max={500}
                    defaultValue={50}
                    required
                  />
                </label>
                <label className="form-check">
                  <input name="setup_egress" type="checkbox" defaultChecked />{" "}
                  Allow dependency downloads during setup; egress is revoked
                  before research
                </label>
              </>
            )}
            <label className="form-check">
              <input name="authorization_confirmed" type="checkbox" required />{" "}
              I confirm this target is in scope and I am authorized to assess it
            </label>
          </div>
          {stepped && step === 3 && (
            <div className="intake-review">
              {pending && !preview ? (
                <Empty
                  title="Reviewing target"
                  detail="Resolving the immutable identity and planned topology. Nothing is deployed."
                />
              ) : preview?.valid ? (
                <>
                  <div className="target-pin">
                    <small>IMMUTABLE IDENTITY</small>
                    <code>
                      {kind === "oci"
                        ? preview.runtime_ref
                        : preview.resolved_ref}
                    </code>
                  </div>
                  <div className="forge-workbench intake-map">
                    <div className="forge-canvas">
                      <SegmentMap
                        compact
                        nodes={preview.topology.nodes.map((node) => ({
                          name: node.name,
                          kind:
                            node.kind === "foothold" ? "foothold" : "target",
                          detail:
                            node.kind === "foothold"
                              ? "Attacker foothold"
                              : `${node.role || "Target"}${
                                  node.ports.length
                                    ? ` · ${node.ports.map((port) => `:${port}`).join(" ")}`
                                    : ""
                                }`,
                        }))}
                        segments={preview.topology.segments}
                      />
                    </div>
                  </div>
                  <div className="topology-facts">
                    <span>
                      {preview.topology.segments.length} network segments
                    </span>
                    <span>Egress {preview.topology.egress || "unknown"}</span>
                    {(kind === "git" || kind === "bundle") && (
                      <span>
                        Build {preview.introspection.build_system || "unknown"}{" "}
                        · {preview.build_plan.strategy || "manual setup"}
                      </span>
                    )}
                  </div>
                  {preview.warnings.length > 0 && (
                    <ul className="preview-warnings">
                      {preview.warnings.map((warning) => (
                        <li key={warning}>{warning}</li>
                      ))}
                    </ul>
                  )}
                </>
              ) : (
                <Empty
                  title="Review did not pass"
                  detail="Go back, correct the target or limits, and review again."
                />
              )}
            </div>
          )}
          {message && (
            <div className="form-error" role="alert">
              {message}
            </div>
          )}
          {stepped ? (
            <div className="comparison-form-foot intake-nav">
              <button
                type="button"
                className="button button-outline"
                disabled={step === 1 || pending}
                onClick={() => goTo((step - 1) as Step)}
              >
                ← Back
              </button>
              {step < 3 ? (
                <button
                  type="submit"
                  className="button button-gold"
                  disabled={pending}
                >
                  {step === 2 ? "Review target →" : "Next →"}
                </button>
              ) : (
                <button
                  type="submit"
                  className="button button-gold"
                  disabled={!pinned || pending}
                >
                  {pending ? "Working…" : "Launch research ↗"}
                </button>
              )}
            </div>
          ) : (
            <div className="comparison-form-foot">
              <span>
                Review validates the planned topology and pins the target.
                Changing a field requires a new review.
              </span>
              <button
                type="submit"
                className="button button-outline"
                disabled={pending}
              >
                {pending ? "Working…" : "Review target ↗"}
              </button>
            </div>
          )}
        </form>
        {stepped ? (
          <aside
            className="intake-notes"
            aria-label="What happens in this step"
          >
            <span className="eyebrow">HOW IT WORKS</span>
            <ol>
              {STEP_NOTES[step].map(([title, detail]) => (
                <li key={title}>
                  <strong>{title}</strong>
                  <span>{detail}</span>
                </li>
              ))}
            </ol>
            <a
              className="inline-action"
              href="/console/research/new?layout=form"
            >
              Use the single-page form ↗
            </a>
          </aside>
        ) : (
          <Panel
            eyebrow="02 / REVIEW"
            title={preview?.summary.name || "Target preview"}
            className="topology-panel"
          >
            {preview?.valid ? (
              <>
                <div className="target-pin">
                  <small>IMMUTABLE IDENTITY</small>
                  <code>
                    {kind === "oci"
                      ? preview.runtime_ref
                      : preview.resolved_ref}
                  </code>
                </div>
                <div className="topology-preview topology-real">
                  <div className="topology-grid" />
                  {preview.topology.nodes.map((node) => (
                    <div className="topology-box" key={node.name}>
                      <span>{node.kind === "foothold" ? "◈" : "⬡"}</span>
                      <strong>{node.name}</strong>
                      <small>{node.role || node.kind}</small>
                    </div>
                  ))}
                </div>
                <div className="topology-facts">
                  <span>
                    {preview.topology.segments.length} network segments
                  </span>
                  <span>Egress {preview.topology.egress || "unknown"}</span>
                </div>
                {(kind === "git" || kind === "bundle") && (
                  <p className="scenario-description">
                    Build: {preview.introspection.build_system || "unknown"} ·
                    Strategy: {preview.build_plan.strategy || "manual setup"} ·
                    Auto-build{" "}
                    {preview.build_plan.auto_build ? "enabled" : "disabled"}
                  </p>
                )}
                {preview.warnings.length > 0 && (
                  <ul className="preview-warnings">
                    {preview.warnings.map((warning) => (
                      <li key={warning}>{warning}</li>
                    ))}
                  </ul>
                )}
                <div className="comparison-form-foot">
                  <span>
                    Launch will create a new arena and start its time box.
                  </span>
                  <button
                    type="button"
                    className="button button-gold"
                    disabled={!pinned || pending}
                    onClick={launch}
                  >
                    {pending ? "Working…" : "Launch research ↗"}
                  </button>
                </div>
              </>
            ) : (
              <Empty
                title="Preview before launch"
                detail="Enter an authorized target and review its pinned identity, setup and topology."
              />
            )}
          </Panel>
        )}
      </div>
    </>
  );
}
