"""
CyberGuard MCP agent gateway (ROADMAP Phase 2, the priority pillar).

The *only* path a bring-your-own agent has into a running arena: an MCP server
that exposes the arena lifecycle (and, in later increments, the per-stance
attacker/MITM/defender toolsets) under `agent`-principal auth, scope, guardrails,
and an append-only trace. See `docs/adr/0005-mcp-agent-gateway.md`.

This package is the gateway service. It talks to the orchestrator over its REST
API (it does NOT import the orchestrator), so it stays a decoupled, separately
deployable process — and never an AI itself (the agent is bring-your-own; see
the scope boundary in VISION.md).
"""
