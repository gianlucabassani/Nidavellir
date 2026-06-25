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
schema: nidavellir/v3            # optional; defaults to nidavellir/v3
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
| `schema` | no | `nidavellir/v3` (default) |
| `name` | **yes** | display name |
| `requires.provider_class` | no | `vm` \| `container` \| `any` (default `any`) |
| `requires.egress` | no | `open` opts out of default-on egress containment (docker-local) |
| `requires.mirror` | no | `off` disables the allowlisted apt/pip mirror on a contained arena (docker-local; default on when there's a foothold) |
| `network.segments[]` | no | `{name, cidr?, description?}`; names are slugs |
| `nodes[]` | **yes** (≥1) | see below |
| `agents[]` | no | `{stance, node}`; stance ∈ `attacker`/`mitm`/`defender` |
| `objectives[]` | no | `{id?, description, points?}` (narrative goals) |
| `vulnerabilities[]` | no | known-vuln manifest (ground truth): `{id, title, cwe?, node?, severity?, points?, description?}`. **Operator-only** — never shown to an agent; the goal is for the agent to discover these. Revealed via `GET /scenarios/{id}/vulnerabilities`; scored from self-reported findings by CWE+node. |
| `ttl_hours`, `tags`, `difficulty`, `title`, `description` | no | metadata |

**Node:** `name` (unique slug, required), a **workload** (`image` *or* a
`service:` block — see below), `role` (slug, default `node`), `size` (default
`small`), `segments[]`, `ports[]`, `environment` (a `str→str` map of env vars for
the workload), `entrypoint` (bool), `command`, plus informational
`services[]`/`tools[]`.

### Software-under-test: the `service:` block (P1-6, packaged-first)

For SUT arenas (point a node at an arbitrary open-source project), a node may
declare a `service:` instead of a bare `image` (ADR-0007). **Packaged-first** —
prefer an existing published image; build from source only for gaps:

```yaml
nodes:
  - name: victim
    role: victim
    ports: [3000]
    service:
      image: "bkimminich/juice-shop:latest"   # preferred (packaged); resolved as the effective image
      whitebox: false                          # true → expose source to the agent (white-box)
      # OR build from source (docker-local builds via the daemon; see the note below):
      # source: {repo: "https://github.com/owner/app", ref: "v1.2.3", dockerfile: "Dockerfile"}
      # OR install a package (execution is a separate follow-up):
      # package: "some-pkg"
```

`service.image` wins over a node's own `image` (packaged-first).

**Build from source (`service.source`)** is built by docker-local via the daemon
(a remote git context, pinned by `ref`), but is **OFF by default**: building an
arbitrary repo runs third-party code at build time, so it requires
`NIDAVELLIR_ALLOW_SOURCE_BUILD=true` (see [`SECURITY.md`](SECURITY.md)). When the
flag is unset, a `source` service fails with a clear error pointing at it — prefer
a packaged `service.image`. Build-time network is open (apt/pip/npm); the arena
**runtime stays egress-locked** regardless. `service.package` install is not wired
yet (supply a `source` or an `image`).

**White-box source access (`whitebox: true` + a `source`).** When a victim node is
white-box and declares a `service.source`, docker-local clones that repo (read-only,
pinned to `ref`) into a per-arena volume and mounts it **read-only** into the
foothold(s) at `/whitebox/<victim>` — the agent reads the source while it tests the
running service. The clone runs nothing from the repo (so source *reading* is
ungated, unlike *building*), the mount is read-only, and the volume is reclaimed on
destroy. `whitebox: true` **without** a `source` just surfaces the flag (no source
to mount). The mounted path is surfaced as `node_<victim>_whitebox_source`.

### Importing from Vulhub (P1-5)

[Vulhub](https://github.com/vulhub/vulhub) ships hundreds of pre-built vulnerable
container environments as Docker Compose files (one dir per CVE/app). Nidavellir
**deterministically** converts one into a v3 pack and lands it in the import
registry — no model in the loop (that is the separate prompt→spec generator):

```bash
curl -sX POST "$API/scenarios/import/vulhub" -H "X-API-Key: $OP" \
  -H 'Content-Type: application/json' \
  -d '{"path": "weblogic/CVE-2017-10271", "ref": "master"}'
```

Each compose **service** becomes one `victim` node: `image:` → `image`; a
build-only service → a gated `service.source` rooted at the Vulhub repo subdir
(deploying it needs `NIDAVELLIR_ALLOW_SOURCE_BUILD`); `ports:` → the container
ports; `environment:` (dict or `KEY=VALUE` list) → `environment`; `command:` →
`command`. A Kali foothold is added by default (so the arena is drivable by a
human or an agent). Keys we can't faithfully map (`volumes`, `depends_on`,
`privileged`, …) are **dropped and reported in `warnings`** — never silently. Pass
`compose` (a pasted compose object/string) instead of `path` for offline use, or
`dry_run: true` to preview the topology without saving. VulnHub (full VM disks)
needs a VM provider and is a separate, planned track.

### Generating from a prompt (P3, BYO model)

Where the Vulhub importer is deterministic, the **prompt→spec generator** drafts a
new topology from a natural-language brief using the **operator's own connected
model** (the model bubble). Nidavellir builds the prompt (embedding this schema +
a worked example), calls the operator's model **in JSON mode** (OpenAI-compatible
providers incl. Gemini get `response_format: json_object`; Anthropic is prefilled
with `{`), and parses a v3 spec out of the reply — it never supplies the AI itself:

```bash
curl -sX POST "$API/scenarios/generate" -H "X-API-Key: $OP" \
  -H 'Content-Type: application/json' \
  -d '{"prompt": "a Kali foothold and a vulnerable Apache CMS box on an isolated segment",
       "provider_class": "container"}'
```

The response is the **same review payload** as `/scenarios/preview`
(`valid`/`errors`/`warnings`/`topology`/`summary`) plus the generated `spec`. It
**never deploys or saves** — the operator reviews the spec + topology (in the
Launch → *Generate* card, the generated spec is editable), then imports it via
`POST /scenarios` and launches like any other pack. No model connected → `409`; an
unusable model reply → `valid: false` with the model's `raw` text (never a `500`).
Pass `provider_class: "vm"` to generate a **VM** topology instead (OS images,
real service ports, no container-only fields) — it validates the same way; a live
VM **deploy** needs a vm backend (OpenStack/AWS, or the planned local QEMU/libvirt
provider).

Generation is **operator-only** and is not exposed to in-arena agent stances
(authoring infrastructure is an operator privilege). Over MCP the operator's gateway
runs with an **operator stance** exposing `scaffold_scenario` (the same review-gated
generate) and `import_scenario` — never on an attacker/defender/configurator session.

### Validation: hard errors vs. soft warnings

Structural problems raise a validation error and the scenario **does not
load**:

- a node with no workload (neither `image` nor a `service` with image/source/package);
- a `service` with none of `image`/`source`/`package`;
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

### docker-local compilation (P1-2)

The docker-local driver realizes the topology directly: **one bridge network
per declared `segment`** (per arena), **one container per node** named
`cg-<arena>-<node>` and attached to the networks of every segment it declares
(a node can straddle segments). Nodes that declare no segment share a per-arena
default bridge (named `nidavellir-<arena>`, preserving the flat single-network
behaviour). `entrypoint`/`attacker` nodes are kept alive (`sleep infinity`) and
get a `docker exec` command; declared `ports` are published on random host ports.

Outputs are emitted **per node** (`node_<name>_private_ip`, `node_<name>_name`,
`node_<name>_ssh_command`, `node_<name>_url`) plus `lab_networks[]`, so N-node
topologies and repeated roles are fully addressable. Legacy role-prefixed keys
(`attack_vm_*`, `victim_vm_*`, `victim_web_url`, …) are still emitted for the
first node of each canonical role, for dashboard/mock parity.

### AWS compilation (P1-2 / P5-2)

The `aws` driver compiles the same v3 topology to a **per-arena VPC** via a
generic OpenTofu module (`infra/terraform-aws/`): one `aws_subnet` per declared
`segment`, one `aws_instance` per `node` (`for_each`), everything tagged
`nidavellir:arena_id`. **No internet gateway/NAT is created** and the security
group is confined to the VPC CIDR — arenas have no egress by construction
(`associate_public_ip` defaults off; SSM is the intended access path). Node
`size` maps to an instance type; `image` resolves through the image map to a
fixed AMI id or a `data.aws_ami` name+owner lookup. The scenario→variables
mapping (`AWSProvider.compile_vars`) is pure and unit-tested; the real `apply`
needs an AWS account (credentials/region from the environment), so it is
exercised only when creds are present — see [ADR-0006](adr/0006-aws-topology.md).
A node that straddles multiple segments lands in its **first** segment's subnet
for now (true multi-homing is a follow-up). AWS outputs are flattened to the
same `node_<name>_*` contract as docker-local.

### Image map

A node's `image` is a **logical name** resolved per provider by `images.py`:
`dvwa`/`kali`/`ubuntu`/… → a container tag for docker-local, an AMI selector
(name-filter + owner, or a fixed id) for aws. Unknown names — including a
concrete container tag or `ami-…` id — **pass through unchanged**, so a scenario
stays portable while still allowing a concrete reference when needed.

### Still pending

The OpenStack driver still maps the canonical roles onto its fixed 3-VM template
(it reads v3 via `normalized_nodes`); replacing that with the generic
`TerraformDriver` + a `nodes[]` module (as AWS now does) is deferred — it needs
OpenStack credentials to verify.
