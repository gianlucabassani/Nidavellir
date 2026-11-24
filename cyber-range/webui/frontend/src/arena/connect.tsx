import { useEffect, useState } from "react";
import { postJson } from "../api";
import type { ArenaData } from "../types";
import { CopyField, formatObserved, getJsonSafe } from "../ui";

// UX-07: from a fresh arena to a connected agent without a shell. The operator
// mints a scoped agent key here (shown once); the client's MCP config starts
// its own gateway over stdio with that key, so starting the client is the only
// command. Harness-neutral: the same gateway serves every MCP client.
type Created = {
  agent_name: string;
  stance: string;
  api_key: string;
  gateway: {
    image: string;
    network: string;
    api_url: string;
    http_url: string;
  };
};
type Connection = {
  bound: boolean;
  connected: boolean;
  session: { ts: string; model: string | null; provider: string | null } | null;
  key: { exists: boolean; revoked: boolean; last_used_at: string | null };
};

function dockerArgs(created: Created) {
  return [
    "run",
    "-i",
    "--rm",
    "--network",
    created.gateway.network,
    "-e",
    `NIDAVELLIR_API_URL=${created.gateway.api_url}`,
    "-e",
    `NIDAVELLIR_AGENT_KEY=${created.api_key}`,
    "-e",
    `NIDAVELLIR_STANCE=${created.stance}`,
    "-e",
    "NIDAVELLIR_GATEWAY_TRANSPORT=stdio",
    created.gateway.image,
  ];
}

function clientConfigs(created: Created) {
  const args = dockerArgs(created);
  const server = { command: "docker", args };
  const mcpServers = JSON.stringify(
    { mcpServers: { nidavellir: server } },
    null,
    2,
  );
  return [
    {
      id: "claude-code",
      label: "Claude Code",
      file: ".mcp.json in your project",
      text: mcpServers,
    },
    {
      id: "desktop",
      label: "Claude Desktop · Cursor · Windsurf",
      file: "the client's MCP servers JSON",
      text: mcpServers,
    },
    {
      id: "opencode",
      label: "opencode",
      file: "opencode.json",
      text: JSON.stringify(
        {
          mcp: {
            nidavellir: {
              type: "local",
              command: ["docker", ...args],
              enabled: true,
            },
          },
        },
        null,
        2,
      ),
    },
    {
      id: "codex",
      label: "Codex CLI",
      file: "~/.codex/config.toml",
      text: `[mcp_servers.nidavellir]\ncommand = "docker"\nargs = [${args.map((a) => JSON.stringify(a)).join(", ")}]`,
    },
  ];
}

export function ConnectAgent({ arena }: { arena: ArenaData }) {
  const active = arena.state === "active";
  const [name, setName] = useState(`agent-${arena.id.slice(0, 8)}`);
  const [stance, setStance] = useState("attacker");
  const [pending, setPending] = useState(false);
  const [failure, setFailure] = useState("");
  const [created, setCreated] = useState<Created | null>(null);
  const [client, setClient] = useState("claude-code");
  const [connection, setConnection] = useState<Connection | null>(null);
  useEffect(() => {
    if (!created) return;
    let stopped = false;
    const check = async () => {
      const status = await getJsonSafe<Connection>(
        `/api/console/arenas/${encodeURIComponent(arena.id)}/agent-connection/${encodeURIComponent(created.agent_name)}`,
      );
      if (!stopped && status) setConnection(status);
    };
    void check();
    const timer = window.setInterval(() => {
      if (!connection?.connected) void check();
    }, 3000);
    return () => {
      stopped = true;
      window.clearInterval(timer);
    };
  }, [created, arena.id, connection?.connected]);
  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (pending) return;
    setPending(true);
    setFailure("");
    try {
      const result = await postJson<Created>(
        `/api/console/arenas/${encodeURIComponent(arena.id)}/agent-keys`,
        { name: name.trim(), stance },
      );
      setCreated(result);
      setConnection(null);
    } catch (reason) {
      setFailure(
        reason instanceof Error ? reason.message : "Key creation failed",
      );
    } finally {
      setPending(false);
    }
  }
  if (!active && !created)
    return (
      <p className="scenario-description">
        Agents connect to an active arena. This one is {arena.state}.
      </p>
    );
  if (!created)
    return (
      <form className="setup-form connect-form" onSubmit={create}>
        <label>
          Agent name
          <input
            value={name}
            required
            pattern="[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}"
            maxLength={64}
            onChange={(event) => setName(event.target.value)}
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
          {pending ? "Creating…" : "Create agent key ↗"}
        </button>
        <small>
          Creates a role=agent key bound only to this arena in this stance. It
          cannot reach other arenas or operator actions.
        </small>
        {failure && (
          <p className="form-error" role="alert">
            {failure}
          </p>
        )}
      </form>
    );
  const configs = clientConfigs(created);
  const chosen = configs.find((item) => item.id === client) || configs[0];
  return (
    <div className="connect-flow">
      <div className="connect-key" role="status">
        <strong>
          Key for {created.agent_name} · {created.stance}
        </strong>
        <p>
          Shown once. It is already in the configs below; store it if you need
          it elsewhere.
        </p>
        <CopyField label="agent key" value={created.api_key} />
      </div>
      <div className="connect-clients">
        <div role="tablist" aria-label="MCP client">
          {configs.map((item) => (
            <button
              key={item.id}
              type="button"
              role="tab"
              aria-selected={item.id === chosen.id}
              onClick={() => setClient(item.id)}
            >
              {item.label}
            </button>
          ))}
        </div>
        <div role="tabpanel">
          <p>
            Paste into <code>{chosen.file}</code>, then start the client. It
            starts its own gateway with Docker.
          </p>
          <CopyField
            label={`${chosen.label} configuration`}
            value={chosen.text}
          />
        </div>
      </div>
      <p>
        Tell the agent to work on <code>arena_id={arena.id}</code>.
      </p>
      <ConnectionIndicator connection={connection} />
    </div>
  );
}

function ConnectionIndicator({
  connection,
}: {
  connection: Connection | null;
}) {
  const state = connection?.connected
    ? "connected"
    : connection?.key.last_used_at
      ? "authenticated"
      : "waiting";
  return (
    <div
      className={`connect-indicator connect-${state}`}
      role="status"
      aria-live="polite"
    >
      <span className="live-dot" aria-hidden="true" />
      {state === "connected" && connection?.session ? (
        <span>
          <strong>Connected</strong> ·{" "}
          {[connection.session.model, connection.session.provider]
            .filter(Boolean)
            .join(" via ") || "agent session"}{" "}
          · {formatObserved(connection.session.ts)}
        </span>
      ) : state === "authenticated" ? (
        <span>
          <strong>Gateway reached the service</strong> · waiting for the agent
          to announce its session
        </span>
      ) : (
        <span>
          <strong>Waiting for agent…</strong> start your client with the
          configuration above
        </span>
      )}
    </div>
  );
}
