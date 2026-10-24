# Agentic research references — 2026-10-24

Status: research and workflow mapping, not delivered runtime functionality.
The operator requested that the research logic in these two videos become part
of Nidavellir's workflow.

## Evidence and access limits

| Requested reference | Verified identity | Access obtained |
|---|---|---|
| [7CiZmq2llDg](https://www.youtube.com/watch?v=7CiZmq2llDg) | *The race to the first exploit // php2shell* | YouTube page title; no video body, description or transcript returned. |
| [SP7y1h0laN0](https://www.youtube.com/watch?v=SP7y1h0laN0) | *php situation 24h later* | YouTube page title; no video body, description or transcript returned. |

The creator's [LiveOverflow Patreon index](https://www.patreon.com/liveoverflow/sitemap)
lists the first title on 22 October 2026 and a PHP exploit follow-up on 23 October.
Both YouTube watch pages returned a sparse shell; attempts to read their English
timedtext endpoints returned cache misses. No timestamped video claims are verified
here. Secondary summaries were useful for locating related primary writing, but
are not evidence for what the presenter said. No claim that either video was
watched or transcribed is warranted.

## Methods verified in related primary writing

[Calif's original php2shell research account](https://calif.io/php2shell/), especially
“The generalized pattern” and “How did we find this?”, describes a researcher using
target history to guide an LLM toward neglected hypotheses. Targeted source review
found interruption and cleanup ordering problems. The team distilled the first
root cause into a reusable `SKILL.md` pattern and searched for variants rather than
stopping at its first finding. The authors distinguish runtime paths and deployment
conditions, and report a coordinated reproduction/disclosure timeline. These are
the authors' research claims, not an independent Nidavellir reproduction.

[Elias Taylor's contemporaneous essay](https://eliastaylor.com/noexploit/) warns
that model-generated demonstrations can change the tested server or depend on an
additional file-inclusion vulnerability. His recommendation to run candidate PoCs
independently supports a verification requirement. His broader assertion about
the absence of a working exploit is a dated opinion; it is not adopted as a current
fact or a verdict about all PHP deployments.

These related primary texts establish useful methods and failure modes. They do
not establish a complete account of either requested video's research loop.

## Provisional mapping to Nidavellir

The following is a proposed local workflow derived from the primary methods and
existing architecture, not a transcription or a claim of new implementation.

1. **Frame a falsifiable hypothesis.** Identify the target's immutable revision,
   vulnerability history, suspected invariant, entry point, required attacker
   access, and observable effect. Record why this hypothesis was selected rather
   than asking an agent to find every bug.
2. **Inspect and plan a bounded experiment.** Use a white-box research copy when
   authorized, trace the relevant producer/consumer or cleanup paths, and specify
   positive and negative controls before testing. Keep source hypotheses separate
   from confirmed runtime findings.
3. **Iterate against a fixed target.** Run small probes, retain failed attempts
   and observations, revise hypotheses, and stop under existing budgets. Any
   target or configuration change creates a separately identified experiment;
   it cannot silently repair a failing demonstration.
4. **Confirm independently.** Require a retained action, a target-local effect,
   healthy prerequisites, and the actual deployment configuration. A crash is a
   fault signal; an agent's report is a claim. Neither alone proves the requested
   exploit outcome. Preserve inconclusive and infrastructure-failure outcomes.
5. **Reproduce and compare.** Replay from reset, record repetitions and failures,
   and use affected/fixed identities where available. Record application/runtime
   prerequisites explicitly; one successful configuration does not prove all
   variants are affected.
6. **Generalize after proof.** Turn a confirmed root cause into a versioned search
   recipe with provenance, prerequisites, counterexamples and evidence links.
   Review it before reuse; each variant starts as a new hypothesis and must pass
   its own controls. A reusable recipe does not confer confirmed status.
7. **Trace configuration lineage.** When the behavior depends on configuration,
   reconstruct the effective layers and find the earliest known vulnerable state.
   Use the enabling delta to focus exploitation work. Label the conclusion proven,
   supported, inferred or unknown; only matched adjacent-state replay with healthy
   controls proves the introduction point. Secret values remain withheld.

Existing foundations: [ADR-0011](../adr/0011-research-sessions-change-intelligence.md)
defines immutable research sessions and the separate source copy;
[ADR-0014](../adr/0014-confined-poc-execution.md) confines participant PoCs;
[ADR-0009](../adr/0009-scoring-validators-monitor.md) separates monitor signals,
independent effects, controls and verdicts. [TODO](../../TODO.md) records completed
NV-06 validation, NV-09 BYO-agent proof and NV-11 affected/fixed replay. UI-R2/R3
support reviewing controls and comparing retained requests. UI-R4 source review
is still pending; semantic source review remains human work.

The gap is an explicit, retained hypothesis/experiment/iteration/recipe workflow
and evidence that a real BYO agent follows it. Existing tools make parts possible;
they do not establish that this complete loop is implemented or enforced. Recipe
generation is not installed skill execution, and must not enlarge participant
permissions or expose operator-only truth.

Fuzzing remains the target-led [NV-12](../../TODO.md) slice. If selected, its
bounded harness, build identity, corpus, crash deduplication, minimization and cold
reproduction should feed the same proof loop. These references do not establish
fuzzing as the mechanism of the cited discovery, and no new fuzzing capability was
implemented during this research.

## Next evidence needed

Obtain the video transcripts or manually inspect the videos before attributing
more specific logic to them. Select an authorized target and define one acceptance
journey: pinned setup, recorded hypothesis and controls, at least one failed or
revised experiment, independently verified result, clean-reset replay, and one
reviewed pattern recipe. Test an invalid demonstration that changes the target or
depends on an undeclared prerequisite. Keep roadmap acceptance open until the
journey is actually verified; known-CVE reproduction remains calibration.

Verification for this note is primary-source reading and local architecture
comparison only. No application suite, live arena, exploit or model experiment was
run.
