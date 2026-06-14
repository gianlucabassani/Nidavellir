# ADR-0006: AWS topology — generic nodes[] module & egress lockdown

- **Status:** Proposed
- **Date:** 2026-06-14
- **Deciders:** CyberGuard maintainers

## Context

ROADMAP Phase 1 (P1-2) needs a *generic* provider compiler: one scenario spec
(v3 `nodes[]` + `segments[]`) compiling to any backend with no per-scenario
code. docker-local already does this for containers. The cloud side needs the
same. The inherited OpenStack template is a frozen 3-VM topology and we have no
OpenStack credentials to iterate against, so AWS — a clean greenfield on the
same OpenTofu plumbing — is the cloud backend we build the generic `nodes[]`
module on first (it is also the hosted-platform target, ROADMAP Phase 5 / P5-2).

Constraints: arenas run agents that execute commands inside them, so **no
internet egress** is a hard requirement (Phase 2 containment). Cost must stay
bounded (TTL reaper already exists; arenas are short-lived). Nothing secret may
live in the module. We cannot run a real `apply` in CI (no AWS account), so the
risky scenario→infra mapping must be pure and unit-testable, and the HCL must
at least `tofu validate`.

## Decision

We will add an **`aws` provider** (`providers/aws.py`) on a shared
`TerraformDriver` base (`providers/terraform_base.py`: per-arena workspace,
local-backend override, init/apply/destroy/outputs) and a **generic OpenTofu
module** (`infra/terraform-aws/`) driven entirely by two variables:

- `segments` → one `aws_subnet` per segment (`for_each`), each a /24 in a
  per-arena VPC;
- `nodes` → one `aws_instance` per node (`for_each`), AMI resolved by fixed id
  or a `data.aws_ami` name+owner lookup, instance type from the node `size`.

Everything is tagged `cyberguard:arena_id` (+ `:role`, `:node`, `:segment`).
**No internet gateway or NAT is created** and the security group is confined to
the VPC CIDR → egress lockdown by construction. Access is intended via **SSM**,
not inbound SSH (`associate_public_ip` defaults to `false`).

The scenario→variables mapping lives in `AWSProvider.compile_vars` (pure,
unit-tested); image references resolve through the shared per-provider **image
map** (`images.py`). The module's per-node output maps are flattened by the
driver into the same `node_<name>_*` + legacy role-prefixed output contract the
other providers emit.

## Alternatives considered

- **boto3 directly** — no state/drift management, would reinvent
  workspace-per-arena + teardown. OpenTofu is the established pattern (ADR-0003).
- **Generalize OpenStack first** — blocked on credentials; AWS is greenfield and
  the hosting target anyway. OpenStack migrates onto `TerraformDriver` + a
  generic module later, reusing this shape.
- **One ENI per segment (true multi-homing)** — AWS ENIs are AZ-scoped and add
  real complexity; v1 places a node in its first segment's subnet and records
  the rest. Multi-NIC straddle is a follow-up.

## Consequences

- Positive: an N-node v3 scenario deploys to AWS with no per-scenario code;
  containment is structural (no egress); resources are fully tagged for cost
  attribution and orphan sweeps; the `TerraformDriver` base is reusable (AWS now,
  OpenStack later).
- Negative / cost: the real `apply` path is unverified without an AWS account
  (CI covers `compile_vars` + output flattening as pure units; the module passes
  `tofu validate`). Multi-segment nodes are single-homed for now. Cost guardrails
  beyond the TTL reaper (Budgets alarm, nightly orphan sweep, per-scenario
  estimate) remain ROADMAP P5-4.
- Follow-ups: SSM access wiring + a bastion-free run_command path for the Phase 2
  attacker stance; ownership/quotas (P5-1); migrate OpenStack onto this base.
