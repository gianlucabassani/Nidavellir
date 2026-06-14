# Authoring scenarios (schema v3)

A **scenario** is a provider-agnostic, data-defined topology: arbitrary
`nodes[]` on named network `segments[]`, plus `objectives` and optional
`agents[]` stance bindings. One spec is meant to compile to any provider
(docker-local, OpenStack, AWS) through the provider abstraction — there is no
frozen victim/attacker/monitor trio. This is ROADMAP Phase 1 (pillar 1 of the
[vision](../.agent/proposals/VISION.md)).

The machine-readable contract is [`scenario.schema.json`](scenario.schema.json)
(JSON Schema, generated from the Pydantic model). Regenerate it after changing
the model with:

```bash
cd cyber-range/services/scenario-orchestrator && python -m scenario_spec > ../../../docs/scenario.schema.json
```

## Where scenarios live

Today a scenario is a single YAML file in
`cyber-range/services/scenario-orchestrator/templates/<id>.yaml`; the file stem
is the scenario **id** (lowercase slug, the path-traversal guard). The richer
package layout (`scenarios/<slug>/` with `objectives.yaml`, `agent/scope.json`,
provider overlays, health `checks/`) described in
[`ARCHITECTURE.md`](../.agent/proposals/ARCHITECTURE.md) is the target shape;
the v3 spec below is the same regardless of how it is packaged.

## The v3 shape

```yaml
schema: cyberguard/v3            # optional; defaults to cyberguard/v3
name: "AD foothold (small)"      # display name (required)
title: "AD foothold"             # optional longer title
difficulty: medium               # free-form label
description: >
  One vulnerable web host and a Kali foothold on a DMZ segment.

requires:
  provider_class: container      # vm | container | any — matched to the provider

network:
  segments:                      # named L2/L3 segments nodes attach to
    - {name: dmz,  cidr: 10.10.1.0/24, description: "edge"}
    - {name: corp, cidr: 10.10.0.0/24}

nodes:                           # arbitrary N nodes — not a fixed trio
  - name: web01                  # slug, unique within the scenario
    role: victim                 # any slug; attacker/victim/monitor are special-cased
    image: dvwa                  # resolved via the per-provider image map
    size: small
    segments: [dmz]              # must reference a defined segment
    ports: [80]                  # service ports to publish (host-reachable)
  - name: jump
    role: attacker
    image: kali
    segments: [dmz, corp]        # a node can straddle segments
    entrypoint: true             # the foothold the attacker stance attaches to
    command: sleep infinity      # optional container/VM entrypoint override

agents:                          # optional — consumed by the Phase 2 MCP gateway
  - {stance: attacker, node: jump}

objectives:                      # scored in Phase 4; description is enough now
  - {id: web-rce, description: "Get RCE on web01", points: 100}

ttl_hours: 8                     # optional
```

### Fields

| Field | Required | Notes |
|-------|----------|-------|
| `schema` | no | `cyberguard/v3` (default) |
| `name` | **yes** | display name |
| `requires.provider_class` | no | `vm` \| `container` \| `any` (default `any`) |
| `network.segments[]` | no | `{name, cidr?, description?}`; names are slugs |
| `nodes[]` | **yes** (≥1) | see below |
| `agents[]` | no | `{stance, node}`; stance ∈ `attacker`/`mitm`/`defender` |
| `objectives[]` | no | `{id?, description, points?}` |
| `ttl_hours`, `tags`, `difficulty`, `title`, `description` | no | metadata |

**Node:** `name` (unique slug, required), `image` (required), `role`
(slug, default `node`), `size` (default `small`), `segments[]`, `ports[]`,
`entrypoint` (bool), `command`, plus informational `services[]`/`tools[]`.

### Validation: hard errors vs. soft warnings

Structural problems raise a validation error and the scenario **does not
load**:

- a node with no `image`;
- a node attached to an undefined segment;
- an agent bound to a node that doesn't exist;
- duplicate node or segment names;
- an empty topology (zero nodes);
- a malformed slug or an out-of-range port.

Softer issues only **warn** (logged; the scenario still loads):

- an `attacker` stance bound to a node that isn't `entrypoint: true`;
- a declared attacker stance with no entrypoint node anywhere;
- a segment with no nodes attached.

### Roles

`role` is a free slug, so GOAD-style roles (`domain-controller`, `web`, …) are
fine. Three roles are special-cased by the drivers today: `attacker` (foothold
+ `docker exec`/SSH access), `victim` (published service ports), and `monitor`
(sensor node; skipped by docker-local until the SOC container lands). Other
roles deploy as plain nodes.

## Backward compatibility

The loader accepts the legacy shape (`vms[]` + a single `network:`
`{name, cidr}`) and normalizes it into v3 in memory: each `vm` becomes a node,
the single network becomes one segment every node attaches to, a legacy
`attacker` is promoted to the entrypoint, and `metadata.objectives`/`tags` are
lifted to first-class fields. New scenarios should be authored directly in v3.

## How it's consumed

- `scenarios.load_scenario_spec(id)` → a validated `ScenarioSpec` (or `None`).
- `scenarios.list_scenarios()` / `GET /scenarios` → registry entries with
  `nodes` (count) and `valid` (schema-conformance) fields.
- Provider drivers consume `scenario_spec.normalized_nodes()` /
  `primary_cidr()`, so they accept either shape during the migration.

The generic per-provider compiler that turns `nodes[]`/`segments[]` into a
container project or a Terraform `nodes[]` module is Phase 1 **P1-2**; today
docker-local fans out one container per node and the OpenStack driver still maps
the canonical roles onto its fixed 3-VM template.
