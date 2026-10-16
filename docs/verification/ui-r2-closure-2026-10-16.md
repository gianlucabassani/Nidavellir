# UI-R2 controls and evidence review — 2026-10-16

The operator approved the bounded first-slice design before implementation.
This extends the existing console Findings view and protected evidence routes.
The live run occurred on October 16 in Europe/Rome; its immutable artifact names
and timestamps use October 15 UTC.

## Delivered behavior

An expandable finding review brings together the linked actor request/response,
prerequisite requests and expected/observed control results, observed effects,
independent verdict, validator/target/recipe identity and immutable evidence links.
Controls distinguish passed, failed and unresolved evidence. Automatic confirmations
and refutations require the retained chain and passed prerequisites; a missing or
failed prerequisite cannot present a refutation. Infrastructure failures remain
separate. Historical verdicts are retained and unresolved evidence is named.
Operator judgments remain separate and win the effective card verdict.

The orchestrator owns this read-only projection at
`GET /arenas/{arena}/findings/{finding}/review`; the session-protected Flask route
is `GET /api/console/arenas/{arena}/findings/{finding}/review`. Agent keys are denied.
Existing arena-scoped stores verify every digest. Reading review never executes a
probe or changes the action budget. New validation receipts retain only the safe
identity/expectation context needed for review, without private control headers or
marker values. Header values are withheld from the review; bodies remain protected
operator-visible target content, with the stored truncation flag and body digest.

For supported validators, operator refutation is rejected with 422 unless the
prerequisites and actor/effect evidence are resolved. Confirmation remains an
explicit, separately audited operator judgment under the existing evidence rule.
Source authoring, execution permissions, neutral agent acknowledgements, scoring,
containment and enforceable arena budgets preserve their existing boundaries.

## Active verification

[The retained live report](ui-r2-live-2026-10-15-42495585.json) uses a real
Docker-local NV-06 synthetic two-account target, pinned by image ID. This is public
calibration evidence, not a new research finding or agent-capability result.

| Case | Observed review |
|---|---|
| A requests B's unprotected object | Independent confirmation, owner control passed, request/response and target-local effect retained. |
| A requests B's protected object | Refutation under the passed owner control; denied response and effect retained. |
| Deliberately tainted generic HTTP control | Owner prerequisite passed; actor allowed-control failed because it disclosed the protected marker. Result stayed infrastructure_failure/control_failed; the API rejected operator refutation with 422. |
| Finding without linked action | Inconclusive with explicit missing action/control/effect evidence. |

Real browser checks passed [before teardown](ui-r2-live-2026-10-15-42495585.json.browser.json)
and [after teardown](ui-r2-live-2026-10-15-42495585.json.retained-browser.json).
Each of three cases opened all three stored transaction/control/effect links
successfully in each phase: 18 protected link checks. Reviews and their digests
were unchanged after all three arenas reached destroyed. Manual refutation kept
its effective headline with cached independent review, refresh and reload.
No browser page errors were recorded; 320, 390 and 1440 px checks found no page-level
overflow. Screenshots beside both browser reports retain the rendered review.
This is a focused product check, not a new full accessibility certification.

Agent access returned 403; a wrong-arena lookup returned 404; review JSON excluded
both synthetic account tokens. Review left the explicitly capped arena budget
unchanged. The report records zero labelled containers, networks, volumes and
images for all three arenas. The disposable service stack was subsequently removed;
see [stack cleanup](ui-r2-stack-cleanup-2026-10-16.log). The checked-in reports and
screenshots remain available after disposable stack cleanup.

## Release and review

[Independent review](ui-r2-review-2026-10-16.md) found two important issues, both
fixed and re-reviewed with no important findings remaining. Regression coverage
includes historical refutation with a failed control, operator/agent and arena
boundaries, post-teardown reads, and confirmation with missing, corrupt,
foreign-arena or failed prerequisite evidence. Frontend TypeScript, formatting
and production build passed.

Final `make release-check` passed in pinned Python 3.11.14: Ruff passed, Bandit
reported no issues; SQLite had 1,123 passed, four skipped and six integrations
deselected; PostgreSQL had 1,127 passed and six integrations deselected. Clean
migrations and API/UI/gateway readiness smoke passed. Retained log:
[ui-r2-final-release-2026-10-16.log](ui-r2-final-release-2026-10-16.log).
Text logs trim terminal trailing spaces for Git; `.log.gz` siblings preserve the
original bytes losslessly. The earlier [interrupted log](ui-r2-release-2026-10-16.log) ends during security
analysis after the terminal/server interruption and is not counted as a pass.

Failed live harness attempts are retained rather than overwritten:
`ui-r2-live-2026-10-15-d3ef9015.json` (arena-name validation),
`7697184d` (duplicate synthetic agent-key setup), `b3481753` (browser expectation
against the pre-review-fix build), and `3532ce6a` (budget deadline beyond expiry).
Only the final `42495585` run is acceptance evidence.

## Limits and next step

Structured adapters cover authorization_effect/v1, single_use_grant_effect/v1 and
http_access_control/v1. The live proof covers authorization and generic HTTP control
failure; single-use grants have no additional UI-specific live proof here.
Unsupported validators and historical records without retained expectation context
remain unresolved. No arbitrary standalone Paperless JSON import, general hypothesis
editor, source-review UI, named request groups or request comparison is included.
Paperless registration artifacts and registered executables are unchanged; the new
calibration evidence does not replace their dated conclusions. Docker-local remains
the only live-verified provider.

Next: design approval for UI-R3 request comparison, as a separate slice. Source
browsing follows later. Existing historical proof gaps and manual source-semantic
review remain unchanged.
