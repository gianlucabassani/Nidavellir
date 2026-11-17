# ADR-0008: Repo → image build pipeline (deterministic-first, LLM-fallback)

- **Status:** Accepted (2026-07-13 — M1 complete: introspection + deterministic
  Dockerfile tier + verified LLM synthesis shipped; compose/devcontainer/buildpack
  execution tiers remain classified-not-executed, tracked in the roadmap)
- **Date:** 2026-07-04
- **Deciders:** Gianluca Bassani

## Context

ADR-0007 established SUT arenas: point the platform at an arbitrary OSS repo and
stand its service up. Today's flow provisions a **bare Ubuntu victim** with the
repo cloned read-write into `/opt/sut`, then relies on the **configurator** (a
human, a HITL agent, or an autonomous-opt-in agent) to *manually* build and run
the project. The field log showed this is unreliable: the model guesses the
runtime/package-manager/port wrong (`npm` vs `python3` vs `go`, the wrong port),
and the operator has to correct it.

ROADMAP **M1** replaces "model drafts shell commands into a bare box" with a
**deterministic-first build pipeline** in three tiers:

1. **Honor what the repo already ships** — a `Dockerfile`, a `compose` file, or a
   `devcontainer.json`. Most real projects have one; this is the cheapest, most
   reliable path.
2. **Zero-config detection** for the rest — Cloud Native Buildpacks (`pack` +
   Paketo) or Railpack as the no-Dockerfile engine.
3. **LLM Dockerfile synthesis with a verified-build loop** (Repo2Run pattern) when
   detection fails — the *fallback*, never the default (ADR-0009 / M1-3).

M1-1 already shipped **repo introspection** (`repo_introspect.py`): it detects the
language, build system, declared ports, and base runtime from the actual repo.
That output is the input to tier selection.

A build seam also already exists: the scenario schema's `service.source` block →
`normalized_nodes` sets `needs_build` → `docker_local._build_service_image` builds
a **single Dockerfile from a remote git context** via BuildKit, tagged +
arena-labeled for reclaim, timed out, with build-time egress open and the arena
runtime egress-locked. It is **OFF by default** (`NIDAVELLIR_ALLOW_SOURCE_BUILD`)
because building untrusted code executes it at build time.

So the forces for M1-2 (this ADR): reuse that seam, make tier selection
**deterministic and introspection-driven**, keep the safety gate, and not regress
the working bare-box + configurator flow when a build can't (or shouldn't) run.

## Decision

We will add a **pure build planner** (`build_planner.py`) that maps a repo
introspection to a **`BuildPlan`** — `strategy` ∈ {`dockerfile`, `compose`,
`devcontainer`, `buildpack`, `none`}, the concrete parameters (dockerfile path,
build context, ports), a `deterministic` flag, and a human-readable `reason`. The
planner is network-free and unit-tested, mirroring `repo_introspect.py` /
`generator.py`.

The SUT wizard consumes the plan:

- When the plan is an **executable deterministic strategy** *and* source builds
  are enabled, the compiled victim node gets a `service.source` block (repo + ref +
  detected dockerfile path) + the detected `ports`, so the **existing
  `needs_build` → `_build_service_image` path builds the repo to a version-pinned
  image and runs it — zero manual configurator steps** for the common case.
- Otherwise (no deterministic strategy, or source builds disabled) the wizard
  keeps **today's bare-box + cloned-source + configurator flow** unchanged. The
  plan is still recorded and surfaced in the preview so the operator sees what
  *would* happen ("this repo ships a Dockerfile → will auto-build" vs "no
  deterministic build → configurator").

**Increment boundary (what M1-2 executes vs classifies).** Tier-1 **Dockerfile**
is wired end-to-end (it reuses the existing builder). **Compose**, **devcontainer**,
and **buildpack** are *classified* by the planner now, but their execution is
deferred with a clear, plan-carried reason, because each needs infrastructure this
increment does not add:
- **compose** — bringing up a compose project is a multi-container runtime model
  that does not map onto the single-victim-node arena; reconciling it is its own
  design step (a follow-up milestone item).
- **devcontainer** — needs the `devcontainer` CLI in the orchestrator image.
- **buildpack** — needs the `pack` binary (Paketo) in the orchestrator image.

**Safety stays as ADR-0007 set it.** Auto-build honors
`NIDAVELLIR_ALLOW_SOURCE_BUILD` (OFF by default). Flipping it safe-by-default —
behind the verified-build loop + egress-during-build-only + arena-labeled-image
reclaim — is **M1-4**, not this ADR. Every produced image is version-pinned and
arena-labeled so `destroy()` reclaims it.

## Alternatives considered

- **One-shot LLM Dockerfile for every repo.** Pure-LLM hallucinates packages ~20%
  of the time; the deterministic tiers are cheaper and reliable. LLM synthesis is
  the *fallback* (M1-3), never the default.
- **Build everything with buildpacks, ignore a shipped Dockerfile.** A project's
  own Dockerfile encodes its real runtime and is more faithful than a detected
  buildpack; honor it first.
- **Execute compose/devcontainer/buildpack now too.** Each needs a binary or a
  runtime-model decision this increment doesn't make; shipping half-wired execution
  would be dead or misleading code. Classify now, execute per follow-up.
- **A new parallel build path instead of reusing `service.source`.** The seam
  already builds a pinned, labeled, timed-out image from a git context — reusing it
  keeps one build path and one reclaim story.
- **Auto-build on by default.** Would execute untrusted code at build time by
  default and regress the working default flow; gate stays until M1-4.

## Consequences

- **Positive:** a repo that ships a Dockerfile becomes a healthy, version-pinned
  running service with **no manual step** (when source builds are enabled); tier
  selection is deterministic and grounded in the real repo, not a model guess; the
  operator sees the planned strategy in the preview before launch; the working
  bare-box + configurator flow is preserved as the fallback; one build path, one
  reclaim story.
- **Negative / cost:** compose/devcontainer/buildpack are classified but not yet
  executed (follow-ups); buildpack + devcontainer need new binaries in the
  orchestrator image; auto-build remains gated off by default until M1-4, so the
  end-to-end "zero manual step" win is opt-in this increment; building arbitrary
  repos is slower and riskier than pulling an image (already true of the seam).
- **Follow-ups this unlocks or requires:** M1-3 (LLM Dockerfile synthesis with a
  verified-build + rollback loop, as the planner's `none`-strategy fallback);
  M1-4 (`service.package` install + safely ungate build-from-source behind the
  verified loop); adding `pack` / `devcontainer` to the orchestrator image to
  execute the buildpack / devcontainer tiers; the compose runtime-model decision.
  Accept this ADR when the planner + tier-1 auto-build land with a repo building to
  a pinned running service end-to-end.
