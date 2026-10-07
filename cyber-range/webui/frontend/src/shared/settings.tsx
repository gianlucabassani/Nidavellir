import { useEffect, useRef, useState } from "react";
import type React from "react";
import { jsonRequest, postJson } from "../api";
import type { SettingsData } from "../types";
import {
  ErrorState,
  Loading,
  PageHead,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

const providers = [
  "anthropic",
  "openai",
  "openrouter",
  "huggingface",
  "gemini",
  "deepseek",
  "ollama",
  "local",
  "custom",
];

export function Settings() {
  const { value, error, loading, refresh } = useWorkspaceData<SettingsData>(
    "/api/console/settings",
  );
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState<
    "stop" | "clear" | "remove-model" | null
  >(null);
  const [reason, setReason] = useState("");
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    if (confirm && dialog.current && !dialog.current.open)
      dialog.current.showModal();
    if (!confirm && dialog.current?.open) dialog.current.close();
  }, [confirm]);
  useEffect(() => {
    if (value?.model_connection.configured) {
      setProvider(value.model_connection.provider || "openai");
      setModel(value.model_connection.model || "");
      setBaseUrl(value.model_connection.base_url || "");
    }
  }, [value]);

  async function saveModel(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setMessage("");
    try {
      await jsonRequest("PUT", "/api/model-connection", {
        provider,
        model: model.trim(),
        api_key: apiKey,
        base_url: baseUrl.trim() || null,
      });
      setApiKey("");
      setMessage(
        "Model connection saved. The service holds the credential; this page does not retain the key.",
      );
      refresh();
    } catch (reason) {
      setMessage(
        reason instanceof Error
          ? reason.message
          : "Connection could not be saved",
      );
    } finally {
      setPending(false);
    }
  }

  async function verifyModel() {
    if (pending) return;
    setPending(true);
    setMessage("");
    try {
      const data = await postJson<{
        checked: boolean;
        verified: boolean;
        detail?: string;
      }>(
        "/api/model-connection/verify",
        apiKey
          ? { provider, model, api_key: apiKey, base_url: baseUrl || null }
          : {},
      );
      setMessage(
        data.verified
          ? "Connection verified by the provider."
          : data.detail || "The provider could not verify this connection.",
      );
    } catch (reason) {
      setMessage(
        reason instanceof Error ? reason.message : "Verification failed",
      );
    } finally {
      setPending(false);
    }
  }

  async function confirmAction() {
    if (!confirm || pending) return;
    setPending(true);
    setMessage("");
    try {
      if (confirm === "remove-model") {
        await jsonRequest("DELETE", "/api/model-connection");
        setApiKey("");
        setModel("");
        setBaseUrl("");
        setMessage("Stored model connection removed.");
      } else {
        await postJson("/api/console/system-stop", {
          action: confirm,
          reason: reason.trim(),
        });
        setMessage(
          confirm === "stop"
            ? "Emergency stop requested. Refreshing service state."
            : "Stop clearance requested. Refreshing service state.",
        );
      }
      setConfirm(null);
      setReason("");
      refresh();
    } catch (failure) {
      setMessage(failure instanceof Error ? failure.message : "Action failed");
    } finally {
      setPending(false);
    }
  }

  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  return (
    <>
      <PageHead
        overline="PLATFORM / SETTINGS"
        title="Settings"
        subtitle="Control research admission, manage your model connection, and review access boundaries."
        observed={value.observed_at}
        action={
          <a className="button button-outline" href="/console/profile">
            Operator profile ↗
          </a>
        }
        refresh={refresh}
      />
      {message && (
        <p className="settings-message" role="status">
          {message}
        </p>
      )}
      <div className="shared-grid settings-grid">
        <Panel
          eyebrow="01 / SAFETY"
          title="System emergency stop"
          className="shared-primary"
          aside={<Status value={value.system_stop.state} />}
        >
          <p className="shared-copy">
            Stops new research work across arenas and drains disposable helpers.
            Clearing the stop requires the service to verify cleanup.
          </p>
          <div className="shared-action-row">
            <strong>Research admission</strong>
            {value.system_stop.state === "open" && (
              <button
                type="button"
                className="button button-danger"
                onClick={() => {
                  setReason("");
                  setConfirm("stop");
                }}
              >
                Emergency stop
              </button>
            )}
            {value.system_stop.state === "stopped" && (
              <button
                type="button"
                className="button button-outline"
                onClick={() => {
                  setReason("");
                  setConfirm("clear");
                }}
              >
                Clear emergency stop
              </button>
            )}
          </div>
        </Panel>
        <Panel eyebrow="02 / MODEL" title="Operator model connection">
          <p className="shared-copy">
            The service encrypts the key at rest and returns masked status. It
            never appears in this page after saving.
          </p>
          <div className="shared-action-row">
            <strong>
              {value.model_connection.configured
                ? `${value.model_connection.provider} · ${value.model_connection.model}`
                : "Not connected"}
            </strong>
            <Status
              value={
                value.model_connection.available
                  ? value.model_connection.configured
                    ? "configured"
                    : "unconfigured"
                  : "unavailable"
              }
            />
          </div>
          <form
            className="registry-form settings-model-form"
            onSubmit={saveModel}
          >
            <label>
              Provider
              <select
                value={provider}
                onChange={(event) => setProvider(event.target.value)}
              >
                {providers.map((item) => (
                  <option key={item} value={item}>
                    {item}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Model
              <input
                value={model}
                onChange={(event) => setModel(event.target.value)}
                required
                maxLength={128}
                placeholder="Model identifier"
              />
            </label>
            <label>
              API key
              <input
                type="password"
                value={apiKey}
                onChange={(event) => setApiKey(event.target.value)}
                maxLength={512}
                autoComplete="new-password"
                placeholder={
                  value.model_connection.configured
                    ? "Leave blank to retain the stored key"
                    : "Provider key, when required"
                }
              />
            </label>
            <label>
              Base URL · optional
              <input
                value={baseUrl}
                onChange={(event) => setBaseUrl(event.target.value)}
                maxLength={512}
                placeholder="Required for local or custom providers"
              />
            </label>
            <div className="settings-model-actions">
              <button
                type="button"
                className="button button-outline"
                disabled={
                  pending || (!value.model_connection.configured && !apiKey)
                }
                onClick={() => void verifyModel()}
              >
                Test connection
              </button>
              <button className="button button-gold" disabled={pending}>
                {pending ? "Working…" : "Save connection ↗"}
              </button>
              {value.model_connection.configured && (
                <button
                  type="button"
                  className="button button-danger"
                  disabled={pending}
                  onClick={() => setConfirm("remove-model")}
                >
                  Remove
                </button>
              )}
            </div>
          </form>
        </Panel>
        <Panel
          eyebrow="03 / ACCESS"
          title="Credential boundary"
          className="settings-access"
        >
          <div className="settings-boundaries">
            <div>
              <strong>Console session</strong>
              <span>Signed-in browser session with CSRF protection.</span>
            </div>
            <div>
              <strong>Orchestrator API</strong>
              <span>Server-held operator key; never sent to the browser.</span>
            </div>
            <div>
              <strong>Agent gateway</strong>
              <span>
                Keys are issued out of band and scoped to an arena and stance.
              </span>
            </div>
          </div>
        </Panel>
      </div>
      <dialog
        ref={dialog}
        className="gate-dialog"
        onClose={() => setConfirm(null)}
        onCancel={(event) => {
          if (pending) event.preventDefault();
        }}
      >
        <span className="eyebrow">CONFIRM PLATFORM ACTION</span>
        <h2>
          {confirm === "stop"
            ? "Stop research across the platform?"
            : confirm === "clear"
              ? "Clear the system stop?"
              : "Remove the stored model connection?"}
        </h2>
        <p>
          {confirm === "stop"
            ? "The service will refuse new work and drain running helpers. Existing evidence remains available."
            : confirm === "clear"
              ? "The service will reopen research admission only after its cleanup checks pass."
              : "The stored credential will be deleted. Agent builds and prior records remain pinned."}
        </p>
        {confirm !== "remove-model" && (
          <label>
            Reason
            <textarea
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              required
              maxLength={500}
              rows={3}
              placeholder="Why is this change needed?"
            />
          </label>
        )}
        <div className="dialog-actions">
          <button
            type="button"
            className="button button-outline"
            disabled={pending}
            onClick={() => setConfirm(null)}
          >
            Cancel
          </button>
          <button
            type="button"
            className={
              confirm === "stop" ? "button button-danger" : "button button-gold"
            }
            disabled={pending || (confirm !== "remove-model" && !reason.trim())}
            onClick={() => void confirmAction()}
          >
            {pending
              ? "Working…"
              : confirm === "stop"
                ? "Confirm emergency stop"
                : confirm === "clear"
                  ? "Clear stop"
                  : "Remove connection"}
          </button>
        </div>
      </dialog>
    </>
  );
}
