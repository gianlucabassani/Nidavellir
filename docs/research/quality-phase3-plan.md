# Research quality phase — 2026-10-11

Authorized scope: repair RESEARCH-R7/R8/R9/R10, actively verify the Docker-local
research path, then propose research usability work from observed friction.

1. Retain an unchanged-code, committed-registration Paperless baseline.
2. Repair metadata-only auditing of admitted code-intel failures. Explicitly
   define authoring queries as unbudgeted operator work; arena budgets still apply
   to arena execution.
3. Repair mutation permissions, member-owned controls, mixed-batch survival and
   failed-control verdict gating. Register changed executable definitions before
   fresh live probing.
4. Retain every static-search residual and affected/fixed rule evidence. Keep
   heuristic and manual-review limits explicit.
5. Reconcile unsupported historical claims without rewriting old artifacts.
6. Run the pinned release gate and real research lifecycle/API/MCP checks, verify
   teardown and retained evidence, update delivery records, obtain code review.
7. Propose a small research usability plan, with primary-source product examples;
   implementation waits for design approval.

## Execution rulings

- Clean in-place branch `research/quality-phase3` provides isolation from main.
  A second worktree is unnecessary for this single-implementer task.
- Baseline registration commit: `41918e0`; baseline evidence:
  `docs/verification/paperless-quality-baseline-2026-10-11.json`.
  Its refutation labels are reproduced defects, not accepted conclusions.
- Host Python lacks dependencies and the local virtualenv TestClient hangs.
  Focused checks use the pinned Python 3.11 verification container.
- Historical logs/claims remain historical; a new passing run cannot validate them.
- Only disposable task resources may be removed. Existing unrelated stacks remain
  outside scope.

## Current status

Local implementation and active checks complete. Final registration `b059439`
matches the executed sources; twelve rows retain concrete requests and controls.
Complete current inventories and nine affected/fixed source shapes are retained.
REST/MCP and the Docker browser/HTTP research gate pass. Code review found no
remaining serious issue. See the 2026-10-12 closure report for scoped conclusions.

The new evidence writers refuse to overwrite existing files. Registration commits
remain separate so each empirical refinement has an immutable prior registration;
merge with a merge commit to preserve their ancestry. Source-query semantic review
remains manual. The verified branch is published to the current GitLab origin.
The earlier GitHub suspension response concerned the separately configured old
remote. The user authorized integration into main on 2026-10-14.
