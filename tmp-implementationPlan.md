# P1 handoff — independently verified, repeatable results

Prepared 2026-09-23. **Planning only: NV-06–10 remain unchecked.** NV-05 is
committed locally as `7df304a`; its passing release, PostgreSQL, Docker live
and NV-02/03/04 regression evidence is in `docs/verification/`. The previous
NV-05 handoff is preserved in Git at `2f0d4e2`. Preserve
`docs/UI_REBUILD_PLAN.md` and journal history. Do not push.

## Outcome and delivery order

P1 should first produce **one independently verified research result** on a
resettable Docker-local target. Then generalize that path into agent comparison:

1. **NV-06 — immediate build target.** Link an authorization finding's actual
   request to an independently observed target effect, negative and healthy
   controls, immutable evidence, and a four-way verdict. A persuasive but
   unsupported claim gets no confirmed credit.
2. **NV-07.** Add the smallest durable Agent build, Challenge/Suite,
   Evaluation, Run and Trial records needed to compare two pinned builds on
   that fixture. Reuse ADR-0010's event-derived export and the existing scorer.
3. **NV-08.** Promote the NV-06 test fixture into one versioned, resettable
   authorization challenge with synthetic accounts, private truth and leakage
   labels. Accept NV-08 only when repeated trials catch a seeded agent regression.
4. **NV-09.** Run one synthetic Bughunt-shaped workflow, reset and repeat after
   one agent change. Record setup effort, reuse, false claims, observed outcomes
   and whether the seeded regression was detected. No live bounty credentials.
5. **NV-10.** Back up and restore the resulting research and experiment records
   on a clean instance, then review old evidence and rerun the pinned fixture.

This sequence follows `TODO.md` dependencies and keeps a vertical proof ahead
of broad challenge intake, generic drivers, optional episodes and providers.
The NV-06 fixture is test infrastructure; it does not complete NV-08. After
each task, use observed operator value to decide whether the next generalization
is justified. Keep `TODO.md` as the acceptance authority.

## NV-06 baseline and gap

Read `AGENTS.md` continuity sources in order, especially ADR-0004 (events),
ADR-0009 (validators/scoring), ADR-0010 (export), ADR-0012 (console), and the
latest journal. Inspect `validators.py`, `api.py` finding/score routes,
`scoring.py`, `http_transactions.py`, `evidence_artifact.py`, the findings
workspace and `tests/test_validators.py` / `tests/test_findings.py`.

Existing validators support browser-observed XSS, a marker check, and crash
correlation. The marker check can accept a marker supplied by the finding;
crash correlation can credit a same-node signal without tying it to the
reported action. A matching CWE/node claim also earns benchmark `found` points
before an effect is confirmed. Resolve these false-credit risks by extending
the existing validator/event model, not by adding a second scorer.

## Freeze the NV-06 acceptance matrix before code

Use a small synthetic service with accounts A and B and one private object per
account. Pin image, scenario recipe, seed and reset identity. The attacker sees
only A's account and the public task brief. A platform-owned validator checks
the target's independent effect record or private read-back; it must not derive
proof from the agent's claim, a caller-supplied marker, or response text alone.

| Case | Participant action and independent check | Verdict |
|---|---|---|
| Positive | A requests B's object; read-back shows unauthorized access/effect. | `confirmed` |
| Negative | Same claim on a denied path or protected variant; probe succeeds and effect is absent. | `refuted` |
| Healthy control | B accesses B's own object; service behaves normally. | Control passes; no vulnerability credit |
| Unsupported claim | Correct-looking CWE, title, PoC or marker without the effect. | `refuted` or `inconclusive`, never confirmed |
| Probe failure | Target or probe unavailable, timeout, or incomplete evidence. | `infrastructure_failure`, never refuted or confirmed |

Freeze a versioned verdict contract with `finding_id`, `arena_id`, immutable
target/recipe identity, validator ID/version, action or transaction digest,
observation/control digests, timestamp, verdict and stable reason code. Keep
private truth and secrets operator-only. Agent REST/MCP replies remain neutral.
Bound every probe to the arena target and honor the existing budget/stop gates.

## Implementation slices

1. **Fixture and oracle.** Build the resettable authorization fixture and an
   operator-owned, target-scoped effect probe. Prove the matrix's positive,
   negative and healthy cases directly. The isolated Docker verifier must clean
   its labeled resources in `finally`, including on assertion failure.
2. **Pure validator.** Add the authorization effect check in `validators.py`.
   Remove caller-controlled marker confirmation. Tie crash confirmation to a
   relevant action/observation window or leave it inconclusive when linkage is
   absent. Unit-test all four verdicts, including misleading response bodies.
3. **Durable evidence chain.** Link action → effect/control → verdict using
   content-addressed transaction/evidence records and append-only events.
   Store identities and digests needed after teardown. Prefer ADR-0004's event
   projection; add a migration only for a demonstrated atomicity/query need.
   Revalidation must be idempotent or append a clearly versioned new verdict.
4. **Score and review.** Show claim coverage separately from effect-confirmed
   success. Unsupported or inconclusive findings cannot satisfy verified
   exploit, full clear or headline success. Preserve old export fields where
   possible and version any changed semantics. Console/API operator views show
   action, observations, controls, reason and digest links after teardown.
   Agent views hide verdicts and private data. Manual operator adjudication
   cites immutable evidence and stays distinct from automatic confirmation.
5. **Vertical live run.** Through normal REST/MCP and console surfaces, deploy,
   act, submit, review, reset, run the negative/control cases, destroy and
   review the retained record. Save JSON evidence with image/recipe digests,
   IDs, verdicts, review links and zero final labeled resources. This proves
   NV-06 only; paired comparisons are NV-07.

## Verification cadence and acceptance

- Run focused validator/API/scoring tests while building. Add PostgreSQL
  ordering/concurrency tests for a real event or idempotency risk. Do not run
  the whole release gate after each assertion change.
- Finish the acceptance matrix before the first full live run. Check fixture
  cleanup after both failure and success; a Docker address-pool failure must
  not leave arena networks behind.
- After the final product-code change, run `make release-check`, the isolated
  NV-06 Docker live gate and affected live regressions. At minimum recheck
  NV-02 reset/retained evidence; run NV-03/04/05 live gates when their helper,
  stop, forward or shared API paths change. Repeat a gate only after a fix to
  its covered behavior, and record the reason.
- Accept NV-06 only when all matrix cases, pinned SQLite/PostgreSQL release
  gate, required live/regression gates, post-teardown review and agent truth
  redaction pass. Then record exact evidence in `docs/JOURNAL.md` and update
  ADR/README/ROADMAP/TODO. Until then, leave NV-06 unchecked. Do not push.

## First action in the next building session

Confirm clean local `main` at the P1 handoff commit. Write the NV-06 acceptance
matrix and fixture first, then settle the verdict/evidence contract before
editing API or scoring code. Build directly if the user requests a builder;
the user's explicit instruction overrides AGENTS.md's delegation suggestion.
