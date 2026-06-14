"""The authenticated agent session: its API key and bound stance."""
import hashlib
from dataclasses import dataclass

from gateway.stances import Stance, allowed_tools, parse_stance


class GatewayAuthError(Exception):
    """Raised when no usable agent credential is available."""


@dataclass(frozen=True)
class Session:
    """An authenticated agent principal bound to (at most) one stance.

    `api_key` is secret and never logged; `agent_id` is a non-reversible,
    stable handle derived from it, used for correlation in traces/audit.
    """

    api_key: str
    stance: Stance | None = None

    @property
    def agent_id(self) -> str:
        return "agent-" + hashlib.sha256(self.api_key.encode()).hexdigest()[:12]

    def can_use(self, tool: str) -> bool:
        return tool in allowed_tools(self.stance)


def session_from_config(cfg) -> Session:
    """Build a Session from gateway config, validating the stance."""
    if not cfg.agent_key:
        raise GatewayAuthError(
            "no agent API key configured (set CYBERGUARD_AGENT_KEY)"
        )
    return Session(api_key=cfg.agent_key, stance=parse_stance(cfg.stance))
