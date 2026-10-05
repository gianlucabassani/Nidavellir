import { useRef, useState } from "react";
import { postForm, postJson } from "../api";
import type { ResearchPreview } from "../types";
import { Panel, Empty, PageHead } from "../ui";

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
      <div className="comparison-form-grid">
        <form
          className="panel comparison-form"
          ref={form}
          onSubmit={(event) => {
            event.preventDefault();
            review();
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
              <span className="eyebrow">01 / TARGET & CONSENT</span>
              <h2>Research setup</h2>
            </div>
          </div>
          <div className="comparison-fields research-fields">
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
              <input name="include_attacker" type="checkbox" defaultChecked />{" "}
              Add an isolated attacker foothold
            </label>
            <label className="form-check">
              <input name="authorization_confirmed" type="checkbox" required />{" "}
              I confirm this target is in scope and I am authorized to assess it
            </label>
          </div>
          {message && (
            <div className="form-error" role="alert">
              {message}
            </div>
          )}
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
        </form>
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
                  {kind === "oci" ? preview.runtime_ref : preview.resolved_ref}
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
                <span>{preview.topology.segments.length} network segments</span>
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
      </div>
    </>
  );
}
