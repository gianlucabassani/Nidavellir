# Research-lane proposal

Status: proposal only — no implementation. Written 2026-10-06 as a paper
pass: no code changed, no arenas spun up, no external contact, no live
campaign credentials. Awaiting approval before building anything (NV-12,
NV-13, NV-14 and NV-15 build starts only on approval).

## WHY this phase, on record

The roadmap's order is: reliable local runtime → independently validated
repeated experiments → research breadth driven by a selected target. The
first two are done — MODEL-R1 and NV07-R1 are closed and the comparison
engine is demonstrated (model-driven paired suite, verified difference
−1.0, cost explicitly unmeasured). The next README milestone
("Held-out proof") reads: a real vulnerability found and proven
on-platform, then a comparison over challenges drawn from that work. That
is the discovery lane, and its gate is a concrete selected target. NV-12
and NV-13 are explicitly conditional ("when selected research needs it",
"when a concrete target requires it"), so they cannot be scheduled before
a target exists.

This pass produces the proposal that unblocks all of it.

## INVENTORY (read from the tree, not assumed)

### What a research session already ships

Gateway tools, all present and live
(`cyber-range/services/agent-gateway/gateway/tools.py`): `browser_visit`,
`http_request` with `list/get/replay_http_transactions` (content-addressed,
digest-bound), `run_command`, `submit_poc` / `poc_status` / `poc_result` /
`cancel_poc` (worker-owned confined jobs: CPU/RAM/PID/time-boxed),
`open_forward` / `forward_status` / `revoke_forward`,
`upload_file` / `download_file`, workspace diff/patch, `report_finding`,
and budget/stop controls (`budget_status`, `stop/resume_arena`,
emergency stop). Behind them: recorded HTTP capture/replay, finding
attachment via transaction/artifact digests, NV-11 `variant_of`
affected-versus-fixed linkage with evidence-derived group outcome,
action/time enforcement, post-teardown evidence retention, and the generic
`http_access_control` validator (confirmed CVE-2026-26012 live on
Vaultwarden 1.35.2 and refuted it on 1.37.3).

### What does not exist — stated plainly

There is **no campaign object** anywhere in the orchestrator, gateway, or
webui (zero hits for "campaign" across all three). There is **no
disclosure bundle**: the word "bundle" in-tree means SUT source-bundle
intake, NV-10 recovery bundles, or validator vocabulary
(`disclosure_status`); "disclosure" outside validators appears only in the
redacted share report. No record groups findings + PoC + notes +
provenance, and no export path produces one.

### What each NV item requires (record shapes + entry points, not schedules)

- **NV-12 (fuzzing + crash triage): greenfield.** Zero
  fuzz/crash-oracle/triage hits in-tree (the only "oracle" is the NV-06
  fixture's local effect log, not a crash oracle). Needs: a corpus record
  (seed digest), target-build identity (image digest + harness command), a
  crash oracle (signal/exit/sanitizer pattern), crash bundles (minimized
  input + dedup key), run bounds. Entry via a worker-owned bounded harness
  reusing the PoC-job slot model; results surface as findings with crash
  evidence.
- **NV-13 (binary/appliance/VM intake): greenfield behind an
  existing-but-unverified driver.** No appliance/firmware/image intake
  exists. `providers/libvirt.py` exists; per INFRA-R1 it has no live
  verification — Docker-local is the only live-verified provider. Needs:
  immutable image record (installer/image digest, format), snapshot/reset
  capability flag, before/after manifests. Entry by extending scenario
  intake past source/container shapes.
- **NV-14 (campaigns + bundles).** Needs a `campaigns` record (id, target
  identity, session list, finding list, disclosure state) plus a bundle
  builder/exporter over existing findings, PoC jobs, digests, and NV-11
  groups. No prior art in-tree — closest analogues are the NV-10 share
  report (redacted export) and eval exports (derived projections).
- **NV-15 (held-out proof): partial footing.** `EvalChallenge.label`
  already admits `held-out`, creation refuses it for public synthetic
  fixtures, and leakage labels ride exports. Missing entirely:
  construction of a private challenge *from* a confirmed finding,
  truth-sealing mechanics, and a leakage policy. Per ROADMAP §8 the
  acceptance is two artifacts — a discovery artifact (vulnerability found
  and proven end to end) and a comparison artifact over challenges "whose
  provenance is stated and whose truth was never public."

## DELIVERABLE 1 — three candidate research targets

Criteria applied: real code, self-hostable and reproducible on
Docker-local (the only live-verified provider — INFRA-R1 is open),
licence-safe to run and to write up, nothing outside the local lab
contacted, deep enough to yield a finding worth bundling. Prior
screening: `docs/research/2026-10-05-research-target-selection.md`
(25 projects; Vaultwarden top pick, Paperless-ngx runner-up).

### 1. Paperless-ngx (RECOMMENDED)

Python/Django + Angular document manager, GPL-3.0, official compose
(web/DB/broker), per-object owner/view/edit permissions plus expiring
public share links, seeded via its REST API. The 2026 advisory stream is
almost entirely authorization logic (GlobalSearch IDOR, share-link
creation without document authorization, owner reassignment via update
API, read-only upload) on only 16 total GHSAs — under-audited relative
to surface. Forces **neither NV-12 nor NV-13** (pure web,
source-available): cheapest credible path to a bundled finding. Effort:
medium (fixture + API seed + `http_access_control` hypotheses, all
existing machinery). A finding looks like: an unprivileged principal
reads or mutates a document outside its permission scope via a direct-ID
or share-link path, confirmed by the generic validator with healthy
controls. Caveat, priced in: its security policy declares some IDOR
shapes intentional — scope must be checked pre-report, and that check is
part of the work.

### 2. Vaultwarden, H3-class only (import/ownership confusion)

Cheapest (fixture, seed, validator all exist) and the prior note's own H3
hypothesis is untested. Forces nothing. But the collection-bypass and
Sends classes are now public-PoC calibration territory, and anything
adjacent risks duplication or the calibration shadow — a finding here
starts under suspicion and must survive the held-out test below to
count. Effort: low; evidential weight: discounted in advance.

### 3. OpenProject

GPL-3.0 Rails, official compose, deep role/permission matrix over work
packages (91 GHSAs, steady improper-access-control stream). Forces
nothing. Effort: high — heavier seeding (admin API + console), deeper
surface to map before the first hypothesis. Genuine depth, but the
slowest route to a bundle and the most scrutinized codebase of the
three.

### Rank: Paperless-ngx > Vaultwarden-H3 > OpenProject

Paperless wins on novelty-per-effort: rich permission system, thin audit
attention, no new platform machinery prerequisite, and its finding shape
lands directly on the existing validator. Vaultwarden is fastest but
weakest-evidence; OpenProject is deepest but slowest.

## DELIVERABLE 2 — campaign and disclosure-bundle shape (NV-14 proposal)

- **Campaign**: groups local research sessions against one pinned target.
  Identity: UUID + target identity (image digest + lifecycle recipe
  digest) + time bounds. Members: session arena IDs, finding IDs with
  verdicts, PoC job IDs, status (`open` → `disclosed` →
  `fixed-verified`).
- **Bundle contents**: the finding (payload + validator verdict +
  reason); the PoC (job ID, minimized input/steps, runner image ID);
  evidence digests (observation/control/transaction/artifact —
  content-addressed, verifiable post-teardown); affected-versus-fixed
  linkage reusing the NV-11 group outcome; analyst notes (operator-only
  free text); provenance (fixture/seed digests, validator versions,
  timestamps, operator principal, evidence-manifest hash predating any
  disclosure).
- **Storage and export, consistent with standing invariants**: bundle =
  one versioned JSON manifest + attachment pack, stored content-addressed
  under `data/` like evidence today; the database holds a pointer record,
  never the artifacts (immutable artifacts → normalized observations →
  canonical projections, same as eval exports). Export runs an
  NV-10-share-style redaction pass: secret-free by construction,
  verifiable by digest after teardown.
- **Must NOT contain**: lab credentials, API keys, tokens, unrelated
  arena data, agent prompts, or challenge truth beyond the finding
  itself. (The bundle *is* operator/disclosure-bound truth — it must
  never flow back into participant-reachable surfaces.)

## DELIVERABLE 3 — the held-out test

A finding counts as held-out iff **all** hold: (a) **no prior art** — no
public advisory, PoC, or writeup for the same flaw predating the
platform evidence (advisory-list + writeup search at discovery time,
recorded in the bundle); (b) **blind path** — discovered through
platform tooling without prior knowledge of the flaw (session record
shows no advisory consulted); (c) **independently confirmed**
on-platform (validator + affected/fixed linkage); (d) **sealed timing**
— evidence-manifest timestamp strictly predates any disclosure
submission; (e) **never fixture material** — the flaw never appears in
any calibration fixture or evaluated-agent brief.

**The test: sealed-evidence-predates-disclosure AND clean prior-art
search AND never-issued-as-fixture.** Applied honestly: Paperless
qualifies structurally; Vaultwarden qualifies only for a genuinely novel
hypothesis with a clean search (H2-adjacent work does not); if a
candidate cannot meet it, it stays calibration and we say so rather than
softening the bar.

## Biggest risk

**The phase can fail closed: bounded effort, no novel finding.**
Research success is not fully in our control — Paperless scope
exclusions or Vaultwarden duplication could leave calibration-grade
material only. Mitigation is structural, not motivational: pick the
under-audited target, time-box the campaign, and pre-register the stop
rule now — if no novel hypothesis confirms within the box, bank the
calibration fixtures and stop rather than softening the held-out bar.
Second, adjacent: disclosure handling (vendor responsiveness, timing) is
outside our control; never submit before sealed evidence exists.

---

*Decisions waiting: (1) confirm Paperless-ngx (or redirect); (2) approve
building NV-14 campaign/bundle records and the Paperless fixture — or
narrower still, fixture first with the bundle deferred until a finding
exists.*
