# WebUI — operator console

**Scope:** the operator-facing console for the Nidavellir arena. Server-rendered
Flask + Jinja, one design-token CSS system (`static/css/app.css`), vanilla JS
(`static/js/app.js`). No build step.

**Responsibility:** present and drive the orchestrator over its REST API —
nothing more. All business logic, infrastructure, and persistence live in the
backend services.

**Excluded:** business logic, provider/infra code, the agent gateway, auth
authority (the orchestrator owns API-key auth; the WebUI just forwards its key).

## Pages (single scope each)

| Route | Page | Status |
|-------|------|--------|
| `/` | Overview — fleet stats + recent arenas | real |
| `/arenas` | Arena fleet list + archive | real |
| `/launch` | Deploy a scenario / build a custom lab | real |
| `/arena/<id>` | Arena detail — nodes, topology, destroy | real |
| `/scenarios` | Scenario registry + image catalog | real |
| `/agents` `/audit` `/settings` | Planned sections (TODO stubs via `stub.html`) | stub |

Topology is rendered generically from the provider's per-node outputs
(`node_<name>_*` + `lab_networks`), so it reflects the real arena rather than a
fixed shape.
