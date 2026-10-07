import { useState } from "react";
import { jsonRequest, postJson } from "../api";
import type { ArenaData } from "../types";
import {
  ConfirmDialog,
  CopyField,
  Empty,
  ErrorState,
  Loading,
  Panel,
  Status,
  useWorkspaceData,
} from "../ui";

type Binding = {
  agent_name: string;
  stance: string | null;
  paused: boolean;
  granted_by?: string;
  auto?: boolean;
};
type BindingList = { bindings: Binding[] };

export function AgentAccess({ arena }: { arena: ArenaData }) {
  const id = encodeURIComponent(arena.id);
  const { value, error, loading, refresh } = useWorkspaceData<BindingList>(
    `/api/arenas/${id}/bindings`,
  );
  const [name, setName] = useState("");
  const [stance, setStance] = useState("attacker");
  const [pending, setPending] = useState(false);
  const [revoking, setRevoking] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [failure, setFailure] = useState("");
  const active = arena.state === "active";
  async function act(path: string, method: "POST" | "DELETE", body?: unknown) {
    if (pending) return;
    setPending(true);
    setMessage("");
    setFailure("");
    try {
      if (method === "DELETE") await jsonRequest("DELETE", path);
      else await postJson(path, body);
      setMessage(
        "Agent access updated. The service rechecks scope on every tool call.",
      );
      refresh();
    } catch (reason) {
      setFailure(
        reason instanceof Error ? reason.message : "Access action failed",
      );
    } finally {
      setPending(false);
    }
  }
  if (loading && !value) return <Loading />;
  if (error) return <ErrorState message={error} refresh={refresh} />;
  if (!value) return null;
  return (
    <div className="access-grid">
      <Panel eyebrow="01 / AUTHORIZATION" title="Position an agent">
        <p className="scenario-description">
          Grant a named BYO agent access to this arena with a single stance. The
          agent connects through its own scoped gateway key.
        </p>
        {active ? (
          <form
            className="setup-form"
            onSubmit={(event) => {
              event.preventDefault();
              if (name.trim())
                void act(`/api/arenas/${id}/bindings`, "POST", {
                  agent_name: name.trim(),
                  stance,
                });
            }}
          >
            <label>
              Agent key name
              <input
                value={name}
                required
                maxLength={128}
                onChange={(event) => setName(event.target.value)}
                placeholder="Registered agent name"
              />
            </label>
            <label>
              Stance
              <select
                value={stance}
                onChange={(event) => setStance(event.target.value)}
              >
                <option value="attacker">Attacker</option>
                <option value="defender">Defender</option>
                <option value="mitm">In-path observer</option>
                <option value="configurator">Configurator</option>
              </select>
            </label>
            <button className="button button-gold" disabled={pending}>
              Grant access ↗
            </button>
          </form>
        ) : (
          <Empty
            title="Read-only access record"
            detail="Bindings cannot be changed on a closed arena."
          />
        )}
        {message && (
          <p className="gate-message" role="status">
            {message}
          </p>
        )}
        {failure && (
          <p className="form-error" role="alert">
            {failure}
          </p>
        )}
      </Panel>
      <Panel
        eyebrow="02 / LIVE BINDINGS"
        title="Scoped agent access"
        aside={
          <span className="tiny-tag">{value.bindings.length} BINDINGS</span>
        }
      >
        {value.bindings.length ? (
          <div className="access-list">
            {value.bindings.map((binding) => (
              <div key={binding.agent_name}>
                <div>
                  <strong>{binding.agent_name}</strong>
                  <Status value={binding.paused ? "paused" : "active"} />
                </div>
                <p>
                  {binding.stance || "Unrestricted"} stance · granted by{" "}
                  {binding.granted_by || "operator"}
                  {binding.auto ? " · automatic" : ""}
                </p>
                {active && (
                  <div className="settings-model-actions">
                    <button
                      className="button button-outline"
                      disabled={pending}
                      onClick={() =>
                        void act(
                          `/api/arenas/${id}/bindings/${encodeURIComponent(binding.agent_name)}/${binding.paused ? "resume" : "pause"}`,
                          "POST",
                          {},
                        )
                      }
                    >
                      {binding.paused ? "Resume" : "Pause"}
                    </button>
                    <button
                      className="button button-danger"
                      disabled={pending}
                      onClick={() => setRevoking(binding.agent_name)}
                    >
                      Revoke
                    </button>
                  </div>
                )}
              </div>
            ))}
          </div>
        ) : (
          <Empty
            title="No agent bindings"
            detail="Grant a named agent key to authorize it for one stance in this arena."
          />
        )}
      </Panel>
      <Panel
        eyebrow="03 / CONNECT"
        title="Connect your agent app"
        className="access-connect"
      >
        <ol className="connect-steps">
          <li>
            <strong>Create an agent key</strong> (admin), then authorize it
            above with a stance.
            <CopyField
              label="key command"
              value="docker exec nidavellir-orchestrator python auth.py create-key red-team-1 agent"
            />
          </li>
          <li>
            <strong>Start the gateway</strong> carrying that key and stance.
            <CopyField
              label="gateway command"
              value="NIDAVELLIR_AGENT_KEY=<agent-key> NIDAVELLIR_STANCE=attacker docker compose --profile agent-gateway up -d agent-gateway"
            />
          </li>
          <li>
            <strong>Add it to your client</strong>, for example Claude Code.
            <CopyField
              label="client command"
              value={`claude mcp add --transport http nidavellir-arena ${arena.gateway_url || "http://localhost:9000/mcp"}`}
            />
          </li>
          <li>
            <strong>Point the agent at this arena</strong> with{" "}
            <code>arena_id={arena.id}</code>. Its actions appear in the event
            trace and Live activity, where you can pause or revoke it.
          </li>
        </ol>
      </Panel>
      {revoking && (
        <ConfirmDialog
          title={`Revoke ${revoking} from ${arena.name}?`}
          body="This removes the agent's authorization for this arena. Events it already recorded stay in the append-only audit trail."
          confirmLabel="Revoke access"
          danger
          onCancel={() => setRevoking(null)}
          onConfirm={() => {
            const agent = revoking;
            setRevoking(null);
            void act(
              `/api/arenas/${id}/bindings/${encodeURIComponent(agent)}`,
              "DELETE",
            );
          }}
        />
      )}
    </div>
  );
}
